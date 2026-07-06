"""FastAPI backend for the Gmail Add-on.

Endpoints:
  GET  /health   -> liveness check (no auth)
  POST /answer   -> {subject, body} (or {question}) -> grounded AnswerResult (auth required)

Auth: every /answer request must carry the shared secret in the ``X-API-Key`` header,
matching BACKEND_SHARED_SECRET. This keeps the public endpoint from being open to the
world without the overhead of a full OAuth flow (see DECISIONS §7). The secret lives
server-side here and in the Add-on's PropertiesService only.

Run locally:  uvicorn app:app --reload --port 8000   (from backend/)
"""
from __future__ import annotations

import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, model_validator

import config
from rag.answer import AnswerResult, answer_question

app = FastAPI(title="Grove | HR Reply Assistant backend", version="1.0.0")


class AnswerRequest(BaseModel):
    subject: str = ""
    body: str = ""
    question: str = ""
    top_k: int = 15
    top_n: int = 5
    rerank: bool = False

    @model_validator(mode="after")
    def _need_some_text(self) -> "AnswerRequest":
        if not (self.subject or self.body or self.question).strip():
            raise ValueError("provide at least one of: question, subject, body")
        return self

    def to_query(self) -> str:
        if self.question.strip():
            return self.question.strip()
        parts = []
        if self.subject.strip():
            parts.append(f"Subject: {self.subject.strip()}")
        if self.body.strip():
            parts.append(self.body.strip())
        return "\n\n".join(parts)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    expected = config.BACKEND_SHARED_SECRET
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server auth not configured (BACKEND_SHARED_SECRET unset).",
        )
    # constant-time compare to avoid leaking the secret via timing
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key.",
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "index": config.PINECONE_INDEX, "model": config.ANTHROPIC_MODEL}


@app.post("/answer", response_model=AnswerResult)
def answer(req: AnswerRequest, _: None = Depends(require_api_key)) -> AnswerResult:
    return answer_question(
        req.to_query(), top_k=req.top_k, rerank=req.rerank, top_n=req.top_n
    )
