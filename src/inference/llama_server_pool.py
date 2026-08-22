"""Subprocess pool for `llama-server` instances.

The Python sidecar manages one or more `llama-server` subprocesses
(one per active model profile). The pool:

  - **Spawns on demand** — first inference request for a profile
    launches the subprocess, allocates a port, waits for `/health`.
  - **Keeps warm** — subsequent requests reuse the running instance.
  - **LRU-evicts** when `LLAMA_SERVER_MAX_LOADED_MODELS` is exceeded
    (default 1 — one profile loaded at a time on local machines).
  - **Idle-unloads** profiles untouched for `LLAMA_SERVER_IDLE_TIMEOUT_S`.
  - **Cleans up at exit** — SIGTERM trap + atexit handler kill every
    spawned subprocess so we never leave orphan llama-server processes.
  - **Fails loud, not silent** — if a subprocess dies unexpectedly, log
    its tail-stderr and surface to the caller with a clear error. We
    deliberately do NOT auto-restart in PR 1; auto-restart hides real
    failures (OOM, bad model, version mismatch). Add later if telemetry
    justifies it.

Spec: `Specs/llama_server_migration.md`.
"""

from __future__ import annotations

import atexit
import collections
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.inference.llama_server_binary import resolve_and_check
from src.inference.profiles import ModelProfile, get_profile
from src.subproc import no_window_kwargs


# ---------------------------------------------------------------------------
# Tunables (env-overridable; see .env.example)
# ---------------------------------------------------------------------------

DEFAULT_BASE_PORT = 9100
"""First port the pool tries when spawning a new instance. NOT 8765 —
that's the FastAPI sidecar. The pool walks forward (9100, 9101, ...)
until it finds one not bound."""

DEFAULT_MAX_LOADED_MODELS = 1
"""How many subprocesses can be live concurrently. 1 = sequential
(LRU eviction on each new profile). Bump on RAM-rich dev boxes."""

DEFAULT_IDLE_TIMEOUT_S = 600
"""Unload a subprocess after this many seconds of inactivity. Frees
the model's RAM. Set to 0 to disable idle eviction."""

DEFAULT_STARTUP_TIMEOUT_S = 60
"""How long to wait for `/health` to return 200 after spawning. Larger
models need longer cold-load; the timeout should accommodate the
slowest profile + a margin."""

# Background thread polls every N seconds for idle eviction. Cheap.
_IDLE_CHECK_INTERVAL_S = 30.0


# ---------------------------------------------------------------------------
# Loaded-instance state
# ---------------------------------------------------------------------------


@dataclass
class _LoadedInstance:
    """One running llama-server subprocess."""

    profile: ModelProfile
    process: subprocess.Popen
    port: int
    base_url: str  # e.g. http://127.0.0.1:9100
    spawned_at: float
    last_used: float = field(default_factory=time.monotonic)
    # Tail buffer of recent stderr lines, used in error reporting when
    # the subprocess crashes. Bounded so a chatty server doesn't OOM
    # the sidecar.
    stderr_tail: deque = field(default_factory=lambda: deque(maxlen=50))


class LlamaServerSpawnError(RuntimeError):
    """Subprocess failed to start or pass health-check. Carries the
    binary path + last 50 stderr lines so the user can debug fast."""


class LlamaServerCrashError(RuntimeError):
    """An inference call discovered the subprocess was no longer alive.
    Caller's request fails; the pool is reset to "no instance" so the
    next call tries to respawn cleanly."""


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------


class LlamaServerPool:
    """Manages the lifecycle of a small fleet of llama-server subprocesses.

    Concurrency model: every public method (`get_url_for`, `evict`,
    `shutdown`) takes `self._lock`. The lock is held only for state
    mutation — actual subprocess spawning + `/health` polling happen
    under it but the cost is bounded (~startup_timeout_s in the worst
    case). For a desktop RAG app this is fine; if we ever need
    concurrent multi-profile fan-out we'd refactor to per-profile locks.
    """

    def __init__(
        self,
        *,
        base_port: int | None = None,
        max_loaded_models: int | None = None,
        idle_timeout_s: int | None = None,
        startup_timeout_s: int | None = None,
    ) -> None:
        self.base_port = int(
            base_port if base_port is not None
            else os.environ.get("LLAMA_SERVER_BASE_PORT", DEFAULT_BASE_PORT)
        )
        self.max_loaded_models = int(
            max_loaded_models if max_loaded_models is not None
            else os.environ.get("LLAMA_SERVER_MAX_LOADED_MODELS", DEFAULT_MAX_LOADED_MODELS)
        )
        self.idle_timeout_s = int(
            idle_timeout_s if idle_timeout_s is not None
            else os.environ.get("LLAMA_SERVER_IDLE_TIMEOUT_S", DEFAULT_IDLE_TIMEOUT_S)
        )
        self.startup_timeout_s = int(
            startup_timeout_s if startup_timeout_s is not None
            else os.environ.get("LLAMA_SERVER_STARTUP_TIMEOUT_S", DEFAULT_STARTUP_TIMEOUT_S)
        )

        # Insertion-ordered for LRU semantics: oldest entry is the
        # eviction candidate.
        self._instances: "collections.OrderedDict[str, _LoadedInstance]" = (
            collections.OrderedDict()
        )
        self._lock = threading.RLock()
        self._binary: Optional[Path] = None  # resolved lazily
        self._installed_handlers = False
        self._idle_thread: Optional[threading.Thread] = None
        self._shutdown = threading.Event()

    # --- public API ---------------------------------------------------------

    def get_url_for(self, profile_name: str) -> str:
        """Return the base URL of a running llama-server for `profile_name`,
        spawning it (and possibly evicting an LRU instance) if needed.

        Caller appends `/v1/chat/completions` etc. and makes HTTP calls.
        Returned URL is stable for the life of the instance — no need to
        re-resolve per request unless the call fails with a connection
        error (in which case `mark_dead` is the recovery path).
        """
        with self._lock:
            self._ensure_setup()
            inst = self._instances.get(profile_name)
            if inst is not None and self._is_alive(inst):
                # Move to most-recently-used; refresh last_used.
                self._instances.move_to_end(profile_name)
                inst.last_used = time.monotonic()
                return inst.base_url

            # Stale entry (subprocess died) — clear it before spawning.
            if inst is not None and not self._is_alive(inst):
                self._handle_dead_instance(profile_name, inst)

            return self._spawn_locked(profile_name)

    def mark_dead(self, profile_name: str) -> None:
        """Caller observed a connection error against a known instance.
        Drop the registry entry so the next `get_url_for` respawns."""
        with self._lock:
            inst = self._instances.pop(profile_name, None)
            if inst is not None:
                self._terminate(inst)

    def evict(self, profile_name: str) -> bool:
        """Manually unload a profile. Returns True if it was loaded."""
        with self._lock:
            inst = self._instances.pop(profile_name, None)
            if inst is None:
                return False
            self._terminate(inst)
            return True

    def shutdown(self) -> None:
        """Kill every running subprocess. Idempotent. Called at process
        exit via atexit and by SIGTERM/SIGINT handlers."""
        with self._lock:
            self._shutdown.set()
            for name, inst in list(self._instances.items()):
                self._terminate(inst)
            self._instances.clear()

    def loaded_profiles(self) -> list[str]:
        """For diagnostics — names of currently-running instances, MRU first."""
        with self._lock:
            # OrderedDict iterates in insertion order; reverse for MRU first.
            return list(reversed(list(self._instances.keys())))

    # --- internals ----------------------------------------------------------

    def _ensure_setup(self) -> None:
        """One-time initialization: resolve the binary, install signal
        handlers, start the idle-eviction thread. Called under lock."""
        if self._binary is None:
            self._binary = resolve_and_check()
        if not self._installed_handlers:
            self._install_handlers()
            self._installed_handlers = True
        if self._idle_thread is None and self.idle_timeout_s > 0:
            self._idle_thread = threading.Thread(
                target=self._idle_loop, daemon=True, name="llama-server-idle"
            )
            self._idle_thread.start()

    def _spawn_locked(self, profile_name: str) -> str:
        """Spawn a new llama-server subprocess for `profile_name`. Lock held."""
        # Evict before spawning if we're at capacity. LRU = first inserted.
        while len(self._instances) >= self.max_loaded_models:
            lru_name, lru_inst = next(iter(self._instances.items()))
            print(
                f"  llama-server: evicting LRU profile {lru_name!r} "
                f"to load {profile_name!r}",
                file=sys.stderr,
            )
            self._instances.pop(lru_name)
            self._terminate(lru_inst)

        profile = get_profile(profile_name)
        port = self._allocate_port()
        argv = self._build_argv(profile, port)

        print(
            f"  llama-server: spawning {profile_name!r} on port {port} "
            f"(pid: pending)",
            file=sys.stderr,
        )
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
            # Windows: don't flash a console window for the server process.
            **no_window_kwargs(),
        )
        base_url = f"http://127.0.0.1:{port}"
        inst = _LoadedInstance(
            profile=profile,
            process=process,
            port=port,
            base_url=base_url,
            spawned_at=time.monotonic(),
        )

        # Drain stderr in a background thread so we don't deadlock on a
        # full pipe AND we keep the last 50 lines for crash diagnostics.
        threading.Thread(
            target=self._drain_stderr,
            args=(profile_name, inst),
            daemon=True,
            name=f"llama-server-stderr-{profile_name}",
        ).start()
        threading.Thread(
            target=self._drain_stdout,
            args=(profile_name, inst),
            daemon=True,
            name=f"llama-server-stdout-{profile_name}",
        ).start()

        # Health-check: poll `/health` until it returns 200 or we time out.
        deadline = time.monotonic() + self.startup_timeout_s
        last_err: Optional[str] = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                # Process died during startup — surface the stderr tail.
                tail = "\n".join(inst.stderr_tail)
                raise LlamaServerSpawnError(
                    f"llama-server for profile {profile_name!r} exited during "
                    f"startup (return code {process.returncode}). "
                    f"Last stderr:\n{tail}"
                )
            try:
                if _http_health_ok(base_url):
                    self._instances[profile_name] = inst
                    print(
                        f"  llama-server: {profile_name!r} ready on {base_url} "
                        f"(pid {process.pid}, {time.monotonic() - inst.spawned_at:.1f}s)",
                        file=sys.stderr,
                    )
                    return base_url
            except OSError as e:
                last_err = str(e)
            time.sleep(0.25)

        # Timed out — kill the subprocess and raise.
        self._terminate(inst)
        tail = "\n".join(inst.stderr_tail)
        raise LlamaServerSpawnError(
            f"llama-server for profile {profile_name!r} did not pass health "
            f"check within {self.startup_timeout_s}s on {base_url}. "
            f"Last error: {last_err}. Last stderr:\n{tail}"
        )

    def _build_argv(self, profile: ModelProfile, port: int) -> list[str]:
        """Translate a ModelProfile into a llama-server command line.

        Resolves the GGUF (always) and the mmproj projector (when the
        profile declares one) via `model_downloader`, both cached under
        `<APP_DATA_DIR>/cache/hub/`. The mmproj is downloaded lazily on
        first vision-profile spawn — slow connections see this as a
        ~900 MB pause, which `just install-llama-server` pre-empts by
        downloading it eagerly.
        """
        from src.inference.model_downloader import ensure_model, ensure_mmproj

        gguf = ensure_model(profile.args.repo_id, profile.args.quant)
        argv: list[str] = [
            str(self._binary),
            "--model", str(gguf),
            "--port", str(port),
            "--host", "127.0.0.1",
            "-ngl", str(profile.args.ngl),
            "-c", str(profile.args.ctx_size),
            "--temp", str(profile.args.temperature),
        ]
        # mmproj resolution: explicit path wins (test fixtures), else
        # download from the repo when mmproj_repo_id is set.
        mmproj_path: Optional[str] = profile.args.mmproj
        if mmproj_path is None and profile.args.mmproj_repo_id:
            mmproj_path = str(
                ensure_mmproj(
                    profile.args.mmproj_repo_id,
                    profile.args.mmproj_variant,
                )
            )
        if mmproj_path:
            argv.extend(["--mmproj", mmproj_path])
        if profile.args.batch_size is not None:
            argv.extend(["-b", str(profile.args.batch_size)])
        if profile.args.ubatch_size is not None:
            argv.extend(["-ub", str(profile.args.ubatch_size)])
        if profile.args.threads is not None:
            argv.extend(["-t", str(profile.args.threads)])
        if profile.args.jinja:
            argv.append("--jinja")
        argv.extend(profile.args.extra_args)
        return argv

    def _allocate_port(self) -> int:
        """Find a free port starting from `self.base_port`. Avoid reusing
        ports that are already loaded by other live profiles in our pool."""
        in_use = {inst.port for inst in self._instances.values()}
        port = self.base_port
        while True:
            if port in in_use:
                port += 1
                continue
            if _port_is_free(port):
                return port
            port += 1

    def _is_alive(self, inst: _LoadedInstance) -> bool:
        """True if the subprocess is still running."""
        return inst.process.poll() is None

    def _handle_dead_instance(self, name: str, inst: _LoadedInstance) -> None:
        """A registered instance was found dead. Log loudly with the
        stderr tail; do NOT auto-restart (per spec)."""
        tail = "\n".join(inst.stderr_tail) or "(no stderr captured)"
        print(
            f"  llama-server: profile {name!r} subprocess died unexpectedly "
            f"(returncode={inst.process.returncode}). Last stderr:\n{tail}",
            file=sys.stderr,
        )
        self._instances.pop(name, None)

    def _terminate(self, inst: _LoadedInstance) -> None:
        """Best-effort kill. SIGTERM first, then SIGKILL after a timeout."""
        if inst.process.poll() is not None:
            return  # already dead
        try:
            inst.process.terminate()
            inst.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            inst.process.kill()
            try:
                inst.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass

    def _drain_stderr(self, name: str, inst: _LoadedInstance) -> None:
        """Background reader for the subprocess's stderr. Always keeps
        the last 50 lines in the instance's tail buffer for crash
        reports. Only mirrors lines to the sidecar's stderr when
        `LLAMA_SERVER_VERBOSE=1` — otherwise the per-token slot/sched
        chatter (~30 lines per inference) drowns out the walker's
        progress bar.

        Even in quiet mode we still surface the highest-signal lines
        (errors, warnings, "model loaded") so you can tell something is
        happening; the rest goes only to the tail buffer where the
        spawn-failure / crash paths can dump it on demand.
        """
        if inst.process.stderr is None:
            return
        verbose = os.environ.get("LLAMA_SERVER_VERBOSE") == "1"
        for line in iter(inst.process.stderr.readline, ""):
            line = line.rstrip("\n")
            inst.stderr_tail.append(line)
            if verbose or _is_high_signal(line):
                print(f"[llama-server:{name}] {line}", file=sys.stderr)

    def _drain_stdout(self, name: str, inst: _LoadedInstance) -> None:
        """Same as _drain_stderr but for stdout. llama-server is mostly
        chatty on stderr, but a few lines (e.g. JSON-RPC trace if enabled)
        come from stdout. Don't let it fill the pipe.

        Same verbose gating as stderr — silent unless `LLAMA_SERVER_VERBOSE=1`
        or the line matches a high-signal pattern.
        """
        if inst.process.stdout is None:
            return
        verbose = os.environ.get("LLAMA_SERVER_VERBOSE") == "1"
        for line in iter(inst.process.stdout.readline, ""):
            line = line.rstrip("\n")
            if verbose or _is_high_signal(line):
                print(f"[llama-server:{name}] {line}", file=sys.stderr)

    # --- shutdown / cleanup -------------------------------------------------

    def _install_handlers(self) -> None:
        """SIGTERM / SIGINT / atexit — three lines of defense against
        leaving orphan subprocesses. The atexit handler covers normal
        Python exit; the signal handlers cover Ctrl-C and the daemon
        receiving SIGTERM from launchctl/systemd. SIGKILL of the parent
        is uncatchable — kernel reaps the children via PR_SET_PDEATHSIG
        on Linux, but on macOS subprocesses survive SIGKILL of the
        parent. The end-to-end smoke test must verify on macOS too."""
        atexit.register(self.shutdown)

        if threading.current_thread() is not threading.main_thread():
            # Signal handlers must be installed from the main thread.
            return

        def _on_signal(signum, _frame):
            print(
                f"  llama-server: received signal {signum}, shutting down "
                f"{len(self._instances)} subprocess(es)",
                file=sys.stderr,
            )
            self.shutdown()
            # Re-raise the default behavior so the parent process exits
            # the way it normally would.
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _on_signal)
            except ValueError:
                # Some test/embedded contexts can't install handlers; OK.
                pass

    def _idle_loop(self) -> None:
        """Background thread that unloads idle profiles."""
        while not self._shutdown.is_set():
            if self._shutdown.wait(timeout=_IDLE_CHECK_INTERVAL_S):
                return
            now = time.monotonic()
            evicted: list[str] = []
            with self._lock:
                for name, inst in list(self._instances.items()):
                    if now - inst.last_used > self.idle_timeout_s:
                        evicted.append(name)
                        self._instances.pop(name)
                        self._terminate(inst)
            for name in evicted:
                print(
                    f"  llama-server: idle-evicted {name!r} after "
                    f"{self.idle_timeout_s}s",
                    file=sys.stderr,
                )


# ---------------------------------------------------------------------------
# Helpers (module-level so unit tests can mock them cleanly)
# ---------------------------------------------------------------------------


# High-signal markers worth surfacing even in quiet mode. The default is
# silence: per-inference llama-server emits ~30 lines per request (slot
# selection, sched_reserve, image decode, eval timing, etc.) and that
# floods walker tqdm output. Errors + lifecycle events (model loaded,
# warnings) we always show.
_HIGH_SIGNAL_SUBSTRINGS = (
    "error",
    "ERROR",
    "warning:",
    "warn:",
    " WARN ",
    "failed",
    "panic",
    "abort",
    "model loaded",
    "server is listening",
)


def _is_high_signal(line: str) -> bool:
    """Cheap substring match — keeps the helper fast on the hot path
    (every stderr line from every subprocess passes through it)."""
    return any(s in line for s in _HIGH_SIGNAL_SUBSTRINGS)


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """True iff we can bind `host:port`. Race-y by nature (the port
    might get grabbed before our spawn) but good enough for sequential
    spawning in a single sidecar."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def _http_health_ok(base_url: str, timeout: float = 1.0) -> bool:
    """Cheap GET `/health`. Used during spawn to wait for readiness.

    llama-server's `/health` returns 200 with body `{"status":"ok"}`
    once the model is loaded. Before that it 503s, which we want to
    treat as "not ready yet, keep polling" — so any non-200 → False."""
    import http.client
    from urllib.parse import urlparse

    url = urlparse(base_url)
    try:
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=timeout)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        ok = resp.status == 200
        resp.read()
        conn.close()
        return ok
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


_pool: Optional[LlamaServerPool] = None
_pool_lock = threading.Lock()


def get_pool() -> LlamaServerPool:
    """Process-wide pool singleton."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = LlamaServerPool()
    return _pool
