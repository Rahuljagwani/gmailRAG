"""Orchestration: question -> retrieve -> generate -> structured AnswerResult.

This is the single entry point the API (Commit 6) and the CLI/eval call. Retrieval
strategy and generation are kept behind retrieve()/generate() so this layer stays
stable as we climb the retrieval ladder. It also attaches a lightweight retrieval
trace so the eval (Commit 5) can inspect what was fed to the model.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field  # noqa: E402

from rag.generate import generate  # noqa: E402
from rag.retrieve import Hit, retrieve  # noqa: E402


class Citation(BaseModel):
    doc: str
    section: str = ""
    page: int = 0
    quote: str = ""


class RetrievedChunk(BaseModel):
    id: str
    score: float
    doc: str
    section: str
    page_start: int
    page_end: int
    effective_date: str | None = None


class AnswerResult(BaseModel):
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    has_clear_answer: bool = False
    retrieval: list[RetrievedChunk] = Field(default_factory=list)


def _trace(hits: list[Hit]) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            id=h.id,
            score=h.score,
            doc=h.doc,
            section=h.section,
            page_start=h.page_start,
            page_end=h.page_end,
            effective_date=h.effective_date,
        )
        for h in hits
    ]


def answer_question(
    question: str,
    top_k: int = 15,
    rerank: bool = False,
    top_n: int = 5,
) -> AnswerResult:
    hits = retrieve(question, top_k=top_k, rerank=rerank, top_n=top_n)
    # Only the top_n chunks are sent to the model; the rest stay in the trace.
    used = hits[:top_n] if hits else []
    result = generate(question, used)
    return AnswerResult(
        question=question,
        answer=result.get("answer", ""),
        citations=[Citation(**c) for c in result.get("citations", [])],
        has_clear_answer=bool(result.get("has_clear_answer", False)),
        retrieval=_trace(hits),
    )
