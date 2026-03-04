"""
memory.py
─────────
Persistent memory block that stores every daily research summary produced by
the assistant.

Storage format
--------------
A single JSON file (default: ``memory.json``) with the following structure:

    {
      "summaries": [
        {
          "date":    "2025-01-15",
          "sources": ["https://arxiv.org/...", ...],
          "summary": "Today's AI research highlights: ..."
        },
        ...
      ]
    }

The list is kept in chronological order (oldest first).  Entries are *never*
deleted automatically; the file therefore grows as a running log.

Design decisions
----------------
* Plain JSON is chosen over SQLite or a vector DB because it is zero-dependency,
  human-readable, and sufficient for a sequential diary of daily summaries.
* The public API is intentionally small so that other modules stay decoupled
  from the storage details.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# Default path; overridden by the MEMORY_FILE environment variable (set in main).
_DEFAULT_PATH = os.getenv("MEMORY_FILE", "memory.json")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load(path: str) -> dict:
    """Load the JSON store from *path*, returning an empty store on first run."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Could not read memory file %s: %s", path, exc)
    return {"summaries": []}


def _save(store: dict, path: str) -> None:
    """Persist *store* to *path* atomically (write-then-rename)."""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(store, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.error("Could not write memory file %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_summary(
    summary: str,
    sources: list[str],
    run_date: Optional[date] = None,
    path: str = _DEFAULT_PATH,
) -> None:
    """
    Append a new daily *summary* (with its *sources*) to the memory store.

    If *run_date* is ``None`` the current UTC date is used.
    """
    entry = {
        "date": str(run_date or date.today()),
        "sources": sources,
        "summary": summary,
    }

    store = _load(path)
    store.setdefault("summaries", []).append(entry)
    _save(store, path)
    logger.info("Summary saved to memory (%s).", entry["date"])


def get_all_summaries(path: str = _DEFAULT_PATH) -> list[dict]:
    """Return all stored summary entries (chronological order)."""
    return _load(path).get("summaries", [])


def get_recent_summaries(n: int = 5, path: str = _DEFAULT_PATH) -> list[dict]:
    """Return the *n* most-recent summary entries (newest first)."""
    all_entries = get_all_summaries(path)
    return list(reversed(all_entries[-n:])) if all_entries else []


def format_memory_context(n: int = 5, path: str = _DEFAULT_PATH) -> str:
    """
    Build a compact, human-readable string of the *n* most recent summaries
    suitable for inclusion in an LLM system prompt.

    Returns an empty string when there is no prior history.
    """
    recent = get_recent_summaries(n=n, path=path)
    if not recent:
        return ""

    lines: list[str] = ["=== Previous Daily Summaries (most recent first) ==="]
    for entry in recent:
        lines.append(f"\n[{entry['date']}]")
        lines.append(entry["summary"])

    return "\n".join(lines)
