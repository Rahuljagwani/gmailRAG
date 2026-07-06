"""Generation layer: turn retrieved chunks into a grounded, structured answer.

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
1. Ground every factual claim in the sources. For each claim, cite the source it came \
from (document, section, page) and include a short verbatim quote.
2. If the sources do not clearly answer the question, set has_clear_answer to false and \
briefly explain what information is missing. Do NOT guess or fabricate.
3. Some questions cannot be answered from plan documents at all (e.g. personal facts \
like "the same plan my manager has", or costs not covered by the plans). For those, set \
has_clear_answer to false and say the documents don't cover it.
4. If the same figure appears under different effective dates, use the MOST RECENT \
effective date and mention that an older value existed. Never average or mix them.
5. Write the answer in a warm, clear, professional tone suitable for pasting into an \
email reply. Be concise; do not invent greetings or signatures."""

ANSWER_TOOL = {
    "name": "submit_answer",
    "description": "Return the grounded answer, its citations, and whether the sources clearly answered the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The drafted reply text, grounded only in the sources.",
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
            "has_clear_answer": {
                "type": "boolean",
                "description": "True only if the sources clearly and fully answer the question.",
            },
        },
        "required": ["answer", "citations", "has_clear_answer"],
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


def build_user_message(question: str, hits: list[Hit]) -> str:
    if not hits:
        return (
            f"QUESTION:\n{question}\n\nSOURCES:\n(none retrieved)\n\n"
            "No sources were retrieved. Set has_clear_answer to false."
        )
    return (
        f"QUESTION:\n{question}\n\n"
        f"SOURCES (answer only from these):\n{_format_sources(hits)}"
    )


def _client():
    from anthropic import Anthropic

    return Anthropic(api_key=config.require("ANTHROPIC_API_KEY"))


def generate(question: str, hits: list[Hit], max_tokens: int = 1024) -> dict:
    """Call Claude with the grounding prompt and return the structured answer dict."""
    resp = _client().messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_user_message(question, hits)}],
        tools=[ANSWER_TOOL],
        tool_choice={"type": "tool", "name": "submit_answer"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_answer":
            return dict(block.input)
    # Should not happen with forced tool_choice, but fail loudly rather than silently.
    raise RuntimeError("Model did not return a submit_answer tool call.")
