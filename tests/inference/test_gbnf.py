"""Unit tests for the JSON-Schema -> GBNF compiler.

The grammar these produce is the only thing standing between a 3B model and
free-form prose on the local answer path (`response_format` is a silent
no-op on llama-server b9049 — see src/inference/gbnf.py), so the shapes we
actually ship are pinned here.
"""

from __future__ import annotations

import json
import re

import pytest

from src.answer import Answer
from src.inference.gbnf import UnsupportedSchema, schema_to_gbnf
from src.stage2.search import SearchQuery


def test_answer_grammar_puts_the_answer_before_the_verdict():
    """Generation order is the whole point. With not_found first the model
    committed to a refusal as its opening token and then wrote a correct
    answer underneath it — measured, twice, on the sem6 set. Answer first
    means the verdict follows the evidence."""
    g = schema_to_gbnf(Answer.model_json_schema())
    root = g.splitlines()[0]
    positions = [
        root.index(f'\\"{k}\\"')
        for k in ("answer", "sources_used", "not_found", "not_found_topic")
    ]
    assert positions == sorted(positions), "answer must be generated first"
    assert "boolean" in root and "stringlist" in root


def test_search_query_schema_compiles():
    assert schema_to_gbnf(SearchQuery.model_json_schema()).startswith("root ::=")


def test_terminals_are_defined_for_every_rule_the_root_references():
    """A root that references an undefined rule is a grammar llama-server
    rejects at sampler-init — the exact failure this module exists to avoid."""
    g = schema_to_gbnf(Answer.model_json_schema())
    defined = {line.split("::=")[0].strip() for line in g.splitlines() if "::=" in line}
    root = g.splitlines()[0].split("::=", 1)[1]
    # rule references are bare identifiers outside quoted literals
    bare = re.sub(r'"(?:[^"\\]|\\.)*"', " ", root)
    for token in re.findall(r"[a-z][a-z0-9_]*", bare):
        assert token in defined, f"{token!r} referenced but never defined"


def test_array_of_non_strings_is_rejected():
    schema = {
        "type": "object",
        "properties": {"nums": {"type": "array", "items": {"type": "integer"}}},
    }
    with pytest.raises(UnsupportedSchema, match="arrays of strings"):
        schema_to_gbnf(schema)


def test_nested_object_is_rejected_rather_than_silently_wrong():
    schema = {
        "type": "object",
        "properties": {"inner": {"type": "object", "properties": {}}},
    }
    with pytest.raises(UnsupportedSchema):
        schema_to_gbnf(schema)


def test_ref_schemas_are_rejected():
    schema = {"type": "object", "$defs": {"X": {}}, "properties": {"a": {"type": "string"}}}
    with pytest.raises(UnsupportedSchema, match=r"\$ref"):
        schema_to_gbnf(schema)


def test_optional_union_field_is_rejected():
    """pydantic renders `str | None` as anyOf; a grammar that ignored that
    would force a string where None is legal."""
    schema = {
        "type": "object",
        "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
    }
    with pytest.raises(UnsupportedSchema, match="union"):
        schema_to_gbnf(schema)


def test_string_rule_permits_escapes_but_bans_raw_control_characters():
    """Answers quote file contents, so escapes must be legal. Raw control
    characters must not be: JSON forbids them inside strings, and a grammar
    that allowed one let a confused model ramble across 3,600 characters of
    fenced junk inside an open string, stranding a correct answer in front
    of unparseable output."""
    g = schema_to_gbnf(Answer.model_json_schema())
    assert r'char ::= [^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" hex hex hex hex)' in g


def test_local_agent_carries_a_grammar_for_the_answer_schema(monkeypatch):
    """End of the wiring: the agent the answer step builds must actually
    hold a compiled grammar, or none of the above matters at runtime."""
    monkeypatch.setenv("MAGPIE_FORCE_PROVIDER", "local")
    monkeypatch.delenv("LOCAL_GRAMMAR", raising=False)
    from src.answer import build_answer_agent

    agent = build_answer_agent(cite_inline=True)
    assert getattr(agent, "_grammar", None), "local answer agent lost its grammar"
    assert json.dumps(agent._response_format)  # still present as the fallback path
