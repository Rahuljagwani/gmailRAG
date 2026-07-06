"""
Generation layer: turn retrieved chunks into a grounded, structured answer.

Uses Claude with a strict grounding prompt. Structured output is obtained via a
forced tool call (Sonnet 4.6 does not support assistant prefill), so the model must
return the exact JSON shape -- {answer, citations[], has_clear_answer} -- or the
request errors rather than drifting into free text.

Grounding rules enforced in the prompt:
  * Answer ONLY from the numbered sources provided; never use outside knowledge.
  * Cite a source for every factual claim (doc + section + page + a short quote).
  * If the sources do not contain the answer, set has_clear_answer=false and say what
    is missing -- do not guess.
  * When the same figure appears with different effective dates, prefer the most
    recent and note the older value (handles the plan-year conflict trap).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from rag.retrieve import Hit  # noqa: E402

SYSTEM = """You are a benefits assistant that drafts replies to employee questions about \
their company benefit plans. You must answer using ONLY the numbered source excerpts \
provided in the user message -- these are passages retrieved from the official plan \
documents. Never use outside knowledge or assumptions.

Rules:
1. Ground every factual claim in the sources. For EACH claim in your answer, add a \
citation (document, section, page) with a short verbatim quote. If your answer contains \
any claim drawn from the sources, the citations array MUST NOT be empty.
2. Set has_clear_answer=true when the sources let you substantively answer the main \
question. In that case you MUST provide citations. Set has_clear_answer=false ONLY when \
the sources do not let you answer the main question; then keep the answer to a brief \
explanation of what is missing and do NOT write a detailed grounded answer.
3. Consistency: never return a detailed, source-backed answer while has_clear_answer is \
false, and never return has_clear_answer=true with an empty citations array. These must \
agree.
4. Multi-part questions: if some parts are answerable from the sources and some are not \
(e.g. a personal fact like "the same plan my manager has"), set has_clear_answer=true, \
answer the supported parts with citations, and clearly flag the unsupported part as \
something the documents don't cover. Never guess or fabricate the unsupported part.
5. CONDITIONAL COVERAGE IS STILL A CLEAR ANSWER. If the sources contain a provision that \
addresses the question, describing that provision counts as answering it -- even if the \
outcome depends on conditions (e.g. "reimbursed only if the service isn't available within \
100 miles"). In that case set has_clear_answer=true, state the conditions plainly, and cite \
them. Do not treat "it depends" or the sender's own uncertainty as a reason to set false.
6. If the same figure appears under different effective dates, use the MOST RECENT \
effective date and mention that an older value existed. Never average or mix them.
7. Write the answer as a complete, ready-to-send email reply:
   - Open with a short greeting. If a sender name is given and it looks like a personal \
first name, use "Hi <FirstName>,"; otherwise use "Hi there,".
   - Then 1-3 concise paragraphs. Use short bullets ONLY for a list of figures/steps.
   - Close with a brief professional sign-off: "Best regards," on its own line, then \
"Benefits Team".
   Keep the whole reply concise and skimmable - short is better than exhaustive.

Final self-check before you submit: if your answer describes ANY plan provision or figure \
from the sources, then has_clear_answer MUST be true and citations MUST be non-empty."""

ANSWER_TOOL = {
    "name": "submit_answer",
    "description": "Return the grounded answer, its citations, and whether the sources clearly answered the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assessment": {
                "type": "string",
                "description": (
                    "FILL THIS FIRST. In one or two sentences, state whether the SOURCES "
                    "contain a provision or figure that addresses the sender's question, "
                    "naming the relevant [Source N]. If any source addresses it (even "
                    "conditionally), has_clear_answer must be true and you must cite it. "
                    "Only if no source addresses the main question is has_clear_answer false."
                ),
            },
            "has_clear_answer": {
                "type": "boolean",
                "description": "True only if the sources clearly and fully answer the question.",
            },
            "citations": {
                "type": "array",
                "description": "One entry per source actually used to support a claim.",
                "items": {
                    "type": "object",
                    "properties": {
                        "doc": {"type": "string", "description": "Source document name."},
                        "section": {"type": "string", "description": "Section title cited."},
                        "page": {"type": "integer", "description": "Page number cited."},
                        "quote": {
                            "type": "string",
                            "description": "Short verbatim quote from the source supporting the claim.",
                        },
                    },
                    "required": ["doc", "section", "page", "quote"],
                },
            },
            "answer": {
                "type": "string",
                "description": "The drafted reply text, grounded only in the sources. Keep it "
                "focused and reasonably concise so the full structured response fits.",
            },
        },
        "required": ["assessment", "has_clear_answer", "citations", "answer"],
    },
}


def _format_sources(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        pages = (
            f"p{h.page_start}"
            if h.page_start == h.page_end
            else f"p{h.page_start}-{h.page_end}"
        )
        eff = f" | effective_date: {h.effective_date}" if h.effective_date else ""
        blocks.append(
            f"[Source {i}] doc: {h.doc} | section: {h.section} | {pages}{eff}\n{h.text}"
        )
    return "\n\n".join(blocks)


def build_user_message(question: str, hits: list[Hit], sender_name: str = "") -> str:
    sender_line = f"SENDER NAME: {sender_name}\n\n" if sender_name.strip() else ""
    if not hits:
        return (
            f"{sender_line}QUESTION:\n{question}\n\nSOURCES:\n(none retrieved)\n\n"
            "No sources were retrieved. Set has_clear_answer to false."
        )
    return (
        f"{sender_line}QUESTION:\n{question}\n\n"
        f"SOURCES (answer only from these):\n{_format_sources(hits)}"
    )


def _client():
    from anthropic import Anthropic

    return Anthropic(api_key=config.require("ANTHROPIC_API_KEY"))


def generate(
    question: str, hits: list[Hit], sender_name: str = "", max_tokens: int = 2048
) -> dict:
    """Call Claude with the grounding prompt and return the structured answer dict.

    Control fields (has_clear_answer, citations) are ordered before the long ``answer``
    field in the schema, so if the response is ever truncated the grounding metadata is
    still intact. max_tokens is generous to avoid truncating the answer prose itself.
    """
    resp = _client().messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[
            {"role": "user", "content": build_user_message(question, hits, sender_name)}
        ],
        tools=[ANSWER_TOOL],
        tool_choice={"type": "tool", "name": "submit_answer"},
    )
    if resp.stop_reason == "max_tokens":
        # Answer prose was cut off, but the ordered control fields should still be present.
        print(f"[warn] generation hit max_tokens ({max_tokens}); answer may be truncated.")
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_answer":
            return dict(block.input)
    # Should not happen with forced tool_choice, but fail loudly rather than silently.
    raise RuntimeError("Model did not return a submit_answer tool call.")
