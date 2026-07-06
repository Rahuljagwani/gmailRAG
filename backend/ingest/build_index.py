"""Upsert chunks into a Pinecone integrated-embedding index.

Reads data/chunks.jsonl (produced by chunk.py) and upserts each chunk as a text record.
Pinecone embeds the ``text`` field server-side (no external embedding key). Non-empty
metadata fields (doc, section, pages, effective_date) are stored for filtering + citations.

Idempotent: re-running upserts the same ids, overwriting in place.

Usage (from backend/):  python -m ingest.build_index
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# make backend/ importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from pinecone import Pinecone  # noqa: E402

BATCH = 90  # integrated upsert_records embeds server-side; keep batches modest


def load_records(path: Path) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            c = json.loads(line)
            rec = {
                "_id": c["id"],
                config.EMBED_FIELD: c["text"],
                "doc": c["doc"],
                "section": c["section"],
                "page_start": c["page_start"],
                "page_end": c["page_end"],
            }
            if c.get("effective_date"):  # Pinecone metadata rejects null values
                rec["effective_date"] = c["effective_date"]
            records.append(rec)
    return records


def main() -> None:
    api_key = config.require("PINECONE_API_KEY")
    index_name = config.require("PINECONE_INDEX")
    ns = config.PINECONE_NAMESPACE

    if not config.CHUNKS_PATH.exists():
        raise SystemExit(
            f"{config.CHUNKS_PATH} not found. Run `python ingest/chunk.py` first."
        )

    records = load_records(config.CHUNKS_PATH)
    print(f"Loaded {len(records)} records from {config.CHUNKS_PATH.name}")

    pc = Pinecone(api_key=api_key)
    if not pc.has_index(index_name):
        raise SystemExit(
            f"Index '{index_name}' not found. Create it as an integrated-embedding index "
            f"(model llama-text-embed-v2, embedded field '{config.EMBED_FIELD}') first."
        )
    index = pc.Index(index_name)

    total = 0
    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        index.upsert_records(namespace=ns, records=batch)
        total += len(batch)
        print(f"  upserted {total}/{len(records)}")
        time.sleep(0.2)  # gentle pacing for server-side embedding

    # wait for indexing to settle, then report vector count
    time.sleep(5)
    stats = index.describe_index_stats()
    print(f"\nDone. Index '{index_name}' namespace '{ns}' stats:")
    print(stats)


if __name__ == "__main__":
    main()
