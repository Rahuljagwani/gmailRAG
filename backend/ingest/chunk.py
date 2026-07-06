"""
Chunk parsed docs into retrieval units carrying section + page + effective-date metadata.

Strategy: start a new chunk at each section heading (font-size detected). Merge consecutive
heading lines into one section title. Split overly long sections into sub-chunks with small
line overlap so no chunk exceeds the target size. Every chunk records the document, section
title, page range, and the most recent effective date seen in it -- so the answer layer can
prefer the newest value when a benefit is restated across plan-year updates.
"""
from __future__ import annotations

import glob
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from parse_pdfs import Line, parse_pdf

TARGET_CHARS = 3200       # ~800 tokens
OVERLAP_LINES = 2         # body lines repeated between sub-chunks of one section


@dataclass
class Chunk:
    id: str
    doc: str
    section: str
    page_start: int
    page_end: int
    effective_date: str | None
    text: str


def _emit(chunks, doc, section, body_lines, seq):
    """Turn accumulated body lines for one section into one or more sub-chunks."""
    if not body_lines:
        return seq
    buf: list[Line] = []
    size = 0

    def flush():
        nonlocal buf, size, seq
        if not buf:
            return
        text = " ".join(l.text for l in buf).strip()
        effs = [l.effective_date for l in buf if l.effective_date]
        chunks.append(
            Chunk(
                id=f"{doc}::{seq}",
                doc=doc,
                section=section or "(untitled)",
                page_start=buf[0].page,
                page_end=buf[-1].page,
                effective_date=effs[-1] if effs else None,
                text=text,
            )
        )
        seq += 1
        buf = buf[-OVERLAP_LINES:] if len(buf) > OVERLAP_LINES else []
        size = sum(len(l.text) for l in buf)

    for line in body_lines:
        if size + len(line.text) > TARGET_CHARS and buf:
            flush()
        buf.append(line)
        size += len(line.text)
    # final flush (no overlap carry-over needed)
    if buf:
        text = " ".join(l.text for l in buf).strip()
        effs = [l.effective_date for l in buf if l.effective_date]
        chunks.append(
            Chunk(
                id=f"{doc}::{seq}",
                doc=doc,
                section=section or "(untitled)",
                page_start=buf[0].page,
                page_end=buf[-1].page,
                effective_date=effs[-1] if effs else None,
                text=text,
            )
        )
        seq += 1
    return seq


def build_chunks(lines: list[Line], doc_name: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    seq = 0
    current_section = ""
    body: list[Line] = []
    pending_heading: list[str] = []
    prev_was_heading = False

    for line in lines:
        if line.is_heading:
            # a new heading block starts -> flush the previous section's body
            if not prev_was_heading:
                seq = _emit(chunks, doc_name, current_section, body, seq)
                body = []
                pending_heading = []
            pending_heading.append(line.text)
            prev_was_heading = True
        else:
            if prev_was_heading and pending_heading:
                current_section = " ".join(pending_heading).strip()
                pending_heading = []
            body.append(line)
            prev_was_heading = False

    seq = _emit(chunks, doc_name, current_section, body, seq)
    return chunks


def main(pattern: str = "../Plan_Documents/*.pdf", out: str = "data/chunks.jsonl") -> None:
    all_chunks: list[Chunk] = []
    for path in sorted(glob.glob(pattern)):
        doc = parse_pdf(path)
        cks = build_chunks(doc.lines, doc.name)
        all_chunks.extend(cks)
        print(f"{doc.name:24} -> {len(cks):4} chunks")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for c in all_chunks:
            f.write(json.dumps(asdict(c)) + "\n")
    print(f"\nTotal: {len(all_chunks)} chunks -> {out}")


if __name__ == "__main__":
    main()
