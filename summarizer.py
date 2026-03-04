"""
summarizer.py
─────────────
Generates concise daily summaries of scraped AI research content using the
xAI Grok API (OpenAI-compatible interface).

Model
-----
``grok-4-0709`` – Grok 4 with fast reasoning enabled via the ``reasoning_effort``
parameter.  Fast reasoning mode keeps latency low while still producing
well-structured analytical summaries.

Token-saving strategy
---------------------
* Scraped content is pre-truncated in ``scraper.py`` before reaching here.
* Only the *n* most-recent prior summaries are included in the context window
  (controlled by ``MEMORY_CONTEXT_COUNT``).
* The model is instructed to produce a *concise* bullet-point summary to
  limit output tokens.

Persona
-------
``PERSONA`` is intentionally left empty.  Fill it in to give the assistant a
specific voice, expertise, or style (e.g. "You are a senior ML researcher…").
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Number of previous summaries to include as memory context in each prompt
MEMORY_CONTEXT_COUNT: int = int(os.getenv("MEMORY_CONTEXT_COUNT", "5"))

# ── Persona ──────────────────────────────────────────────────────────────────
# Leave empty for neutral, factual summaries.
# Example: "You are a senior AI researcher specialising in LLMs and safety."
PERSONA: str = ""


# ---------------------------------------------------------------------------
# xAI client (OpenAI-compatible)
# ---------------------------------------------------------------------------

def _get_client() -> OpenAI:
    """
    Lazily build the OpenAI-compatible xAI client.

    Deferring client construction until the first API call means the module
    can be imported without raising a ``KeyError`` when ``XAI_API_KEY`` is
    not yet available (e.g., during unit tests or documentation builds).
    """
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "XAI_API_KEY is not set. "
            "Copy .env.example to .env and add your xAI API key."
        )
    return OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

_MODEL = "grok-4-0709"


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_system_prompt(memory_context: str) -> str:
    """
    Construct the system prompt, optionally prepending the persona and
    injecting prior-summary memory.
    """
    parts: list[str] = []

    if PERSONA:
        parts.append(PERSONA.strip())

    parts.append(
        "You are an AI research analyst. Your task is to read the scraped "
        "content from multiple AI research websites and produce a concise "
        "daily digest. For each source, extract the most significant recent "
        "findings, paper titles, or announcements. Present the output as "
        "clearly labelled bullet points grouped by source. Keep the total "
        "summary under 800 words. Avoid repeating information already covered "
        "in previous summaries."
    )

    if memory_context:
        parts.append(memory_context)

    return "\n\n".join(parts)


def _build_user_prompt(scraped: dict[str, str]) -> str:
    """
    Format the scraped content dictionary into the user turn of the prompt.
    Each entry is wrapped with a source header so the model can attribute
    findings correctly.
    """
    sections: list[str] = [
        "Below is the content scraped from today's AI research sources. "
        "Please produce the daily summary digest.\n"
    ]

    for url, text in scraped.items():
        sections.append(f"--- SOURCE: {url} ---\n{text}\n")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_summary(
    scraped_content: dict[str, str],
    memory_context: str = "",
) -> Optional[str]:
    """
    Send *scraped_content* (``{url: text}``) to Grok 4 and return the
    generated summary string.

    *memory_context* should be the pre-formatted string produced by
    ``memory.format_memory_context()``.

    Returns ``None`` on API error so that the caller can decide how to handle
    the failure (log, retry, etc.).
    """
    if not scraped_content:
        logger.warning("No scraped content provided — skipping summarisation.")
        return None

    system_prompt = _build_system_prompt(memory_context)
    user_prompt = _build_user_prompt(scraped_content)

    logger.info(
        "Sending %d sources to %s for summarisation…", len(scraped_content), _MODEL
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Fast reasoning: the model reasons internally but responds quickly.
            # Adjust to "high" for deeper analysis at the cost of latency.
            extra_body={"reasoning_effort": "low"},
        )
        summary = response.choices[0].message.content
        logger.info("Summary generated (%d chars).", len(summary or ""))
        return summary
    except Exception as exc:  # noqa: BLE001
        logger.error("Grok API error: %s", exc)
        return None
