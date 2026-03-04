"""
main.py
───────
Entry-point for the AI Research Assistant.

Modes of operation
------------------
1. **Single run** (default / ``--once`` flag):
   Scrape all sources, generate a summary, persist to memory, and exit.

2. **Scheduled daemon** (``--schedule`` flag):
   Start APScheduler and execute the same pipeline on the cron schedule
   defined by the ``SCHEDULE_CRON`` environment variable
   (default: every day at 07:00 UTC).

Usage
-----
    # One-shot run
    python main.py

    # Daemon mode (runs continuously on the configured cron schedule)
    python main.py --schedule

Environment variables
---------------------
All configuration is read from a ``.env`` file (see ``.env.example``).
The only *required* variable is ``XAI_API_KEY``.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# ── Load .env before any other local imports so that os.getenv calls inside
#    scraper.py / summarizer.py / memory.py pick up the correct values.
load_dotenv()

# Local modules (imported *after* load_dotenv)
import memory as mem
import scraper
import summarizer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test mode: hardcoded sources (set to True to skip live scraping)
# ---------------------------------------------------------------------------
USE_TEST_DATA = False

TEST_SCRAPED_DATA = {
    "https://arxiv.org/list/cs.AI/new": "arXiv cs.AI: Recent submissions include papers on federated learning privacy, reasoning benchmarks for LLMs, and novel multi-agent memory systems.",
    "https://huggingface.co/papers": "Hugging Face Papers: Trending work includes Moonshine ASR model with rotary embeddings and efficient encoder-decoder architectures.",
    "https://openai.com/research/": "OpenAI Research: Latest publications on reinforcement learning from human feedback and constitutional AI methods.",
}


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------

def load_sources(csv_path: str) -> list[str]:
    """
    Read the list of URLs to scrape from *csv_path*.

    The CSV must have a column named ``url`` (case-insensitive).  All other
    columns are ignored so the file can carry metadata (name, category, notes)
    without affecting this function.

    Returns a deduplicated list of non-empty URL strings.
    """
    path = Path(csv_path)
    if not path.exists():
        logger.error("Sources CSV not found: %s", csv_path)
        return []

    urls: list[str] = []
    seen: set[str] = set()

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        # Normalise column names to lowercase for robustness
        for row in reader:
            normalised = {k.strip().lower(): v.strip() for k, v in row.items()}
            url = normalised.get("url", "")
            if url and url not in seen:
                urls.append(url)
                seen.add(url)

    logger.info("Loaded %d sources from %s.", len(urls), csv_path)
    return urls


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run_pipeline() -> None:
    """
    Execute one full research-scraping-and-summarisation cycle:

    1. Load source URLs from the CSV file.
    2. Scrape each source (pre-truncated to save tokens).
    3. Retrieve recent prior summaries as memory context.
    4. Send scraped content to Grok 4 for summarisation.
    5. Persist the new summary to the memory store.
    6. Print the summary to stdout.
    """
    run_start = datetime.now(tz=timezone.utc)
    logger.info("Pipeline started at %s.", run_start.isoformat())

    # ── 1. Load sources / Use test data ──────────────────────────────────────
    if USE_TEST_DATA:
        logger.info("Using hardcoded test data (USE_TEST_DATA = True).")
        scraped: dict[str, str] = TEST_SCRAPED_DATA
    else:
        sources_csv = os.getenv("SOURCES_CSV", "sources.csv")
        urls = load_sources(sources_csv)
        if not urls:
            logger.error("No source URLs available — aborting pipeline.")
            return

        # ── 2. Scrape ────────────────────────────────────────────────────────
        logger.info("Scraping %d sources…", len(urls))
        scraped: dict[str, str] = scraper.scrape_all(urls)
        if not scraped:
            logger.error("All scraping attempts failed — aborting pipeline.")
            return

        logger.info("Successfully scraped %d / %d sources.", len(scraped), len(urls))

    # ── 3. Memory context ────────────────────────────────────────────────────
    memory_path = os.getenv("MEMORY_FILE", "memory.json")
    memory_context = mem.format_memory_context(
        n=summarizer.MEMORY_CONTEXT_COUNT, path=memory_path
    )

    # ── 4. Summarise ─────────────────────────────────────────────────────────
    summary = summarizer.generate_summary(
        scraped_content=scraped,
        memory_context=memory_context,
    )
    if summary is None:
        logger.error("Summarisation failed — pipeline aborted without saving.")
        return

    # ── 5. Persist ───────────────────────────────────────────────────────────
    mem.append_summary(
        summary=summary,
        sources=list(scraped.keys()),
        path=memory_path,
    )

    # ── 6. Output ────────────────────────────────────────────────────────────
    separator = "═" * 72
    print(f"\n{separator}")
    print(f"  AI Research Daily Digest — {run_start.strftime('%Y-%m-%d')}")
    print(separator)
    print(summary)
    print(separator + "\n")

    duration = (datetime.now(tz=timezone.utc) - run_start).total_seconds()
    logger.info("Pipeline completed in %.1f seconds.", duration)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def start_scheduler(cron_expression: str) -> None:
    """
    Start APScheduler and register the pipeline on *cron_expression*.

    The function blocks until the process is interrupted (Ctrl-C / SIGTERM).
    """
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error(
            "APScheduler is not installed.  Run `pip install APScheduler` "
            "or install from requirements.txt."
        )
        sys.exit(1)

    # Parse "MINUTE HOUR DOM MONTH DOW" into keyword args for CronTrigger
    parts = cron_expression.split()
    if len(parts) != 5:
        logger.error(
            "Invalid SCHEDULE_CRON value %r.  Expected 5 fields: "
            "MINUTE HOUR DOM MONTH DOW.",
            cron_expression,
        )
        sys.exit(1)

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
        timezone="UTC",
    )

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run_pipeline, trigger=trigger, id="daily_research")

    logger.info(
        "Scheduler started.  Next run: %s",
        scheduler.get_jobs()[0].next_run_time,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Research Assistant — daily AI research digest using Grok 4."
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help=(
            "Run as a background daemon on the SCHEDULE_CRON schedule "
            "(default: once and exit)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.schedule:
        cron = os.getenv("SCHEDULE_CRON", "0 7 * * *")
        logger.info("Starting in scheduled mode (cron: %s).", cron)
        start_scheduler(cron)
    else:
        run_pipeline()


if __name__ == "__main__":
    main()
