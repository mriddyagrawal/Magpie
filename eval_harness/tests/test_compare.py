"""Tests for eval_harness/harness/compare.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "harness"
sys.path.insert(0, str(HARNESS))

import compare  # noqa: E402


def test_mcnemar_exact_known_values():
    # b=1, c=5: p = 2 * sum_{i<=1} C(6,i) * 0.5^6 = 2*(1+6)/64 = 0.21875
    assert abs(compare.mcnemar_exact(1, 5) - 0.21875) < 1e-9
    assert compare.mcnemar_exact(0, 0) == 1.0
    # symmetric
    assert compare.mcnemar_exact(3, 7) == compare.mcnemar_exact(7, 3)
    # capped at 1.0 for balanced discordants
    assert compare.mcnemar_exact(4, 4) == 1.0


def test_paired_binary_counts_and_credibility():
    pairs = [(True, True)] * 10 + [(True, False)] * 2 + [(False, True)] * 6 + [(False, False)] * 2
    s = compare.paired_binary(pairs)
    assert s["n"] == 20
    assert s["discordant_a_only"] == 2
    assert s["discordant_b_only"] == 6
    assert s["a_rate"] == 0.6 and s["b_rate"] == 0.8
    assert s["delta"] == 0.2
    # #116 semantics: 2A/6B has p~0.29 - coin-consistent, so detectable
    # volume but NOT decision-grade
    assert s["enough_discordant"] is True
    assert s["credible"] is False
    s2 = compare.paired_binary([(True, False), (False, False)])
    assert s2["enough_discordant"] is False
    assert s2["credible"] is False


def test_retrieval_prefers_end_to_end_basis(tmp_path):
    a = _mk_run(tmp_path, "eA", "g1", {"q1": "correct"})
    b = _mk_run(tmp_path, "eB", "g1", {"q1": "correct"})
    la, lb = compare.load_run(a, False), compare.load_run(b, False)
    for lr, hit in ((la, 1.0), (lb, 0.0)):
        for r in lr["rows"].values():
            r["retrieval_end_to_end"] = {"hit@1": hit}
    c = compare.compare_pair(la, lb, ["q1"])
    assert c["retrieval_hit1"]["basis"] == "end_to_end"
    assert c["retrieval_hit1"]["discordant_a_only"] == 1  # e2e says A-only
    # without the field, falls back with the honest label
    for lr in (la, lb):
        for r in lr["rows"].values():
            r.pop("retrieval_end_to_end")
    c2 = compare.compare_pair(la, lb, ["q1"])
    assert c2["retrieval_hit1"]["basis"] == "ranked_pre_gate"


def test_credible_requires_signal_not_just_volume():
    # perfectly balanced 5A/5B: p = 1.0 - the exact #116 case
    null = compare.paired_binary([(True, False)] * 5 + [(False, True)] * 5)
    assert null["mcnemar_p"] == 1.0
    assert null["enough_discordant"] is True
    assert null["credible"] is False
    # lopsided 0A/8B: p ~ 0.008 - decision-grade
    win = compare.paired_binary([(False, True)] * 8 + [(True, True)] * 4)
    assert win["credible"] is True


def _mk_run(tmp_path: Path, name: str, golden_sha: str, verdicts: dict[str, str],
            questions: dict[str, str] | None = None, params: dict | None = None,
            status: str = "complete") -> Path:
    d = tmp_path / name
    d.mkdir()
    qids = sorted(verdicts)
    (d / "run.json").write_text(json.dumps({
        "run_id": name, "status": status, "golden_sha": golden_sha,
        "backend_git_sha": "aaa111", "harness_git_sha": "bbb222",
        "params": params or {"top_k": 2}, "env_snapshot": {},
        "solo_gate_structurally_off": True,
    }))
    rows = []
    for q in qids:
        rows.append({
            "qa_id": q, "question": (questions or {}).get(q, f"question {q}"),
            "golden_answer": "42", "verdict": verdicts[q],
            "abstained": verdicts[q] in ("correct_abstain", "false_abstain"),
            "retrieval": {"hit@1": 1.0 if verdicts[q] == "correct" else 0.0},
            "magpie_answer": "42" if verdicts[q] == "correct" else "7",
            "phrasing": "typed" if q.endswith("typed") else "full",
            "answer_type": "extractive", "latency_s": 5.0,
        })
    (d / "answers_enriched.json").write_text(json.dumps(rows))
    (d / "metrics.json").write_text(json.dumps({"n_questions": len(qids)}))
    return d


def test_full_pairing_and_flips(tmp_path):
    a = _mk_run(tmp_path, "runA", "g1", {"q1-typed": "correct", "q2-full": "wrong"})
    b = _mk_run(tmp_path, "runB", "g1", {"q1-typed": "wrong", "q2-full": "correct"})
    la = compare.load_run(a, allow_incomplete=False)
    lb = compare.load_run(b, allow_incomplete=False)
    qa_ids, mode, cov = compare.pair_questions(la, lb, force_intersection=False)
    assert mode == "full" and cov == 1.0 and qa_ids == ["q1-typed", "q2-full"]
    c = compare.compare_pair(la, lb, qa_ids)
    assert c["answer_authoritative"]["basis"] == "deterministic"  # no judge files
    assert c["answer_deterministic"]["discordant_a_only"] == 1
    assert c["answer_deterministic"]["discordant_b_only"] == 1
    assert len(c["flips"]["answer_regressions"]) == 1
    assert len(c["flips"]["answer_wins"]) == 1
    assert c["flips"]["answer_regressions"][0]["qa_id"] == "q1-typed"
    assert c["verdict_transitions"] == {"correct -> wrong": 1, "wrong -> correct": 1}


def test_intersection_mode_on_golden_mismatch(tmp_path):
    # same qa_ids, different golden_sha; q2's question text differs -> only q1 pairs
    a = _mk_run(tmp_path, "runA", "g1", {"q1": "correct", "q2": "wrong"},
                questions={"q1": "same q", "q2": "old wording"})
    b = _mk_run(tmp_path, "runB", "g2", {"q1": "correct", "q2": "wrong"},
                questions={"q1": "same q", "q2": "new wording"})
    la, lb = compare.load_run(a, False), compare.load_run(b, False)
    qa_ids, mode, cov = compare.pair_questions(la, lb, force_intersection=True)
    assert mode == "intersection"
    assert qa_ids == ["q1"] and cov == 0.5


def test_incomplete_run_refused(tmp_path):
    d = _mk_run(tmp_path, "runX", "g1", {"q1": "correct"}, status="running")
    import pytest
    with pytest.raises(SystemExit):
        compare.load_run(d, allow_incomplete=False)
    assert compare.load_run(d, allow_incomplete=True)["run"]["status"] == "running"


def test_axes_confound_detection(tmp_path):
    a = _mk_run(tmp_path, "rA", "g1", {"q1": "correct"}, params={"top_k": 2, "rerank": True})
    b = _mk_run(tmp_path, "rB", "g1", {"q1": "correct"}, params={"top_k": 3, "rerank": False})
    la, lb = compare.load_run(a, False), compare.load_run(b, False)
    ax = compare.axes(la, lb)
    assert ax["changed_axes"] == ["config"]
    # #115: two config knobs = confounded, even though only one axis moved
    assert ax["confounded"] is True
    assert ax["changed_knobs"] == ["rerank", "top_k"]
    assert set(ax["params_diff"]) == {"top_k", "rerank"}
    assert ax["rerank_coupling_warning"] is not None


def test_axes_single_knob_not_confounded(tmp_path):
    a = _mk_run(tmp_path, "sA", "g1", {"q1": "correct"}, params={"top_k": 2})
    b = _mk_run(tmp_path, "sB", "g1", {"q1": "correct"}, params={"top_k": 3})
    ax = compare.axes(compare.load_run(a, False), compare.load_run(b, False))
    assert ax["confounded"] is False
    assert ax["changed_knobs"] == ["top_k"]


def test_cli_end_to_end(tmp_path):
    a = _mk_run(tmp_path, "runA", "g1", {"q1-typed": "correct", "q2-full": "wrong"})
    b = _mk_run(tmp_path, "runB", "g1", {"q1-typed": "correct", "q2-full": "correct"})
    out = tmp_path / "cmp"
    r = subprocess.run(
        [sys.executable, str(HARNESS / "compare.py"), str(a), str(b), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads((out / "comparison.json").read_text())
    assert data["pairs"][0]["comparison"]["answer_deterministic"]["discordant_b_only"] == 1
    md = (out / "COMPARISON.md").read_text()
    assert compare.AGENT_MARKER in md
    assert "Answer wins" in md


def _stamp_provenance(run_dir, fingerprint, build=10502):
    import json as _json
    p = run_dir / "run.json"
    rec = _json.loads(p.read_text(encoding="utf-8"))
    rec["provenance"] = {
        "fingerprint": fingerprint,
        "llama_server": {"build": build},
        "qdrant": {"version": "1.17.1"},
        "models": {"repo": "LiquidAI/LFM2.5-VL-3B-GGUF", "quant": "Q6_K",
                   "gguf": {"sha256": "a" * 64}, "mmproj": {"sha256": "b" * 64}},
        "col_model": {"model_id": "vidore/colqwen2.5-v0.2"},
    }
    p.write_text(_json.dumps(rec), encoding="utf-8")


def test_axes_runtime_fingerprint_is_a_knob(tmp_path):
    """Drift guard: a binary/model bump between runs is a changed knob."""
    a = _mk_run(tmp_path, "pA", "g1", {"q1": "correct"}, params={"top_k": 2})
    b = _mk_run(tmp_path, "pB", "g1", {"q1": "correct"}, params={"top_k": 2})
    _stamp_provenance(a, "fp-old", build=10502)
    _stamp_provenance(b, "fp-new", build=10600)
    ax = compare.axes(compare.load_run(a, False), compare.load_run(b, False))
    assert ax["changed_axes"] == ["runtime"]
    assert ax["changed_knobs"] == ["<runtime>"]
    assert ax["confounded"] is False          # exactly one knob moved
    assert ax["runtime"]["changed"] is True and ax["runtime"]["known"] is True
    assert ax["runtime"]["a"]["llama_server"] == "b10502"
    assert ax["runtime"]["b"]["llama_server"] == "b10600"


def test_axes_runtime_plus_config_is_confounded(tmp_path):
    a = _mk_run(tmp_path, "cA", "g1", {"q1": "correct"}, params={"top_k": 2})
    b = _mk_run(tmp_path, "cB", "g1", {"q1": "correct"}, params={"top_k": 3})
    _stamp_provenance(a, "fp-old")
    _stamp_provenance(b, "fp-new")
    ax = compare.axes(compare.load_run(a, False), compare.load_run(b, False))
    assert ax["changed_axes"] == ["config", "runtime"]
    assert ax["confounded"] is True


def test_axes_runtime_unknown_never_counts(tmp_path):
    """Runs from before the stamp (or one side missing) must not become a
    phantom knob - old comparisons keep their verdicts."""
    a = _mk_run(tmp_path, "uA", "g1", {"q1": "correct"}, params={"top_k": 2})
    b = _mk_run(tmp_path, "uB", "g1", {"q1": "correct"}, params={"top_k": 2})
    _stamp_provenance(a, "fp-old")            # only one side stamped
    ax = compare.axes(compare.load_run(a, False), compare.load_run(b, False))
    assert ax["changed_axes"] == ["none"]
    assert ax["runtime"]["known"] is False and ax["runtime"]["b"] is None


def test_context_window_ablation_is_a_single_knob(tmp_path):
    """The experiment the 16K decision says to run next: local_n_ctx differs
    as a param AND the runtime launch args differ - that is ONE knob.
    Provenance keeps launch args out of the fingerprint for exactly this."""
    import sys as _sys
    _sys.path.insert(0, str(HARNESS.parents[1]))
    from src.drift.provenance import fingerprint_of

    def prov(ctx):
        return {"llama_server": {"build": 10502, "commit": "x"}, "qdrant": {"version": "1.17.1"},
                "models": {"repo": "r", "quant": "q", "gguf": {"sha256": "a" * 64},
                           "mmproj": {"sha256": "b" * 64},
                           "launch": {"ctx_size": ctx, "ngl": 999, "extra_args": []}},
                "col_model": {"model_id": "c"}, "deps": {"uv_lock_sha256": "d" * 64},
                "platform": {"system": "Darwin", "machine": "arm64"}}
    a = _mk_run(tmp_path, "kA", "g1", {"q1": "correct"}, params={"local_n_ctx": 16384})
    b = _mk_run(tmp_path, "kB", "g1", {"q1": "correct"}, params={"local_n_ctx": 32768})
    pa, pb = prov(16384), prov(32768)
    _stamp_provenance(a, fingerprint_of(pa)); _stamp_provenance(b, fingerprint_of(pb))
    ax = compare.axes(compare.load_run(a, False), compare.load_run(b, False))
    assert ax["changed_knobs"] == ["local_n_ctx"]
    assert ax["confounded"] is False
