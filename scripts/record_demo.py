"""Record the Magpie window and produce the README demo assets.

Captures the *Magpie window only* — never the whole desktop. That is a
deliberate safety default, not a nicety: a full-screen grab of a dev machine
picks up secrets, mail, and whatever else is on screen, and a demo GIF is the
single most-shared artifact a project has. If the window can't be located the
script stops rather than falling back to the full display.

    uv run python scripts/record_demo.py

It writes two files into docs/assets/:

    demo.mp4    high-quality H.264, for social / the pitch deck
    demo.gif    palette-optimised, sized for the README

Both are derived from one capture, so they always show the same take.

Capture backend per OS (all via ffmpeg, which must be on PATH):

    Linux/X11   x11grab, window geometry from xdotool
    Windows     gdigrab with `title=`, which targets the window directly
    macOS       avfoundation grabs the whole display, then we crop to the
                window rect — avfoundation has no per-window input

Wayland is not supported: there is no X window to point at, and the portal
based recorders (wf-recorder, gpu-screen-recorder) each want their own
handling. Run the demo capture from an X session.

Drive the app yourself while this runs. A good take is roughly:
summon with the global shortcut, type one real question, let the answer
stream in, arrow down through the sources, open one. Fifteen seconds.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
OUT_DIR = ROOT / "docs" / "assets"

WINDOW_TITLE = "Magpie"  # matches app.windows[].title in tauri.conf.json
SECONDS = 15
COUNTDOWN = 5  # time to summon the window before recording starts

# Magpie doesn't unmap itself when it hides — it parks the window off-screen
# at a large negative X and leaves it mapped. So "is it visible?" is a
# coordinate test, not a mapped test, and x11grab on a negative origin dies
# with BadMatch rather than recording anything.
RESTING_HEIGHT = 300  # taller than this means it has expanded to show an answer

CAPTURE_FPS = 30
GIF_FPS = 12
GIF_WIDTH = 900  # GitHub renders README images at ~900px max usefully
GIF_WARN_MB = 10  # GitHub gets unhappy well before this


def need(binary: str) -> str:
    found = shutil.which(binary)
    if not found:
        sys.exit(f"{binary} is not on PATH — install it and re-run.")
    return found


def window_rect() -> tuple[int, int, int, int]:
    """(x, y, width, height) of the Magpie window, in display pixels."""
    system = platform.system()

    if system == "Linux":
        need("xdotool")
        found = subprocess.run(
            ["xdotool", "search", "--name", f"^{WINDOW_TITLE}$"],
            capture_output=True, text=True,
        ).stdout.split()
        if not found:
            sys.exit(
                f"No window titled {WINDOW_TITLE!r}. Start the app first\n"
                "  (pnpm tauri dev, or the packaged build) and summon it."
            )
        # A Tauri app can own several X windows; the biggest is the real one.
        best, best_area = None, -1
        for wid in found:
            out = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", wid],
                capture_output=True, text=True,
            ).stdout
            geom = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
            w, h = int(geom.get("WIDTH", 0)), int(geom.get("HEIGHT", 0))
            if w * h > best_area:
                best, best_area = (int(geom["X"]), int(geom["Y"]), w, h), w * h
        return best

    if system == "Darwin":
        # No per-window capture on avfoundation, so ask the window server.
        script = (
            f'tell application "System Events" to tell process "{WINDOW_TITLE}" '
            "to get {position, size} of window 1"
        )
        out = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        )
        if out.returncode != 0:
            sys.exit(
                f"Could not read the {WINDOW_TITLE} window rect.\n"
                "Grant Terminal accessibility access in System Settings → "
                "Privacy & Security → Accessibility, and make sure the app is running."
            )
        x, y, w, h = (int(float(n)) for n in out.stdout.replace(",", " ").split())
        return x, y, w, h

    # Windows: gdigrab targets the window by title, so no rect needed.
    return 0, 0, 0, 0


def capture_args(rect: tuple[int, int, int, int]) -> list[str]:
    x, y, w, h = rect
    system = platform.system()

    if system == "Linux":
        # x11grab wants even dimensions for yuv420p.
        w, h = w - (w % 2), h - (h % 2)
        return [
            "-f", "x11grab", "-framerate", str(CAPTURE_FPS),
            "-video_size", f"{w}x{h}", "-i", f":0.0+{x},{y}",
        ]

    if system == "Windows":
        return [
            "-f", "gdigrab", "-framerate", str(CAPTURE_FPS),
            "-i", f"title={WINDOW_TITLE}",
        ]

    if system == "Darwin":
        w, h = w - (w % 2), h - (h % 2)
        return [
            "-f", "avfoundation", "-framerate", str(CAPTURE_FPS),
            "-capture_cursor", "1", "-i", "1:none",
            "-vf", f"crop={w}:{h}:{x}:{y}",
        ]

    sys.exit(f"No capture backend for {system}.")


def main() -> None:
    ffmpeg = need("ffmpeg")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rect = window_rect()
    if platform.system() != "Windows":
        x, y, w, h = rect
        if x < 0 or y < 0:
            sys.exit(
                f"Magpie is hidden — the window is parked off-screen at ({x}, {y}).\n"
                "  Press the global shortcut to summon it, then run this again.\n"
                "  It has to be summoned from the keyboard: the shortcut is an OS-level\n"
                "  grab, and synthetic key events don't reach it."
            )
        print(f"Magpie window: {w}x{h} at ({x}, {y})")
        if h <= RESTING_HEIGHT:
            print(
                f"  It is at resting height ({h}px). The region is fixed for the whole\n"
                "  take, so an answer expanding past it would be cropped off. Ask a\n"
                "  question first, leave the answer on screen, then run this again."
            )

    print(f"Recording {SECONDS}s. Drive the app — ask one real question.")
    for n in range(COUNTDOWN, 0, -1):
        print(f"  {n}...", end="\r", flush=True)
        time.sleep(1)
    print("  recording  ")

    raw = OUT_DIR / "demo.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         *capture_args(rect),
         "-t", str(SECONDS),
         "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", str(raw)],
        check=True,
    )
    print(f"wrote {raw.relative_to(ROOT)}  ({raw.stat().st_size / 1e6:.1f} MB)")

    # Two-pass GIF: build a palette from the whole clip, then apply it.
    # One-pass GIF uses the stock 216-colour web palette and looks like 1998.
    gif = OUT_DIR / "demo.gif"
    chain = f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos"
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
         "-filter_complex",
         f"[0:v]{chain},split[a][b];[a]palettegen=stats_mode=diff[p];"
         f"[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
         str(gif)],
        check=True,
    )
    size_mb = gif.stat().st_size / 1e6
    print(f"wrote {gif.relative_to(ROOT)}  ({size_mb:.1f} MB)")
    if size_mb > GIF_WARN_MB:
        print(
            f"  that is over {GIF_WARN_MB} MB — GitHub will be slow to load it.\n"
            f"  Drop GIF_FPS or GIF_WIDTH at the top of this script and re-run\n"
            f"  (it re-encodes from demo.mp4, no need to record again)."
        )

    print("\nnext: swap the TODO comment at the top of README.md for")
    print('      <p align="center"><img src="docs/assets/demo.gif" width="700" /></p>')


if __name__ == "__main__":
    main()
