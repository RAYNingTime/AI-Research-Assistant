"""
scraper.py
──────────
Responsible for fetching raw web pages and extracting clean article text.

Design decisions
----------------
* ``httpx`` is used for HTTP requests: it is modern, supports HTTP/2, and
  has a clean async API.
* ``trafilatura`` performs state-of-the-art boilerplate removal.  It outperforms
  BeautifulSoup-based approaches on real-world news and research sites and
  requires zero manual CSS/XPath selectors.
* Content is truncated to ``MAX_CHARS_PER_PAGE`` characters **before** it
  reaches the LLM, keeping token consumption predictable and low.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
import trafilatura

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (populated from environment variables set by main.py)
# ---------------------------------------------------------------------------
MAX_CHARS_PER_PAGE: int = int(os.getenv("MAX_CHARS_PER_PAGE", "8000"))
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))

_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AI-Research-Assistant/1.0; "
        "automated research digest bot)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> Optional[str]:
    """
    Download ``url`` and return the raw HTML as a string.

    Returns ``None`` on any network or HTTP error so that the caller can
    decide whether to skip or retry.
    """
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT,
            headers=_HEADERS,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s for %s", exc.response.status_code, url)
    except httpx.RequestError as exc:
        logger.warning("Request error for %s: %s", url, exc)
    return None


def extract_text(html: str, url: str = "") -> Optional[str]:
    """
    Extract the main article text from *html* using trafilatura.

    ``url`` is passed as a hint so that trafilatura can apply site-specific
    extraction rules.  Returns ``None`` when extraction yields no content.
    """
    text = trafilatura.extract(
        html,
        url=url or None,
        include_comments=False,
        include_tables=False,
        no_fallback=False,  # allow heuristic fallback for edge cases
    )
    return text or None


def scrape(url: str) -> Optional[str]:
    """
    Fetch *url*, extract its main text, and truncate to ``MAX_CHARS_PER_PAGE``
    characters.

    This is the single entry-point used by the rest of the application.
    Pre-truncating the content here (before it ever reaches the summariser)
    is the primary token-saving measure in the pipeline.

    Returns ``None`` when the page cannot be fetched or yields no content.
    """
    logger.info("Scraping %s", url)

    html = fetch_page(url)
    if html is None:
        logger.warning("Could not fetch %s — skipping.", url)
        return None

    text = extract_text(html, url=url)
    if not text:
        logger.warning("No extractable content at %s — skipping.", url)
        return None

    # Truncate to stay within the configured token budget
    if len(text) > MAX_CHARS_PER_PAGE:
        text = text[:MAX_CHARS_PER_PAGE] + "\n… [truncated]"

    logger.debug("Extracted %d chars from %s", len(text), url)
    return text


def scrape_all(urls: list[str]) -> dict[str, str]:
    """
    Scrape every URL in *urls* and return a mapping ``{url: text}``.

    URLs that fail or yield no content are silently omitted from the result
    so that the caller only receives successfully scraped pages.
    """
    results: dict[str, str] = {}
    for url in urls:
        content = scrape(url)
        if content:
            results[url] = content
    return results
