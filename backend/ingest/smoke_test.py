"""
smoke test: confirm the built index retrieves sane chunks.

Runs a few benefits questions against the live index and prints the top hits with
their citations. Two of these are the hardest cases from the sample emails and we
assert the right document surfaces in the top results:

  * FSA 2026 contribution limit  -> expect HCSA.pdf
  * Orthodontia lifetime maximum -> expect DentalPPO.pdf (and ideally the 2022 chunk)

This is a retrieval sanity check only -- generation/grounding comes in Commit 4.

Usage (from backend/, with PINECONE creds in .env):  python -m ingest.smoke_test
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.retrieve import retrieve  # noqa: E402

CASES = [
    {
        "q": "What is the 2026 FSA / health care spending account contribution limit and minimum?",
        "expect_doc": "HCSA",
    },
    {
        "q": "What is the orthodontia lifetime maximum for in-network and out-of-network?",
        "expect_doc": "DentalPPO",
    },
    {
        "q": "What does the vision plan cover for eye exams and frames?",
        "expect_doc": "VisionBasic",
    },
]


def _doc_matches(hit_doc: str, expect: str) -> bool:
    return expect.lower() in hit_doc.lower()


def main() -> int:
    failures = 0
    for case in CASES:
        q, expect = case["q"], case["expect_doc"]
        hits = retrieve(q, top_k=10)
        print(f"\nQ: {q}")
        if not hits:
            print("  !! no hits returned")
            failures += 1
            continue
        top_docs = {h.doc for h in hits[:5]}
        ok = any(_doc_matches(d, expect) for d in top_docs)
        rank = next((i for i, h in enumerate(hits, 1) if _doc_matches(h.doc, expect)), None)
        for i, h in enumerate(hits[:5], 1):
            print(f"  {i}. [{h.score:.3f}] {h.citation()}")
        status = "OK" if ok else "MISS"
        print(f"  -> expect {expect}: {status}" + (f" (rank {rank})" if rank else ""))
        if not ok:
            failures += 1

    print("\n" + ("All smoke cases passed." if failures == 0 else f"{failures} case(s) failed."))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
