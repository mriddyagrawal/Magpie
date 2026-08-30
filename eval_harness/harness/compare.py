"""Deterministic pairwise comparison of eval-harness runs.

Usage:
    uv run python eval_harness/harness/compare.py RUN_A RUN_B [RUN_C ...] \
        [--out DIR] [--force-intersection] [--allow-incomplete]

RUN_A is the BASELINE; every other run is compared against it pairwise.
Runs are given as paths to run directories (or bare run ids resolved
against eval_harness/runs/).

Produces, in --out (default eval_harness/comparisons/<utc>-<A>-vs-<B...>/):
    comparison.json   machine-readable full diff
    COMPARISON.md     human tables + auto-inserted caveats; the
                      /magpie-compare skill's agents append their
                      cause-attribution and verdict below the marker line.

Design rules (mirroring the harness's own):
  - Read-only over run directories. Never mutates a run.
  - Comparability is judged on the triple (params, backend_git_sha,
    golden_sha). The report names WHICH axes differ; multi-axis
    comparisons are flagged as confounded, not refused.
  - golden_sha mismatch degrades to INTERSECTION mode: only qa_ids whose
    (question, golden_answer) match byte-for-byte are paired. Coverage
    below 50% refuses unless --force-intersection.
  - Paired stats only: discordant counts + exact McNemar p. With ~60-120
    questions, fewer than ~5 discordant flips is not credibly non-noise;
    the report says so instead of hiding it behind a rate.
  - Judge verdicts are authoritative for answer quality when present in
    BOTH runs; the deterministic verdict is always reported alongside.
    Retrieval per-question numbers prefer the end_to_end basis (what ask()
    actually returned) and fall back to ranked_pre_gate for runs enriched
    before that field existed (#117); the basis used is stamped in the
    output because the two are known to disagree on some questions.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
REPO = EVAL.parent
RUNS = EVAL / "runs"
COMPARISONS = EVAL / "comparisons"

VERDICTS = ["correct", "partial", "wrong", "false_abstain", "correct_abstain", "false_answer"]
GOOD_VERDICTS = {"correct", "correct_abstain"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def resolve_run(arg: str) -> Path:
    p = Path(arg)
    if p.is_dir():
        return p.resolve()
    cand = RUNS / arg
    if cand.is_dir():
        return cand.resolve()
    sys.exit(f"compare: run not found: {arg}")


def load_run(run_dir: Path, allow_incomplete: bool) -> dict:
    rj = run_dir / "run.json"
    if not rj.is_file():
        sys.exit(f"compare: {run_dir} has no run.json")
    run = json.loads(rj.read_text(encoding="utf-8"))
    status = run.get("status")
    if status != "complete" and not allow_incomplete:
        sys.exit(
            f"compare: {run_dir.name} status={status!r} (not complete). "
            "Pass --allow-incomplete to compare anyway."
        )
    out = {
        "dir": run_dir,
        "name": run_dir.name,
        "run": run,
        "metrics": None,
        "rows": None,
        "judge": None,
    }
    mj = run_dir / "metrics.json"
    if mj.is_file():
        out["metrics"] = json.loads(mj.read_text(encoding="utf-8"))
    ae = run_dir / "answers_enriched.json"
    if ae.is_file():
        rows = json.loads(ae.read_text(encoding="utf-8"))
        out["rows"] = {r["qa_id"]: r for r in rows}
    jv = run_dir / "judge_verdicts.json"
    if jv.is_file():
        out["judge"] = json.loads(jv.read_text(encoding="utf-8"))
    return out


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p over discordant counts b (A-only) and c
    (B-only). p = 2 * P(X <= min(b,c)) under Binomial(b+c, 0.5), capped
    at 1.0. Returns 1.0 when there are no discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


def paired_binary(pairs: list[tuple[bool, bool]]) -> dict:
    """Aggregate a list of (a_outcome, b_outcome) booleans."""
    a_only = sum(1 for a, b in pairs if a and not b)
    b_only = sum(1 for a, b in pairs if b and not a)
    both = sum(1 for a, b in pairs if a and b)
    neither = sum(1 for a, b in pairs if not a and not b)
    n = len(pairs)
    return {
        "n": n,
        "a_rate": round((a_only + both) / n, 4) if n else None,
        "b_rate": round((b_only + both) / n, 4) if n else None,
        "delta": round((b_only - a_only) / n, 4) if n else None,
        "discordant_a_only": a_only,
        "discordant_b_only": b_only,
        "concordant_both": both,
        "concordant_neither": neither,
        "mcnemar_p": round(mcnemar_exact(a_only, b_only), 5),
        # #116: credible means DECISION-GRADE - enough flips to detect an
        # effect AND a split lopsided enough that coin-luck is a poor
        # explanation. Volume alone stamped p=1.0 nulls (a perfectly
        # balanced split, the most noise-like outcome possible) credible.
        "enough_discordant": (a_only + b_only) >= 5,
        "credible": (a_only + b_only) >= 5 and mcnemar_exact(a_only, b_only) < 0.05,
    }


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def pair_questions(a: dict, b: dict, force_intersection: bool) -> tuple[list[str], str, float]:
    """Return (qa_ids, mode, coverage). mode is 'full' when golden_sha
    matches, else 'intersection' (byte-identical question+golden_answer)."""
    rows_a, rows_b = a["rows"], b["rows"]
    if rows_a is None or rows_b is None:
        sys.exit("compare: both runs need answers_enriched.json (run enrich first)")
    same_golden = a["run"].get("golden_sha") == b["run"].get("golden_sha")
    if same_golden:
        common = sorted(set(rows_a) & set(rows_b))
        cov = len(common) / max(len(rows_a), len(rows_b)) if rows_a else 0.0
        return common, "full", round(cov, 4)
    common = sorted(
        qid for qid in set(rows_a) & set(rows_b)
        if rows_a[qid].get("question") == rows_b[qid].get("question")
        and rows_a[qid].get("golden_answer") == rows_b[qid].get("golden_answer")
    )
    cov = len(common) / max(len(rows_a), len(rows_b)) if rows_a else 0.0
    if cov < 0.5 and not force_intersection:
        sys.exit(
            f"compare: golden_sha differs and only {cov:.0%} of questions match "
            "byte-for-byte - these runs answered different questions. "
            "Pass --force-intersection to compare the overlap anyway."
        )
    return common, "intersection", round(cov, 4)


# ---------------------------------------------------------------------------
# Axis / provenance diff
# ---------------------------------------------------------------------------


def dict_diff(da: dict, db: dict) -> dict:
    keys = sorted(set(da) | set(db))
    out = {}
    for k in keys:
        va, vb = da.get(k, "<absent>"), db.get(k, "<absent>")
        if va != vb:
            out[k] = {"a": va, "b": vb}
    return out


def git_log_between(sha_a: str, sha_b: str, pathspec: str) -> list[str]:
    if not sha_a or not sha_b or sha_a == sha_b:
        return []
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO), "log", "--oneline", f"{sha_a}..{sha_b}", "--", pathspec],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return [f"(git log failed: {r.stderr.strip()[:120]})"]
        return [l for l in r.stdout.splitlines() if l.strip()]
    except Exception as e:  # noqa: BLE001 - provenance nicety, never fatal
        return [f"(git log unavailable: {e})"]


def axes(a: dict, b: dict) -> dict:
    ra, rb = a["run"], b["run"]
    params_diff = dict_diff(ra.get("params", {}), rb.get("params", {}))
    params_diff.pop("_notes", None)
    backend_changed = ra.get("backend_git_sha") != rb.get("backend_git_sha")
    golden_changed = ra.get("golden_sha") != rb.get("golden_sha")
    changed = []
    if params_diff:
        changed.append("config")
    if backend_changed:
        changed.append("code")
    if golden_changed:
        changed.append("questions")
    env_diff = dict_diff(ra.get("env_snapshot", {}) or {}, rb.get("env_snapshot", {}) or {})
    # #115: a comparison is confounded whenever MORE THAN ONE KNOB moved,
    # not just when more than one axis category moved - a config diff of
    # {top_k, rewrite} is a two-factor change even though it is one "axis".
    n_knobs = len(params_diff) + int(backend_changed) + int(golden_changed)
    return {
        "changed_axes": changed or ["none"],
        "changed_knobs": sorted(params_diff)
        + (["<code>"] if backend_changed else [])
        + (["<questions>"] if golden_changed else []),
        "confounded": n_knobs > 1,
        "params_diff": params_diff,
        "backend_git_sha": {"a": ra.get("backend_git_sha"), "b": rb.get("backend_git_sha")},
        "backend_commits_between": (
            git_log_between(ra.get("backend_git_sha"), rb.get("backend_git_sha"), "src/")
            if backend_changed else []
        ),
        "harness_git_sha": {"a": ra.get("harness_git_sha"), "b": rb.get("harness_git_sha")},
        "golden_sha": {"a": ra.get("golden_sha"), "b": rb.get("golden_sha")},
        "env_snapshot_diff": env_diff,
        "solo_gate_structurally_off": {
            "a": ra.get("solo_gate_structurally_off"),
            "b": rb.get("solo_gate_structurally_off"),
        },
        "rerank_coupling_warning": (
            "rerank differs between runs: per #112 this is a rerank+solo-gate "
            "two-factor change, not a rerank ablation"
        ) if "rerank" in params_diff else None,
    }


# ---------------------------------------------------------------------------
# Per-question comparison
# ---------------------------------------------------------------------------


def _latency_total(v) -> float | None:
    """Runs store latency_s either as a scalar or as a dict of phase
    timings with a 'total' key (found the hard way in the first real
    comparison - the scalar-only check silently collected zero pairs)."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict) and isinstance(v.get("total"), (int, float)):
        return float(v["total"])
    return None


def judge_verdict_of(run: dict, qa_id: str) -> str | None:
    j = run.get("judge")
    if not j:
        return None
    v = j.get("verdicts", {}).get(qa_id)
    if isinstance(v, dict):
        return v.get("verdict")
    return v


def compare_pair(a: dict, b: dict, qa_ids: list[str]) -> dict:
    rows_a, rows_b = a["rows"], b["rows"]
    both_judged = bool(a.get("judge")) and bool(b.get("judge"))

    det_pairs, judge_pairs, hit1_pairs, abstain_pairs = [], [], [], []
    hit1_bases: set[str] = set()
    latency_deltas = []
    transitions: dict[str, int] = {}
    flips: dict[str, list[dict]] = {
        "answer_regressions": [], "answer_wins": [],
        "retrieval_regressions": [], "retrieval_wins": [],
    }
    slices: dict[str, dict[str, list[tuple[bool, bool]]]] = {"phrasing": {}, "answer_type": {}}

    for qid in qa_ids:
        ra, rb = rows_a[qid], rows_b[qid]
        det_a, det_b = ra.get("verdict"), rb.get("verdict")
        jv_a, jv_b = judge_verdict_of(a, qid), judge_verdict_of(b, qid)
        # authoritative verdict: judge when both runs have one, else deterministic
        va = jv_a if both_judged and jv_a else det_a
        vb = jv_b if both_judged and jv_b else det_b
        good_a, good_b = va in GOOD_VERDICTS, vb in GOOD_VERDICTS

        det_pairs.append((det_a in GOOD_VERDICTS, det_b in GOOD_VERDICTS))
        if both_judged and jv_a and jv_b:
            judge_pairs.append((jv_a in GOOD_VERDICTS, jv_b in GOOD_VERDICTS))
        # #117: prefer the end-to-end basis (what ask() actually returned)
        # over the pre-gate ranking - the two are known to diverge (17/106
        # on the topk2-vs-topk3 pair). Old runs without the field fall back
        # to pre-gate; the basis label follows whichever was used.
        e2e_a = (ra.get("retrieval_end_to_end") or {}).get("hit@1")
        e2e_b = (rb.get("retrieval_end_to_end") or {}).get("hit@1")
        if e2e_a is not None and e2e_b is not None:
            hit1_pairs.append((bool(e2e_a), bool(e2e_b)))
            hit1_bases.add("end_to_end")
        else:
            h1a = (ra.get("retrieval") or {}).get("hit@1")
            h1b = (rb.get("retrieval") or {}).get("hit@1")
            if h1a is not None and h1b is not None:
                hit1_pairs.append((bool(h1a), bool(h1b)))
                hit1_bases.add("ranked_pre_gate")
        abstain_pairs.append((bool(ra.get("abstained")), bool(rb.get("abstained"))))
        la_s, lb_s = _latency_total(ra.get("latency_s")), _latency_total(rb.get("latency_s"))
        if la_s is not None and lb_s is not None:
            latency_deltas.append(lb_s - la_s)

        if va != vb:
            transitions[f"{va} -> {vb}"] = transitions.get(f"{va} -> {vb}", 0) + 1
        entry = {
            "qa_id": qid,
            "question": ra.get("question"),
            "phrasing": ra.get("phrasing"),
            "verdict_a": va, "verdict_b": vb,
            "det_a": det_a, "det_b": det_b,
            "judge_a": jv_a, "judge_b": jv_b,
            "hit1_a": h1a, "hit1_b": h1b,
            "answer_a": (ra.get("magpie_answer") or "")[:200],
            "answer_b": (rb.get("magpie_answer") or "")[:200],
            "golden_answer": ra.get("golden_answer"),
        }
        if good_a and not good_b:
            flips["answer_regressions"].append(entry)
        elif good_b and not good_a:
            flips["answer_wins"].append(entry)
        if h1a is not None and h1b is not None:
            if h1a and not h1b:
                flips["retrieval_regressions"].append(entry)
            elif h1b and not h1a:
                flips["retrieval_wins"].append(entry)

        for dim, key in (("phrasing", ra.get("phrasing")), ("answer_type", ra.get("answer_type"))):
            if key:
                slices[dim].setdefault(key, []).append((good_a, good_b))

    lat = {}
    if latency_deltas:
        latency_deltas.sort()
        n = len(latency_deltas)
        lat = {
            "n": n,
            "mean_delta_s": round(sum(latency_deltas) / n, 2),
            "p50_delta_s": round(latency_deltas[n // 2], 2),
        }

    return {
        "answer_authoritative": paired_binary(
            judge_pairs if judge_pairs else det_pairs
        ) | {"basis": "judge" if judge_pairs else "deterministic"},
        "answer_deterministic": paired_binary(det_pairs),
        "answer_judge": paired_binary(judge_pairs) if judge_pairs else None,
        "retrieval_hit1": paired_binary(hit1_pairs) | {
            "basis": "+".join(sorted(hit1_bases)) or "none",
        },
        "abstention": paired_binary(abstain_pairs) | {"note": "outcome=abstained, not correctness"},
        "verdict_transitions": dict(sorted(transitions.items(), key=lambda kv: -kv[1])),
        "slices": {
            dim: {k: paired_binary(v) for k, v in sorted(vals.items())}
            for dim, vals in slices.items()
        },
        "latency_paired": lat,
        "flips": flips,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

AGENT_MARKER = "<!-- magpie-compare agents append below this line -->"


def _fmt_binary(name: str, s: dict) -> str:
    if not s:
        return ""
    if s.get("credible"):
        cred = ""
    elif not s.get("enough_discordant"):
        cred = "  *(not decision-grade: < 5 discordant)*"
    else:
        cred = "  *(not decision-grade: p >= 0.05 - split is coin-consistent)*"
    basis = f" ({s['basis']})" if s.get("basis") else ""
    return (
        f"| {name}{basis} | {s['a_rate']} | {s['b_rate']} | {s['delta']:+} "
        f"| {s['discordant_a_only']}A / {s['discordant_b_only']}B | {s['mcnemar_p']} |{cred}"
    )


def render_md(meta: dict, ax: dict, cmp_: dict, a: dict, b: dict) -> str:
    L: list[str] = []
    L.append(f"# Comparison: {a['name']}  vs  {b['name']}")
    L.append("")
    L.append(f"- Generated: {meta['generated_utc']}  ·  pairing mode: **{meta['pairing_mode']}** "
             f"(coverage {meta['pairing_coverage']:.0%}, n={meta['n_paired']})")
    L.append(f"- Changed axes: **{', '.join(ax['changed_axes'])}** "
             f"(knobs: {', '.join(ax['changed_knobs']) or 'none'})"
             + ("  ⚠ **CONFOUNDED (more than one knob changed - deltas are "
                "not attributable to a single cause)**" if ax["confounded"] else ""))
    if ax["params_diff"]:
        L.append("- Params diff: " + ", ".join(
            f"`{k}`: {v['a']} → {v['b']}" for k, v in ax["params_diff"].items()))
    if ax["backend_commits_between"]:
        L.append(f"- src/ commits between: {len(ax['backend_commits_between'])} "
                 f"(first: {ax['backend_commits_between'][-1] if ax['backend_commits_between'] else ''})")
    if ax["rerank_coupling_warning"]:
        L.append(f"- ⚠ {ax['rerank_coupling_warning']}")
    sg = ax["solo_gate_structurally_off"]
    if sg["a"] != sg["b"]:
        L.append(f"- ⚠ solo_gate_structurally_off differs: A={sg['a']} B={sg['b']} - "
                 "gate availability itself changed between runs")
    L.append("")
    L.append("## Paired outcomes (A = baseline)")
    L.append("")
    L.append("| Metric | A | B | Δ | discordant | McNemar p |")
    L.append("|---|---|---|---|---|---|")
    L.append(_fmt_binary("answer good (authoritative)", cmp_["answer_authoritative"]))
    L.append(_fmt_binary("answer good (deterministic)", cmp_["answer_deterministic"]))
    if cmp_["answer_judge"]:
        L.append(_fmt_binary("answer good (judge)", cmp_["answer_judge"]))
    L.append(_fmt_binary("retrieval hit@1", cmp_["retrieval_hit1"]))
    L.append(_fmt_binary("abstained", cmp_["abstention"]))
    L.append("")
    if cmp_["verdict_transitions"]:
        L.append("## Verdict transitions (A → B)")
        L.append("")
        for t, n in cmp_["verdict_transitions"].items():
            L.append(f"- {t}: {n}")
        L.append("")
    L.append("## Slices")
    L.append("")
    L.append("| Slice | A | B | Δ | discordant | McNemar p |")
    L.append("|---|---|---|---|---|---|")
    for dim, vals in cmp_["slices"].items():
        for k, s in vals.items():
            L.append(_fmt_binary(f"{dim}={k}", s))
    L.append("")
    if cmp_["latency_paired"]:
        lp = cmp_["latency_paired"]
        L.append(f"## Latency (paired): mean Δ {lp['mean_delta_s']:+}s, median Δ {lp['p50_delta_s']:+}s "
                 f"over n={lp['n']}")
        L.append("")
    for section, title in (
        ("answer_regressions", "Answer regressions (good in A → bad in B)"),
        ("answer_wins", "Answer wins (bad in A → good in B)"),
        ("retrieval_regressions", "Retrieval hit@1 regressions"),
        ("retrieval_wins", "Retrieval hit@1 wins"),
    ):
        rows = cmp_["flips"][section]
        L.append(f"## {title} — {len(rows)}")
        L.append("")
        for e in rows:
            L.append(f"- **{e['qa_id']}** ({e['phrasing']}) — {e['verdict_a']} → {e['verdict_b']}: "
                     f"{e['question']!r}")
            L.append(f"    - gold: {e['golden_answer']!r} · A: {e['answer_a']!r} · B: {e['answer_b']!r}")
        L.append("")
    L.append("## Caveats (auto-generated)")
    L.append("")
    basis = (cmp_.get("retrieval_hit1") or {}).get("basis", "none")
    if basis == "end_to_end":
        L.append("- Retrieval per-question basis is `end_to_end` - what ask() actually "
                 "returned to the answer stage.")
    else:
        L.append(f"- Retrieval per-question basis is `{basis}`; pre-gate ranking is known "
                 "to disagree with the end-to-end ask() list on some questions - treat "
                 "those deltas as pre-gate ranking deltas (old-run fallback).")
    L.append("- Discordant counts below ~5 are inside noise for this golden-set size; "
             "flagged rows say so. Do not tune on them.")
    if meta["pairing_mode"] == "intersection":
        L.append(f"- INTERSECTION mode: golden sets differ; only {meta['n_paired']} byte-identical "
                 "questions were compared. Aggregate rates are NOT comparable to full-run reports.")
    if not (a.get("judge") and b.get("judge")):
        L.append("- Judge verdicts missing in at least one run: answer rows fall back to the "
                 "deterministic verdict, which is a matcher, not a grader.")
    L.append("")
    L.append(AGENT_MARKER)
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="baseline run first, then 1+ comparison runs")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force-intersection", action="store_true")
    ap.add_argument("--allow-incomplete", action="store_true")
    args = ap.parse_args()

    if len(args.runs) < 2:
        sys.exit("compare: need a baseline and at least one comparison run")

    loaded = [load_run(resolve_run(r), args.allow_incomplete) for r in args.runs]
    base, rest = loaded[0], loaded[1:]

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) if args.out else COMPARISONS / (
        f"{ts}-{base['name'][:40]}-vs-" + "-".join(r["name"][:40] for r in rest)
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    all_json = {"baseline": base["name"], "generated_utc": ts, "pairs": []}
    md_parts = []
    for other in rest:
        qa_ids, mode, cov = pair_questions(base, other, args.force_intersection)
        ax = axes(base, other)
        cmp_ = compare_pair(base, other, qa_ids)
        meta = {
            "generated_utc": ts, "pairing_mode": mode,
            "pairing_coverage": cov, "n_paired": len(qa_ids),
        }
        all_json["pairs"].append({
            "a": base["name"], "b": other["name"], "meta": meta,
            "axes": ax, "comparison": cmp_,
        })
        md_parts.append(render_md(meta, ax, cmp_, base, other))

    (out_dir / "comparison.json").write_text(
        json.dumps(all_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "COMPARISON.md").write_text(
        "\n\n---\n\n".join(md_parts) + "\n", encoding="utf-8")

    for p in all_json["pairs"]:
        s = p["comparison"]["answer_authoritative"]
        print(f"[compare] {p['a']} vs {p['b']}: answer {s['a_rate']} -> {s['b_rate']} "
              f"(Δ {s['delta']:+}, discordant {s['discordant_a_only']}A/{s['discordant_b_only']}B, "
              f"p={s['mcnemar_p']}, basis={s['basis']}) axes={','.join(p['axes']['changed_axes'])}")
    print(f"[compare] written -> {out_dir}")


if __name__ == "__main__":
    main()
