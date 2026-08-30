"""Compile a flat Pydantic JSON Schema into a GBNF grammar.

Why this exists: `LocalAgent` sent the response schema to llama-server as
`response_format={"type": "json_schema", ...}` and assumed the server
compiled it to a grammar. On llama-server b9049 that assumption is false in
the worst possible way — the parameter is accepted and **silently ignored**
(HTTP 200, unconstrained prose back), while passing the same schema as the
`json_schema` request field fails outright with
`Failed to initialize samplers`, even for `{"answer": {"type": "string"}}`.
The `grammar` field, meanwhile, works on both `/completion` and
`/v1/chat/completions`.

So the answer step was running with no structural constraint at all. When
the 3B improvised a different shape (`{"grade": "A 4.000 4 16.000"}` is a
real observed output), `parse_json_with_repair` could not rescue it and the
user got an empty answer for a question the model had actually read
correctly. Compiling the grammar here and sending it as `grammar` puts the
constraint back where the code always claimed it was.

Scope is deliberately small: flat objects whose properties are strings,
booleans, integers, numbers, or arrays of strings — which is every
structured output Magpie asks a local model for (`Answer`, `SearchQuery`,
`FileSummary`). Anything else raises `UnsupportedSchema`, and the caller
falls back to prompt-plus-repair rather than shipping a wrong grammar.
"""

from __future__ import annotations

from typing import Any


class UnsupportedSchema(Exception):
    """The schema uses a construct this compiler does not model."""


# Shared terminals. `string` follows the JSON spec's escape rules so the
# model can emit quotes and newlines inside an answer without breaking out
# of the grammar. `ws` is permissive: llama.cpp's own converter allows
# whitespace between tokens and the model reads more naturally with it.
#
# `ws` is a single optional space, not `[ \t\n]*`. Unbounded whitespace is
# a legal infinite loop: on one question the model emitted 2,048 tokens of
# tabs straight after the opening brace and hit the generation cap without
# ever writing a field. Whitespace between JSON tokens is cosmetic; the
# grammar should not offer a degenerate path through it. A repetition
# penalty does not save you here — whitespace tokens are not what it
# penalises in practice.
#
# Control characters are excluded from `char` on purpose, and it is
# load-bearing rather than pedantic. JSON forbids a raw newline inside a
# string; a grammar that allows one lets a model that has lost the thread
# ramble across lines inside an open string and produce output that no
# repair can parse. Observed exactly once and then never again after this
# line: 3,600 characters of '```json\n```answer' inside `sources_used[0]`,
# with a correct answer stranded in front of it.
_PRELUDE = r'''
string ::= "\"" char* "\""
char ::= [^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" hex hex hex hex)
hex ::= [0-9a-fA-F]
boolean ::= "true" | "false"
integer ::= "-"? ("0" | [1-9] [0-9]*)
number ::= integer ("." [0-9]+)? ([eE] [-+]? [0-9]+)?
stringlist ::= "[" ws (string (ws "," ws string)*)? ws "]"
numstring ::= "\"" [0-9]+ ("  [" [^"\\]* "]")? "\""
numstringlist ::= "[" ws (numstring (ws "," ws numstring)*)? ws "]"
ws ::= [ \t]?
'''.strip()


def _rule_for(name: str, prop: dict[str, Any]) -> str:
    """Map one JSON-Schema property to the terminal that matches it."""
    kind = prop.get("type")
    if kind == "string":
        return "string"
    if kind == "boolean":
        return "boolean"
    if kind == "integer":
        return "integer"
    if kind == "number":
        return "number"
    if kind == "array":
        items = prop.get("items") or {}
        # A field that must hold file numbers ("2", optionally "2  [book pp.
        # 4-5]"). Asked for a number but offered a free string, the model
        # opens the quote and writes JSON inside it (measured 2026-08-29:
        # 4 of 25 answers derailed into '":[1,2]]}```json```"' and took
        # 10-24 s); digits-only after the quote leaves it nowhere to go.
        if prop.get("x-gbnf") == "numstringlist" and items.get("type") == "string":
            return "numstringlist"
        if items.get("type") != "string":
            raise UnsupportedSchema(
                f"property {name!r}: only arrays of strings are supported, "
                f"got items={items!r}"
            )
        return "stringlist"
    raise UnsupportedSchema(f"property {name!r}: unsupported type {kind!r}")


def schema_to_gbnf(schema: dict[str, Any]) -> str:
    """Compile a flat object schema to GBNF.

    Key order is fixed to the schema's property order — a grammar that
    allowed any permutation would need a rule per ordering, and pinning the
    order is what the cloud prompt already asks for anyway, so the two
    providers emit the same shape.
    """
    if schema.get("type") != "object":
        raise UnsupportedSchema(f"top level must be an object, got {schema.get('type')!r}")
    if "$defs" in schema or "$ref" in schema:
        raise UnsupportedSchema("$ref/$defs schemas are not supported")

    props: dict[str, Any] = schema.get("properties") or {}
    if not props:
        raise UnsupportedSchema("object has no properties")

    parts: list[str] = []
    for name, prop in props.items():
        if "anyOf" in prop or "oneOf" in prop or "allOf" in prop:
            raise UnsupportedSchema(f"property {name!r}: union types are not supported")
        # The key is a literal, so a mis-spelled or invented field name is
        # unreachable rather than merely discouraged.
        key = name.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'"\\"{key}\\"" ws ":" ws {_rule_for(name, prop)}')

    body = ' ws "," ws '.join(parts)
    return f'root ::= "{{" ws {body} ws "}}"\n{_PRELUDE}\n'
