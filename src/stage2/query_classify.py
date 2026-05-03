"""Adaptive query router (backlog B1).

Classifies a user's question into a `QueryClass` and returns a tier-agnostic
`RetrievalConfig` that the search layer uses to vary retrieval shape per
query type. Today's primary lever is `top_k` — list/enumeration queries
need a bigger candidate set than factoid queries — but the structure here
is designed to grow:

  - per-class dense/sparse RRF weights once we measure where each shape wins
  - per-class fast-tier oversampling for visual queries
  - HyDE gating (backlog B2) only fires on the Conceptual class
  - cross-encoder reranking (B4) can be wired here

Why this exists: the in-session evidence on 2026-04-21 was that
"what topics did I learn in AI class" returned **1** Propositional Logic
file when the user's `sem6/343/` folder has 26 indexed AI-course files.
Fixed top-k=5 cannot serve enumeration queries no matter how good the
ranker is — you need to widen the window.

Pure module: no I/O, no LLM calls, no Qdrant. Cheap to import and easy
to test as a string-in / config-out transformation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class QueryClass(str, Enum):
    """How the user's question should be retrieved against.

    Subclassing str so the value round-trips cleanly through JSON / logs /
    REPL display without manual `.value` access.
    """

    # Enumeration / list / "what are all the X" / "topics in Y" — the user
    # wants breadth, not depth. Bump top_k aggressively.
    LIST_ALL = "list_all"

    # Default factoid / conceptual / vague — current behavior, top-k=5.
    GENERAL = "general"


@dataclass(frozen=True)
class RetrievalConfig:
    """Per-class retrieval shape. Drives `run_search()`'s knobs.

    Today only `top_k` differs by class, but kept as a struct so future
    levers (per-class dense/sparse weights, fanout, reranker thresholds)
    don't need to thread additional kwargs through every call site.
    """

    top_k: int
    """How many results to return after RRF fusion across tiers."""

    notes: str = ""
    """Human-readable explanation, surfaced in REPL/debug output."""


# Default per-class configs. Numbers chosen empirically:
#   - 5 was the original product default; matches what the REPL shipped.
#   - 30 covers most enumeration cases including category-spanning queries
#     ("what kind of receipts do I have") where the user expects the full
#     surface area: small purchase receipts AND flight itineraries AND
#     hotel bookings AND bank statements all need to fit. 20 was missing
#     the long tail in real-corpus testing.
_LIST_ALL_TOP_K = 30
_GENERAL_TOP_K = 5


def config_for(klass: QueryClass) -> RetrievalConfig:
    """Return the canonical retrieval shape for a given class."""
    if klass is QueryClass.LIST_ALL:
        return RetrievalConfig(
            top_k=_LIST_ALL_TOP_K,
            notes=f"list/enumeration query — widened top_k to {_LIST_ALL_TOP_K}",
        )
    return RetrievalConfig(
        top_k=_GENERAL_TOP_K,
        notes="general query — default top_k",
    )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

# Patterns that flag a question as enumeration-shaped. Compiled once at
# import time. Order doesn't matter — first match wins because we return
# immediately, but every pattern here should be a true positive in isolation.
_LIST_ALL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # Imperative list verbs at sentence start. We accept these broadly
        # — any sentence starting with "list" / "enumerate" / "show me" /
        # "give me" is enumeration intent. False-positive cost is just a
        # wider candidate window (top_k 5 → 20), which is harmless: the
        # answer LLM grounds on what's actually relevant in those 20.
        r"^\s*(list|enumerate)\b",
        r"^\s*give\s+me\b",
        r"^\s*show\s+me\b",

        # Same imperative verbs ANYWHERE in the query — catches conversational
        # phrasings like "what receipts do i have list all of the possible ones"
        # where the list verb shows up after a question stem.
        r"\b(list|show|give|tell)\s+(me\s+)?(all|every|the\s+(?:full|complete|whole))\b",
        r"\blist\s+all\s+of\s+the\b",

        # "what are all X" / "what were every Y"
        r"\bwhat\s+(are|were)\s+(all|every|the)\b",

        # "topics in/of/from/covered" — strong enumeration signal
        r"\btopics?\s+(in|of|from|covered|we)\b",

        # "what topics" / "which topics" — direct ask for a list
        r"\b(what|which)\s+topics?\b",

        # "what / which did I {learn,study,cover,take}" — implicit enumeration
        # ("what topics did I learn", "what classes did I take")
        r"\b(what|which)\s+\w+\s+(did|do)\s+i\s+(learn|study|cover|take|read|do)\b",

        # "every X" / "all my X" / "all the X"
        r"\b(every|all\s+(?:my|the))\s+\w+\b",

        # "what / which" + plural enumerable noun
        # ("what courses", "which classes", "what files",
        #  "what receipts", "which invoices", "what flights")
        r"\b(what|which)\s+(courses?|classes?|files?|documents?|chapters?|"
        r"sections?|topics?|subjects?|assignments?|lectures?|notes|"
        r"receipts?|bills?|invoices?|statements?|expenses?|transactions?|"
        r"purchases?|orders?|flights?|hotels?|trips?|bookings?|"
        r"contracts?|leases?|payments?|charges?|refunds?)\b",

        # "what / which X do I have / own / keep" — common phrasing for
        # "tell me my X." Covers receipts, files, courses, docs, etc. that
        # fall outside the noun whitelist above. Up to 4 words between
        # the question stem and the verb, so "what kind of receipts do i
        # have" and "which sort of bills do i keep" both match.
        r"\b(what|which)\s+(?:\w+\s+){1,4}do\s+i\s+(have|own|keep)\b",

        # "what kind / type / sort of X" — "what kind of receipts" is a
        # very common conversational way of asking for an enumeration of
        # categories. Standalone trigger; captures the pattern even when
        # the rest of the query doesn't include a do/have stem.
        r"\bwhat\s+(kind|kinds|type|types|sort|sorts|category|categories)\s+of\b",

        # "contents of" — TOC-style enumeration
        r"\bcontents?\s+of\b",

        # "everything about X" / "all about X"
        r"\b(everything|all)\s+(about|on|regarding)\b",

        # ----------------------------------------------------------------
        # Aggregation / universal-quantifier queries (added 2026-05-01).
        # Trigger transcript: "how much has been my total expenses
        # altogether include all of it" — the user wanted every expense
        # doc summed, not the single closest match. None of the
        # enumeration-noun patterns above caught it because the question
        # stem is "how much", not "what" / "which" / "list".
        # ----------------------------------------------------------------

        # Aggregation adverbs — "altogether", "in total", "in all",
        # "combined", "overall". The query wants every matching doc
        # rolled up, not the single best match.
        r"\b(altogether|in\s+total|in\s+all|combined|overall)\b",

        # "all of it" / "all of them" / "every one of them" / "all of
        # these" — universal quantification without a list verb.
        # Excludes "all of the" deliberately to avoid factoid noise.
        r"\b(all|every(?:\s+one)?)\s+of\s+(it|them|these|those)\b",

        # "every single X" — emphatic universal.
        r"\bevery\s+single\b",

        # "include all / every / everything" — explicit directive to be
        # exhaustive. Common as a tail clause: "...include all of it".
        r"\binclude\s+(all|every|everything)\b",

        # "total <enumerable>" — aggregation across every matching doc.
        # Restricted to enumerable nouns; even occasional false positives
        # are cheap (top_k 5→30 is harmless when the answer LLM grounds).
        r"\btotal\s+(?:my\s+)?"
        r"(expenses?|transactions?|spending|spend|receipts?|invoices?|"
        r"bills?|charges?|payments?|purchases?|costs?|deposits?|"
        r"withdrawals?|orders?|trips?|hours?|miles?)\b",

        # "total of all/my/the/every <X>" — explicit aggregation phrasing.
        r"\btotal\s+of\s+(all|my|the|every)\b",

        # "sum of" / "sum up" — explicit aggregation language.
        r"\bsum\s+(of|up)\b",

        # "each and every" — emphatic universal quantifier.
        r"\beach\s+and\s+every\b",
    )
)


def classify(question: str) -> QueryClass:
    """Classify a user question. Pure regex; no LLM / network.

    Returns `QueryClass.LIST_ALL` when at least one enumeration pattern
    matches, else `QueryClass.GENERAL`. Empty / whitespace input is
    `GENERAL` — defer the "empty question" handling to the caller.
    """
    if not question or not question.strip():
        return QueryClass.GENERAL

    for pattern in _LIST_ALL_PATTERNS:
        if pattern.search(question):
            return QueryClass.LIST_ALL

    return QueryClass.GENERAL


def classify_and_config(question: str) -> tuple[QueryClass, RetrievalConfig]:
    """Convenience: classify + look up config in one call."""
    klass = classify(question)
    return klass, config_for(klass)
