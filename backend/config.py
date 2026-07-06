"""Central config: loads backend/.env and exposes settings used across the backend."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

# --- Pinecone (integrated embedding index) ---
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "sigflow-index")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "__default__")

# --- Generation (Claude) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# --- Backend auth ---
BACKEND_SHARED_SECRET = os.getenv("BACKEND_SHARED_SECRET", "")

# --- Paths ---
CHUNKS_PATH = BACKEND_DIR / "data" / "chunks.jsonl"

# The field in each record whose text Pinecone embeds server-side. Must match the
# field_map chosen when the integrated-embedding index was created.
EMBED_FIELD = "text"


def require(name: str) -> str:
    val = globals().get(name, "")
    if not val:
        raise SystemExit(f"Missing required config: {name}. Set it in backend/.env")
    return val
