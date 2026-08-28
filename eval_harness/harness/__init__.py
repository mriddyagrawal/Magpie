"""Magpie evaluation harness (PLAN.md).

Deterministic runner: no LLM anywhere in the execution path. Judgment
(golden-set generation, grading) happens in separate offline passes over the
artifacts this package produces.
"""
