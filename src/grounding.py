"""Deterministic groundedness checks on an answer against its own context.

No model, no second call. Everything here is a string comparison between what
the model wrote and what the model was shown, and it maps onto the failure
class our evals keep recording: right file, wrong figure — or no file at all.

Three modes, chosen by MAGPIE_GROUNDING:

  numerals   The original check. Every numeral in the answer at or above
             MAGPIE_GROUNDING_MIN_NUMERAL must appear in the context, or be
             the sum of numerals that do; the answer is refused only when
             EVERY such numeral is unsupported. The magnitude floor exists
             because small integers are in every document and would rescue
             an invented figure next to them — which also means a bare
             integer below the floor is never checked ('Jan 5', '8'). A
             numeral WITH a decimal part is audited at any size
             (MAGPIE_GROUNDING_DECIMALS): receipt totals are mostly under
             100, and '20.00' is a claim, not a list index.
  evidence   The model quotes the span(s) it read (`Answer.evidence`). Each
             span must be found in the context; every numeral in the answer
             must sit inside a supported span, or be derivable from numerals
             that do. Nothing is compared "anywhere in the context", so no
             small number can launder a large one and there is no floor.
  off        No check.

MAGPIE_GROUNDING_ACTION decides what a failed check does: `refuse` (the
not-found contract) or `warn` (log it, let the answer through — the setting
for measuring a mode before it ships). Every threshold is an env knob with
its default in `_KNOBS`; there are no other numbers in this file.

Two users:

  - `src/answer.py` calls `check` as a last guard before an answer reaches
    the user.
  - `Evaluations/grounding_audit.py` uses the same primitives to score whole
    eval runs, so the shipped guard and the measured metric never drift.
"""

from __future__ import annotations

import itertools
import os
import re
from dataclasses import dataclass, field

# Every tunable, in one place. Read at call time so an eval arm (or a test)
# can flip one with the environment and nothing else.
_KNOBS: dict[str, str] = {
    "MAGPIE_GROUNDING": "numerals",          # numerals | evidence | off
    "MAGPIE_GROUNDING_ACTION": "refuse",     # refuse | warn
    "MAGPIE_GROUNDING_MIN_NUMERAL": "100",   # numerals mode: floor below which numerals are ignored
    "MAGPIE_GROUNDING_DECIMALS": "1",        # numerals mode: a numeral with a decimal part is audited whatever its size
    "MAGPIE_GROUNDING_SUM_TERMS": "5",       # max terms in the "it is a sum of context numbers" test (an Uber receipt is fare + four fees)
    "MAGPIE_EVIDENCE_MIN_NUMERAL": "0",      # evidence mode: floor (0 = every number counts)
    "MAGPIE_EVIDENCE_MIN_OVERLAP": "0.8",    # evidence mode: token share of a span that must be in the context
    "MAGPIE_EVIDENCE_REQUIRED": "1",         # evidence mode: an answer with no supported span fails
    "MAGPIE_EVIDENCE_NUMERALS": "1",         # evidence mode: answer numerals must be inside the spans
    "MAGPIE_EVIDENCE_ARITHMETIC": "1",       # evidence mode: allow +, -, x, / and counts over span numerals
    "MAGPIE_EVIDENCE_MAX_VALUES": "40",      # combinatorics guard for the arithmetic test
}


def knob(name: str) -> str:
    return os.environ.get(name, _KNOBS[name]).strip() or _KNOBS[name]


def mode() -> str:
    m = knob("MAGPIE_GROUNDING").lower()
    return m if m in ("numerals", "evidence", "off") else "numerals"


def action() -> str:
    a = knob("MAGPIE_GROUNDING_ACTION").lower()
    return a if a in ("refuse", "warn") else "refuse"


def _float_knob(name: str) -> float:
    try:
        return float(knob(name))
    except ValueError:
        return float(_KNOBS[name])


def _int_knob(name: str) -> int:
    try:
        return int(knob(name))
    except ValueError:
        return int(_KNOBS[name])


def _on(name: str) -> bool:
    return knob(name) != "0"


# Kept as a name for callers that import it; the live value is the knob.
MIN_INTERESTING = int(_KNOBS["MAGPIE_GROUNDING_MIN_NUMERAL"])

# Citation markers ([1], [2]) are ours, not claims about the world.
_CITATION = re.compile(r"\[\d{1,2}\]")

# A numeral: digits, optional thousands separators, optional decimals.
# Currency symbols are left outside the token so '$51.32' == '51.32'.
_NUMERAL = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalize(text: str) -> str:
    """Drop thousands separators so '11,378.50' in an answer matches
    '11378.50' in a PDF's text layer."""
    return re.sub(r"(?<=\d),(?=\d)", "", text)


def numerals(text: str, minimum: float | None = None) -> list[str]:
    """Numerals in `text` at or above `minimum` (default: the numerals-mode
    floor). Below the floor, bare integers are list indices, small counts
    and years-in-prose: they collide with everything. A numeral with a
    decimal part ('20.00', '3.86') is kept at any size when
    MAGPIE_GROUNDING_DECIMALS is on — it reads as a stated figure, and most
    receipt totals live below the floor."""
    floor = _float_knob("MAGPIE_GROUNDING_MIN_NUMERAL") if minimum is None else minimum
    decimals = _on("MAGPIE_GROUNDING_DECIMALS")
    out: list[str] = []
    for m in _NUMERAL.finditer(normalize(_CITATION.sub(" ", text))):
        tok = m.group(0).rstrip(".")
        try:
            if abs(float(tok)) < floor and not (decimals and "." in tok):
                continue
        except ValueError:
            continue
        out.append(tok)
    return out


def _values(tokens: list[str]) -> list[float]:
    vals: list[float] = []
    for p in tokens:
        try:
            vals.append(round(float(p), 2))
        except ValueError:
            continue
    return sorted(set(vals))[: _int_knob("MAGPIE_EVIDENCE_MAX_VALUES")]


def is_sum_of(target: str, present: list[str], max_terms: int | None = None) -> bool:
    """True when `target` is the sum of two to `max_terms` numbers that ARE
    in the context — a total the model computed, not one it invented."""
    try:
        goal = round(float(target), 2)
    except ValueError:
        return False
    vals = _values(present)
    top = _int_knob("MAGPIE_GROUNDING_SUM_TERMS") if max_terms is None else max_terms
    for n in range(2, max(2, top) + 1):
        for combo in itertools.combinations(vals, n):
            if abs(sum(combo) - goal) < 0.005:
                return True
    return False


def derivable(target: str, present: list[str], count: int = 0) -> bool:
    """Evidence mode's arithmetic test. `target` is fine when it is a sum of
    2..N present numbers, or (MAGPIE_EVIDENCE_ARITHMETIC) the difference,
    product or quotient of two of them, or the number of spans quoted — a
    count the model made rather than a figure it read."""
    if is_sum_of(target, present):
        return True
    if not _on("MAGPIE_EVIDENCE_ARITHMETIC"):
        return False
    try:
        goal = round(float(target), 2)
    except ValueError:
        return False
    if count and goal == count:
        return True
    vals = _values(present)
    for a, b in itertools.permutations(vals, 2):
        if abs((a - b) - goal) < 0.005 or abs((a * b) - goal) < 0.005:
            return True
        if b and abs((a / b) - goal) < 0.005:
            return True
    return False


def unsupported_numerals(answer: str, context: str) -> list[str]:
    """Numerals-mode primitive: numbers in `answer` that appear nowhere in
    `context` and are not the sum of numbers that do.

    The de-spaced comparison is not optional: flyers and poster exports put
    a space between every glyph, so '2026' extracts as '2 0 2 6' and a
    literal search reports a fabrication that is sitting right there.
    """
    ctx = normalize(context)
    despaced = re.sub(r"\s+", "", ctx)
    ctx_numbers = numerals(ctx)

    out: list[str] = []
    for tok in numerals(answer):
        if tok in ctx or tok in despaced:
            continue
        if is_sum_of(tok, ctx_numbers):
            continue
        out.append(tok)
    return out


# Blocks carrying this marker are index-time LLM summaries, not extracted
# text. See `strip_generated_blocks`.
_SUMMARY_MARKER = "Content type: llm-summary"


def strip_generated_blocks(blocks: list[str]) -> list[str]:
    """Drop index-time LLM summaries from the text an answer is checked against.

    A summary is the model's own earlier output, not evidence. Treating it as
    evidence lets a fabrication launder itself: the invitation letter in the
    sem6 corpus has its digits destroyed by a font encoding, its summary
    nonetheless states a salary of '2,500.00' and a postcode of '44801', and
    the answer step then repeats those figures with the summary as their
    apparent support. Numbers that exist only in a summary are exactly the
    numbers that need checking, so the checker cannot count them.
    """
    return [b for b in blocks if _SUMMARY_MARKER not in b]


def looks_fabricated(answer: str, context: str) -> bool:
    """Numerals mode: True when EVERY number in the answer is unsupported,
    and there is at least one.

    Deliberately conservative. An answer with one wrong figure among several
    right ones is a misreading — the user still gets value, and the citations
    let them check. An answer whose every number is absent from every file
    the model read is a different animal: on the sem6 absence probe ('how
    much did I pay for my dorm room') the model returned '$159.00', a figure
    that exists in no retrieved file. That is the shape this catches.
    """
    found = numerals(answer)
    if not found:
        return False
    return len(unsupported_numerals(answer, context)) == len(found)


# ---------------------------------------------------------------------------
# Evidence mode
# ---------------------------------------------------------------------------

_NOT_WORD = re.compile(r"[^0-9a-z.]+")


def _norm(text: str) -> str:
    """Comparison form: thousands separators gone, lower-case, punctuation
    to spaces (a '.' survives only between digits), whitespace collapsed."""
    t = normalize(text).lower()
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    t = _NOT_WORD.sub(" ", t)
    return " ".join(t.split())


def span_supported(span: str, context: str, min_overlap: float | None = None) -> bool:
    """Is `span` a quote from `context`?

    Exact after normalisation, or exact with all spaces removed (letter-spaced
    PDF text), or — a small model copies imperfectly — a token match: every
    numeral in the span is in the context and at least `min_overlap` of the
    span's tokens are. The numeral rule is strict on purpose: a quote that
    gets the words right and a digit wrong is the failure we are here for.
    """
    ns, nc = _norm(span), _norm(context)
    if not ns or not nc:
        return False
    if ns in nc:
        return True
    despaced_ctx = nc.replace(" ", "")
    if ns.replace(" ", "") in despaced_ctx:
        return True
    toks = ns.split()
    ctx_toks = set(nc.split())
    for tok in toks:
        if tok[0].isdigit() and tok not in ctx_toks and tok not in despaced_ctx:
            return False
    share = _float_knob("MAGPIE_EVIDENCE_MIN_OVERLAP") if min_overlap is None else min_overlap
    hit = sum(1 for tok in toks if tok in ctx_toks)
    return hit / len(toks) >= share


def unsupported_spans(spans: list[str], context: str) -> list[str]:
    return [s for s in spans if not span_supported(s, context)]


def unsupported_answer_numerals(answer: str, spans: list[str], question: str = "") -> list[str]:
    """Numerals in `answer` that are inside none of the (supported) `spans`
    and cannot be derived from the numerals that are. Numbers the user typed
    in the question are echoes, not claims, and are skipped."""
    floor = _float_knob("MAGPIE_EVIDENCE_MIN_NUMERAL")
    joined = _norm(" ".join(spans))
    despaced = joined.replace(" ", "")
    span_numbers = numerals(" ".join(spans), minimum=floor)
    asked = set(numerals(question, minimum=floor))
    out: list[str] = []
    for tok in numerals(answer, minimum=floor):
        if tok in asked or tok in joined.split() or tok in despaced:
            continue
        if derivable(tok, span_numbers, count=len(spans)):
            continue
        out.append(tok)
    return out


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    mode: str = ""
    detail: dict = field(default_factory=dict)


def check(
    answer: str,
    context: str,
    *,
    evidence: list[str] | None = None,
    question: str = "",
) -> Verdict:
    """Run the configured check. `evidence=None` means the caller could not
    ask for quotes (a provider that composes its own prompt), so evidence
    mode falls back to the numerals check rather than refusing everything."""
    m = mode()
    if m == "off" or not answer.strip():
        return Verdict(True, "", m)
    if m == "evidence" and evidence is not None:
        supported = [s for s in evidence if s.strip() and span_supported(s, context)]
        bad_spans = [s for s in evidence if s.strip() and s not in supported]
        if not supported:
            if evidence and bad_spans:
                return Verdict(False, "no quoted span is in the files read", m,
                               {"spans": bad_spans})
            if _on("MAGPIE_EVIDENCE_REQUIRED"):
                return Verdict(False, "no evidence quoted", m)
            return _numerals_verdict(answer, context)
        if _on("MAGPIE_EVIDENCE_NUMERALS"):
            missing = unsupported_answer_numerals(answer, supported, question)
            if missing:
                return Verdict(False, f"figures not in the quoted spans: {missing}", m,
                               {"numerals": missing, "spans": bad_spans})
        return Verdict(True, "", m, {"spans": bad_spans})
    return _numerals_verdict(answer, context)


def _numerals_verdict(answer: str, context: str) -> Verdict:
    if looks_fabricated(answer, context):
        return Verdict(False, "every figure in the answer is absent from the files read",
                       "numerals", {"numerals": unsupported_numerals(answer, context)})
    return Verdict(True, "", "numerals")
