"""Parse benefit plan PDFs into structured lines with heading + page metadata.

All 8 provided PDFs have a real text layer (verified), so no OCR is needed. Section
headings are detected by font size: body text is 8-10pt, headings are 12pt+. We also
flag "effective <date>" lines, which matter because some documents (notably DentalPPO)
state the same benefit at multiple effective dates -- the answer layer must prefer the
most recent one.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

# "effective January 1, 2026", "effective as of January 1, 2022"
EFFECTIVE_RE = re.compile(
    r"effective(?:\s+as\s+of)?\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},\s+(\d{4})",
    re.IGNORECASE,
)


@dataclass
class Line:
    page: int
    text: str
    size: float
    is_heading: bool
    effective_date: str | None = None


@dataclass
class ParsedDoc:
    name: str
    lines: list[Line] = field(default_factory=list)


def _group_lines(page) -> list[tuple[str, float]]:
    """Return (text, max_font_size) per line in natural reading order.

    Uses pdfplumber's extract_text_lines() (correct reading order) while keeping access to
    each line's chars so we can read font size for heading detection.
    """
    out = []
    for ln in page.extract_text_lines():
        text = ln["text"].strip()
        if not text:
            continue
        max_size = max((c.get("size") or 0) for c in ln["chars"])
        out.append((text, round(max_size, 1)))
    return out


def _body_mode_size(page_lines: list[list[tuple[str, float]]]) -> float:
    counts: Counter = Counter()
    for lines in page_lines:
        for text, size in lines:
            counts[size] += len(text)
    return counts.most_common(1)[0][0] if counts else 10.0


def parse_pdf(path: str | Path) -> ParsedDoc:
    path = Path(path)
    doc = ParsedDoc(name=path.stem)
    with pdfplumber.open(path) as pdf:
        page_lines = [_group_lines(p) for p in pdf.pages]

    body = _body_mode_size(page_lines)
    heading_threshold = max(body + 2.0, 11.5)

    for page_idx, lines in enumerate(page_lines, start=1):
        for text, size in lines:
            is_heading = (
                size >= heading_threshold
                and len(text) < 120
                and any(ch.isalpha() for ch in text)
            )
            m = EFFECTIVE_RE.search(text)
            eff = None
            if m:
                eff = f"{m.group(1).title()} {m.group(0).split()[-1]}".replace(",", "")
                # normalize to "Month YYYY"
                eff = f"{m.group(1).title()} {m.group(2)}"
            doc.lines.append(
                Line(page=page_idx, text=text, size=size, is_heading=is_heading, effective_date=eff)
            )
    return doc


if __name__ == "__main__":
    import sys

    d = parse_pdf(sys.argv[1])
    headings = [l for l in d.lines if l.is_heading]
    print(f"{d.name}: {len(d.lines)} lines, {len(headings)} headings")
    for l in headings[:25]:
        print(f"  p{l.page:3} [{l.size:4.1f}] {l.text}")
