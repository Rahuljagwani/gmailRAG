"""
Run the 5 sample emails end-to-end and dump results for inspection.

For each email it builds the query (subject + body), calls the RAG, and writes:
  * outputs/email_<n>.md   -- human-readable answer + citations + retrieval trace
  * outputs/eval_results.json -- machine-readable full dump

It also prints soft checks against eval/sample_emails.json expectations:
  * expected document(s) appear in the retrieval trace
  * required strings (e.g. "$3,300") appear in the answer
  * has_clear_answer matches the expectation (when the expectation is not null)

These checks are advisory -- the point of Step 5 is to eyeball grounding quality and
decide whether to climb the retrieval ladder, not to hard-pass/fail a suite.

Usage (from backend/):  python -m eval.run_eval
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.answer import AnswerResult, answer_question  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
OUT_DIR = EVAL_DIR.parent.parent / "outputs"


def _query(email: dict) -> str:
    return f"Subject: {email['subject']}\n\n{email['body']}"


def _checks(email: dict, res: AnswerResult) -> list[str]:
    exp = email.get("expect", {})
    lines: list[str] = []

    want_docs = exp.get("docs") or []
    seen_docs = {r.doc for r in res.retrieval}
    for d in want_docs:
        hit = any(d.lower() in s.lower() for s in seen_docs)
        lines.append(f"  [{'OK' if hit else 'MISS'}] expected doc in retrieval: {d}")

    for s in exp.get("must_mention") or []:
        present = s.lower() in res.answer.lower()
        lines.append(f"  [{'OK' if present else 'MISS'}] answer mentions: {s}")

    want_clear = exp.get("clear_answer")
    if want_clear is None:
        lines.append(f"  [--] has_clear_answer={res.has_clear_answer} (judgment case, inspect)")
    else:
        ok = res.has_clear_answer == want_clear
        lines.append(
            f"  [{'OK' if ok else 'MISS'}] has_clear_answer={res.has_clear_answer} "
            f"(expected {want_clear})"
        )
    return lines


def _write_md(email: dict, res: AnswerResult) -> Path:
    p = OUT_DIR / f"email_{email['id']}.md"
    lines = [
        f"# Email {email['id']}: {email['subject']}",
        f"\n**From:** {email['from']}",
        f"\n**Body:**\n\n> {email['body']}",
        f"\n**has_clear_answer:** `{res.has_clear_answer}`",
        "\n## Drafted answer\n",
        res.answer,
        "\n## Citations\n",
    ]
    if res.citations:
        for c in res.citations:
            lines.append(f"- **{c.doc} · {c.section}** (p{c.page}): \"{c.quote}\"")
    else:
        lines.append("_(none)_")
    lines.append("\n## Retrieval trace (top 8)\n")
    for i, r in enumerate(res.retrieval[:8], 1):
        eff = f", eff {r.effective_date}" if r.effective_date else ""
        lines.append(f"{i}. `[{r.score:.3f}]` {r.doc} · {r.section} (p{r.page_start}{eff})")
    p.write_text("\n".join(lines) + "\n")
    return p


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    emails = json.loads((EVAL_DIR / "sample_emails.json").read_text())

    dump = []
    misses = 0
    for email in emails:
        res = answer_question(_query(email))
        _write_md(email, res)
        dump.append({"email": email, "result": res.model_dump()})

        print(f"\n{'='*70}\nEmail {email['id']}: {email['subject']}")
        print(f"clear_answer={res.has_clear_answer} | citations={len(res.citations)}")
        for line in _checks(email, res):
            print(line)
            if "[MISS]" in line:
                misses += 1

    (OUT_DIR / "eval_results.json").write_text(json.dumps(dump, indent=2))
    print(f"\n{'='*70}\nWrote {len(emails)} answers to {OUT_DIR}")
    print("All expectation checks passed." if misses == 0 else f"{misses} check(s) to review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
