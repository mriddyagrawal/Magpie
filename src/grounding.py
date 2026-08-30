"""Deterministic groundedness checks on an answer against its own context.

No model, no second call. The one question a computer can answer with
certainty about a generated answer is whether the numbers in it appear in
what the model was shown, and that maps directly onto the failure class our
evals keep recording: right file, wrong figure — or no file at all.

Two users:

  - `src/answer.py` calls `looks_fabricated` as a last guard before an
    answer reaches the user.
  - `Evaluations/grounding_audit.py` uses the same primitives to score
    whole eval runs, so the shipped guard and the measured metric can never
    drift apart.
"""

from __future__ import annotations

import itertools
import re

# Citation markers ([1], [2]) are ours, not claims about the world.
_CITATION = re.compile(r"\[\d{1,2}\]")

# A numeral: digits, optional thousands separators, optional decimals.
# Currency symbols are left outside the token so '$51.32' == '51.32'.
_NUMERAL = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Below this, bare integers are list indices, small counts and years-in-prose.
# They collide with everything and auditing them is noise, not signal. A
# numeral WITH a decimal part is a different thing: 9.00, 60.30, 0.42 are
# money, and most receipt totals are under 100 — the old rule never looked
# at them, so an invented "$8.20" for a shop that is not even in the corpus
# walked straight through (SROIE absence probes, 2026-08-29).
MIN_INTERESTING = 100


def normalize(text: str) -> str:
    """Drop thousands separators so '11,378.50' in an answer matches
    '11378.50' in a PDF's text layer."""
    return re.sub(r"(?<=\d),(?=\d)", "", text)


def numerals(text: str) -> list[str]:
    out: list[str] = []
    for m in _NUMERAL.finditer(normalize(_CITATION.sub(" ", text))):
        tok = m.group(0).rstrip(".")
        try:
            if abs(float(tok)) < MIN_INTERESTING and "." not in tok:
                continue
        except ValueError:
            continue
        out.append(tok)
    return out


def is_sum_of(target: str, present: list[str]) -> bool:
    """True when `target` is the sum of two to five numbers that ARE in the
    context — a total the model computed, not one it invented. Five, not
    four: an Uber receipt is fare + booking fee + airport surcharge + state
    surcharge + wait time, and its total only passed the old four-addend
    rule because 51.32 was under the threshold and never checked."""
    try:
        goal = round(float(target), 2)
    except ValueError:
        return False
    vals: list[float] = []
    for p in present:
        try:
            vals.append(round(float(p), 2))
        except ValueError:
            continue
    vals = sorted(set(vals))[:30]  # combinatorics guard: 30 choose 5 is 142k sums
    for n in (2, 3, 4, 5):
        for combo in itertools.combinations(vals, n):
            if abs(sum(combo) - goal) < 0.005:
                return True
    return False


def unsupported_numerals(answer: str, context: str) -> list[str]:
    """Numbers in `answer` that appear nowhere in `context` and are not the
    sum of numbers that do.

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
    """True when EVERY number in the answer is unsupported, and there is at
    least one.

    Deliberately conservative. An answer with one wrong figure among several
    right ones is a misreading — the user still gets value, and the citations
    let them check. An answer whose every number is absent from every file
    the model read is a different animal: on the sem6 absence probe ('how
    much did I pay for my dorm room') the model returned '$159.00', a figure
    that exists in no retrieved file. That is the shape this catches, and
    the honest response to it is the not-found contract.
    """
    found = numerals(answer)
    if not found:
        return False
    # No "but the rest of the answer is fine" exemption. A residue test was
    # tried and dropped: it saved an address whose street number and postcode
    # were both invented, and in exchange it let every verbose fabrication
    # through ("The monthly gross salary is 2,500.00 euros" reads as five
    # honest words plus a lie). If every figure in an answer is absent from
    # the source, the answer does not go out.
    return len(unsupported_numerals(answer, context)) == len(found)
