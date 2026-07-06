"""Retrieval layer (rung 1: dense-only).

Queries the Pinecone integrated-embedding index with raw text; Pinecone embeds the
query server-side and returns the nearest chunk records with their metadata. The
retrieval strategy is intentionally kept behind this one module so climbing the
upgrade ladder (rung 2 rerank, rung 3 hybrid) is a change here only -- the answer
layer and API contract never change. See PLAN.md §3 and DECISIONS.md §9.

Usage:
    from rag.retrieve import retrieve
    hits = retrieve("What is the 2026 FSA contribution limit?", top_k=15)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# make backend/ importable whether run as a module or a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from pinecone import Pinecone  # noqa: E402

# metadata fields we ask Pinecone to return alongside each hit
RETURN_FIELDS = ["text", "doc", "section", "page_start", "page_end", "effective_date"]

# Rung 2 (reranker) is defined but off by default -- enabled only on eval evidence.
RERANK_MODEL = "bge-reranker-v2-m3"


@dataclass
class Hit:
    id: str
    score: float
    text: str
    doc: str
    section: str
    page_start: int
    page_end: int
    effective_date: str | None

    def citation(self) -> str:
        pages = (
            f"p{self.page_start}"
            if self.page_start == self.page_end
            else f"p{self.page_start}-{self.page_end}"
        )
        eff = f", eff {self.effective_date}" if self.effective_date else ""
        return f"{self.doc} · {self.section} ({pages}{eff})"


@lru_cache(maxsize=1)
def _index():
    api_key = config.require("PINECONE_API_KEY")
    index_name = config.require("PINECONE_INDEX")
    pc = Pinecone(api_key=api_key)
    if not pc.has_index(index_name):
        raise SystemExit(
            f"Index '{index_name}' not found. Build it first: python -m ingest.build_index"
        )
    return pc.Index(index_name)


def _to_hits(response) -> list[Hit]:
    # SearchRecordsResponse -> response.result.hits; each Hit exposes .id/.score/.fields
    result = getattr(response, "result", None)
    raw = getattr(result, "hits", None) or []
    hits: list[Hit] = []
    for h in raw:
        f = getattr(h, "fields", None) or {}
        hits.append(
            Hit(
                id=getattr(h, "id", "") or "",
                score=float(getattr(h, "score", 0.0) or 0.0),
                text=f.get("text", "") or "",
                doc=f.get("doc", "") or "",
                section=f.get("section", "") or "",
                page_start=int(f.get("page_start", 0) or 0),
                page_end=int(f.get("page_end", 0) or 0),
                effective_date=f.get("effective_date"),
            )
        )
    return hits


def retrieve(
    question: str,
    top_k: int = 15,
    rerank: bool = False,
    top_n: int = 5,
) -> list[Hit]:
    """Return the most relevant chunks for a question.

    rung 1 (default): dense-only, returns the top_k nearest chunks.
    rung 2 (rerank=True): retrieve top_k dense, then Pinecone-rerank to top_n.
    """
    kwargs: dict = {
        "namespace": config.PINECONE_NAMESPACE,
        "top_k": top_k,
        "inputs": {"text": question},
        "fields": RETURN_FIELDS,
    }
    if rerank:
        kwargs["rerank"] = {
            "model": RERANK_MODEL,
            "top_n": top_n,
            "rank_fields": ["text"],
        }
    response = _index().search(**kwargs)
    return _to_hits(response)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What is the 2026 FSA contribution limit?"
    for i, h in enumerate(retrieve(q), 1):
        print(f"{i:2}. [{h.score:.3f}] {h.citation()}")
        print(f"    {h.text[:160]}...")
