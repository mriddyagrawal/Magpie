"""`sources_used` entries are file numbers now (one token to decode instead
of a 20-40 token path); resolve_sources maps them back to the display paths
in message order, keeps a page-range suffix, still accepts verbatim paths,
and drops inventions."""

from __future__ import annotations

from src.answer import resolve_sources

PATHS = ["/docs/low-rank.pdf", "/docs/top hit.md", "/docs/101  mus/notes.txt"]


def test_numbers_map_to_message_order():
    assert resolve_sources(["2", "1"], PATHS) == ["/docs/top hit.md", "/docs/low-rank.pdf"]


def test_page_suffix_rides_along():
    assert resolve_sources(["1  [book pp. 4-5 / PDF pp. 9-10]"], PATHS) == [
        "/docs/low-rank.pdf  [book pp. 4-5 / PDF pp. 9-10]"
    ]


def test_paths_still_accepted_and_inventions_dropped():
    out = resolve_sources(["/docs/top hit.md", "/docs/101 mus/notes.txt", "/nope.pdf", "9", "0"], PATHS)
    assert out == ["/docs/top hit.md", "/docs/101  mus/notes.txt"]


def test_duplicate_citations_collapse():
    assert resolve_sources(["2", "/docs/top hit.md"], PATHS) == ["/docs/top hit.md"]


def test_local_grammar_forces_digit_strings_for_sources():
    from src.answer import Answer
    from src.inference.gbnf import schema_to_gbnf

    schema = Answer.model_json_schema()
    g = schema_to_gbnf(schema)
    assert '"\\"sources_used\\"" ws ":" ws numstringlist' in g
    assert 'numstring ::= "\\"" [0-9]+' in g
    # the other list-free fields keep their plain rules
    assert '"\\"answer\\"" ws ":" ws string' in g
