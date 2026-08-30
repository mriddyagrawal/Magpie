"""Extractive fast path for factoid questions.

A small span-extraction model (SQuAD2-tuned RoBERTa, ~80M parameters) reads
the retrieved files and copies out the exact phrase that answers a "how many
/ when / who / what is the X" question. It cannot write anything that is not
in the file, and it answers in a few hundred milliseconds on CPU where the
3B reader takes seconds. Off by default; MAGPIE_EXTRACTIVE=1 turns it on.
The numbers that decide that live in Evaluations/phyll/REPORT.md.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

MODEL = os.environ.get("MAGPIE_EXTRACTIVE_MODEL", "deepset/tinyroberta-squad2")
MIN_SCORE = float(os.environ.get("MAGPIE_EXTRACTIVE_MIN_SCORE", "0.5"))
ENABLED = os.environ.get("MAGPIE_EXTRACTIVE", "0").strip() == "1"

# the reader sees ~380 tokens at once, so long files are cut into overlapping
# windows and only the windows that share words with the question are read
WINDOW_CHARS = 1500
WINDOW_STEP = 1200
MAX_WINDOWS = 6
MAX_ANSWER_CHARS = 120
MAX_ANSWER_TOKENS = 40

# questions whose answer is a short phrase sitting in the text. "what is X
# about" or "explain Y" are deliberately not here — those need the reader.
FACTOID_RE = re.compile(
    r"^\s*(on what date|on which date|at what time|what date|which date"
    r"|which (shop|store|company|vendor|merchant|supplier|bank|airline|hotel|restaurant)"
    r"|what is the (\w+ ){0,2}(address|phone|email|invoice number|order number|"
    r"receipt number|reference|confirmation number|booking reference|account number)"
    r"|how (many|much|long|far|often|fast|old|big|large|wide|tall|heavy|thick)"
    r"|when|who|whom|where"
    r"|what (year|date|day|time|number|value|percentage|percent|frequency|size|"
    r"voltage|current|rate|amount|price|cost|temperature|version|address)"
    r"|which (year|date|version|port|pin|model|device)"
    r"|what (is|was|are|were) the (\w+[ -]){0,3}(rate|frequency|bandwidth|count|"
    r"number|total|value|size|length|width|height|duration|date|time|price|cost|"
    r"amount|voltage|current|resolution|version|threshold|limit|range|speed|"
    r"temperature|weight|mass|distance|ratio|percentage|score|accuracy))\b",
    re.IGNORECASE,
)

_STOPWORDS = set(
    "the a an of in on at to for is are was were what which how many much does "
    "do did and or with by from as it its this that be been has have had".split()
)


def is_factoid(question: str) -> bool:
    return bool(FACTOID_RE.search(question))


@lru_cache(maxsize=1)
def _reader():
    # transformers + torch are ~1 GB of imports, so this waits for first use
    from transformers import AutoModelForQuestionAnswering, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForQuestionAnswering.from_pretrained(MODEL)
    model.eval()
    return tok, model


def _read(question: str, context: str) -> tuple[float, str]:
    # one forward pass; returns (confidence, span). confidence is the span's
    # margin over the model's own "no answer" option squashed to 0..1, so
    # 0.5 means "as likely as not answerable" and MIN_SCORE sits above it.
    import math

    import torch

    tok, model = _reader()
    enc = tok(question, context, return_tensors="pt", truncation="only_second",
              max_length=512, return_offsets_mapping=True)
    offsets = enc.pop("offset_mapping")[0].tolist()
    seq_ids = enc.sequence_ids(0)
    with torch.no_grad():
        out = model(**enc)
    start = out.start_logits[0].tolist()
    end = out.end_logits[0].tolist()

    context_positions = [i for i, s in enumerate(seq_ids) if s == 1]
    best_score, best = None, None
    for i in context_positions:
        for j in range(i, min(i + MAX_ANSWER_TOKENS, len(seq_ids))):
            if seq_ids[j] != 1:
                break
            score = start[i] + end[j]
            if best_score is None or score > best_score:
                best_score, best = score, (i, j)
    if best is None:
        return 0.0, ""
    no_answer = start[0] + end[0]
    i, j = best
    span = context[offsets[i][0] : offsets[j][1]]
    return 1 / (1 + math.exp(-(best_score - no_answer))), span


def _keywords(question: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", question.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _windows(text: str) -> list[str]:
    out = []
    start = 0
    while True:
        out.append(text[start : start + WINDOW_CHARS])
        if start + WINDOW_CHARS >= len(text):
            return out
        start += WINDOW_STEP


def extract(question: str, files: list[tuple[str, str]]) -> tuple[float, str, str] | None:
    # files is [(display path, raw text)]; returns (score, span, display) or None
    keywords = _keywords(question)
    candidates = []
    for display, text in files:
        for window in _windows(text):
            low = window.lower()
            hits = sum(1 for k in keywords if k in low)
            if hits:
                candidates.append((hits, display, window))
    candidates.sort(key=lambda c: -c[0])
    if not candidates:
        return None

    best = None
    for _hits, display, window in candidates[:MAX_WINDOWS]:
        score, span = _read(question, window)
        span = span.strip().strip(".,;:")
        if not span or len(span) > MAX_ANSWER_CHARS:
            continue
        if best is None or score > best[0]:
            best = (score, span, display)
    if best is None or best[0] < MIN_SCORE:
        return None
    return best
