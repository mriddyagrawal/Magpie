"""Request/response schemas for the LLM endpoints.

These mirror the desktop's structured-output classes (`SearchQuery`,
`Answer`, `FileSummary`) so the two sides agree on the shape of every
LLM call. Until Phase 2.5 step 5 lands, the desktop has its own copy of
these models in `src/stage2/search.py`, `src/answer.py`,
`src/stage1/summarize.py`. After step 5 the desktop imports its types
from here (or generates a TypeScript client), eliminating duplication.

Field descriptions are part of the IP — they're what the LLM reads to
understand each output slot. Edit carefully; they shape behavior.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ContentType = Literal["image", "pdf", "docx", "xlsx", "text", "code", "markdown", "other"]


# ---------------------------------------------------------------------------
# /llm/rewrite
# ---------------------------------------------------------------------------

class SearchQuery(BaseModel):
    """Output of the rewrite step. Drives both dense and sparse retrieval."""
    query: str = Field(
        description=(
            "A keyword-rich rewrite of the user's question that captures the full "
            "intent. The dense embedder sees this whole string."
        )
    )
    keywords: list[str] = Field(
        description=(
            "5-12 terms covering verbatim values from the question (names, dates, "
            "amounts) AND likely synonyms / paraphrases the documents may use."
        )
    )


class RewriteRequest(BaseModel):
    question: str = Field(min_length=1)
    history: list[tuple[str, str]] = Field(
        default_factory=list,
        description=(
            "Optional prior (question, answer) turns to resolve pronouns and "
            "implicit references in the current question."
        ),
    )


class RewriteResponse(BaseModel):
    query: str
    keywords: list[str]
    prompt_version: int


# ---------------------------------------------------------------------------
# /llm/answer
# ---------------------------------------------------------------------------

class Answer(BaseModel):
    """Output of the answer step."""
    answer: str = Field(
        description="The grounded answer. Concise unless the question asks for a list."
    )
    sources_used: list[str] = Field(
        description=(
            "File paths the answer actually depends on, copied verbatim from the "
            "'--- File N: <path> ---' headers."
        )
    )


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1)
    # The desktop has already retrieved + read the relevant files. It sends the
    # extracted text snippets here so the cloud doesn't need to know anything
    # about the user's filesystem. Path is the citation key the LLM will copy
    # into `sources_used`.
    snippets: list["AnswerSnippet"] = Field(
        description="Pre-extracted text from the files the desktop retrieved."
    )
    history: list[tuple[str, str]] = Field(default_factory=list)


class AnswerSnippet(BaseModel):
    path: str = Field(description="Cite this verbatim if used in the answer.")
    text: str = Field(description="Extracted body text. Already capped client-side.")


class AnswerResponse(BaseModel):
    answer: str
    sources_used: list[str]
    prompt_version: int


# ---------------------------------------------------------------------------
# /llm/summarize  (T3 cloud summarization)
# ---------------------------------------------------------------------------

class FileSummary(BaseModel):
    """Output of T3 summarization: the structured summary that gets embedded."""
    title: str = Field(description="Short human-readable title for the file (<=80 chars).")
    summary: str = Field(
        description=(
            "Comprehensive 3-7 sentence summary covering what the file is and the headline "
            "facts (merchant/author, dates, totals, key items). Write natural prose but include "
            "discriminator tokens verbatim — names, dates, totals — so retrieval can match them."
        )
    )
    content_type: ContentType
    keywords: list[str]
    key_entities: list[str]
    identifiers: list[str]


class SummarizeRequest(BaseModel):
    filename: str = Field(min_length=1)
    text: str = Field(
        min_length=1,
        description=(
            "Pre-extracted text from the file. Cloud summarization is text-only "
            "for beta; vision-required files (scanned PDFs) stay on the desktop's "
            "local fallback."
        ),
    )


class SummarizeResponse(BaseModel):
    summary: FileSummary
    prompt_version: int


# Forward-ref resolution for AnswerRequest -> AnswerSnippet
AnswerRequest.model_rebuild()
