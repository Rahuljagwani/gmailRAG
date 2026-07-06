"""
Run a benefits question end-to-end from the terminal (test the brain).

    python cli.py "What is the 2026 FSA contribution limit?"
    python cli.py --rerank "orthodontia lifetime maximum in and out of network"
    python cli.py --top-k 20 --top-n 6 "does the plan cover travel for a specialist?"

Prints the drafted answer, a warning when the sources don't clearly answer, the
citations, and the retrieval trace.
"""
from __future__ import annotations

import argparse

from rag.answer import answer_question


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the benefits RAG a question.")
    ap.add_argument("question", nargs="+", help="the question text")
    ap.add_argument("--top-k", type=int, default=15, help="dense candidates to retrieve")
    ap.add_argument("--top-n", type=int, default=5, help="chunks sent to the model")
    ap.add_argument("--rerank", action="store_true", help="enable rung-2 Pinecone rerank")
    args = ap.parse_args()

    question = " ".join(args.question)
    res = answer_question(question, top_k=args.top_k, rerank=args.rerank, top_n=args.top_n)

    print(f"\nQ: {res.question}\n")
    if not res.has_clear_answer:
        print("[!] No clear answer from the documents.\n")
    print(res.answer)

    if res.citations:
        print("\nCitations:")
        for c in res.citations:
            print(f"  - {c.doc} · {c.section} (p{c.page}): \"{c.quote}\"")

    print("\nRetrieval trace (top candidates):")
    for i, r in enumerate(res.retrieval[:8], 1):
        eff = f", eff {r.effective_date}" if r.effective_date else ""
        print(f"  {i:2}. [{r.score:.3f}] {r.doc} · {r.section} (p{r.page_start}{eff})")


if __name__ == "__main__":
    main()
