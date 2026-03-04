# AI Research Assistant

An automated pipeline that **scrapes leading AI research websites daily** and
uses **xAI Grok 4 fast reasoning** to produce concise, structured digests of
the latest developments in Artificial Intelligence.

---

## Features

| Feature | Details |
|---|---|
| **LLM** | xAI Grok 4 (`grok-4-fast-reasoning`) via OpenAI-compatible API |
| **Scraping** | `trafilatura` + `httpx` — state-of-the-art boilerplate removal, no manual selectors |
| **Token saving** | Content pre-truncated before the LLM ever sees it (`MAX_CHARS_PER_PAGE`) |
| **Memory** | Persistent JSON store of all previous daily summaries; injected as context |
| **Persona** | Configurable (currently empty — fill in `PERSONA` in `summarizer.py`) |
| **Scheduling** | APScheduler cron daemon (`--schedule`) or single one-shot run (default) |
| **Sources** | External `sources.csv` — edit freely to add / remove websites |

---

## Project Structure

```
AI-Research-Assistant/
├── main.py          # Orchestrator: load sources → scrape → summarise → persist
├── scraper.py       # Web fetching & text extraction (httpx + trafilatura)
├── summarizer.py    # Grok 4 API integration & prompt construction
├── memory.py        # Persistent JSON memory block for all past summaries
├── sources.csv      # List of AI research websites to scrape
├── .env.example     # Template for required environment variables
├── requirements.txt # Python dependencies
└── README.md        # This file
```

---

## Quick Start

### 1 — Clone & install dependencies

```bash
git clone https://github.com/RAYNingTime/AI-Research-Assistant.git
cd AI-Research-Assistant
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

### 2 — Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and set **at minimum**:

```dotenv
XAI_API_KEY=xai-your-key-here   # https://console.x.ai/
```

All other variables have sensible defaults (see `.env.example` for details).

### 3 — Run once

```bash
python main.py
```

The assistant will:
1. Load source URLs from `sources.csv`.
2. Scrape each site and strip boilerplate (tokens saved here!).
3. Retrieve the last 5 summaries from `memory.json` as context.
4. Call Grok 4 to produce today's digest.
5. Save the new summary to `memory.json`.
6. Print the digest to stdout.

### 4 — Run as a daily daemon

```bash
python main.py --schedule
```

Uses the `SCHEDULE_CRON` value from `.env` (default: `0 7 * * *` = 07:00 UTC
every day) to run the pipeline automatically.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `XAI_API_KEY` | *(required)* | Your xAI API key |
| `MAX_CHARS_PER_PAGE` | `8000` | Characters extracted per scraped page (token control) |
| `REQUEST_TIMEOUT` | `30` | HTTP request timeout in seconds |
| `SCHEDULE_CRON` | `0 7 * * *` | Cron expression for the daily daemon |
| `MEMORY_FILE` | `memory.json` | Path to the persistent summary store |
| `SOURCES_CSV` | `sources.csv` | Path to the website list CSV |

---

## Adding or Removing Sources

Edit `sources.csv`.  Each row needs at minimum a `url` column:

```csv
name,url,category,notes
My New Source,https://example.com/ai-news,News,Optional description
```

The scraper only reads the `url` column; all other columns are metadata for
human reference.

---

## Memory Store Format

`memory.json` grows over time as a chronological log:

```json
{
  "summaries": [
    {
      "date": "2025-01-15",
      "sources": ["https://arxiv.org/list/cs.AI/recent", "..."],
      "summary": "**arXiv cs.AI** — ..."
    }
  ]
}
```

The last *N* entries (configurable via `MEMORY_CONTEXT_COUNT` in
`summarizer.py`, default 5) are automatically injected into each new prompt so
the model avoids repeating previously covered research.

---

## Persona

The `PERSONA` constant in `summarizer.py` is currently **empty**.  You can give
the assistant a specific voice or expertise by setting it, for example:

```python
PERSONA: str = "You are a senior ML researcher specialising in LLMs and AI safety."
```

---

## Token-Saving Design

1. **Pre-truncation in `scraper.py`** — each page is capped at
   `MAX_CHARS_PER_PAGE` characters *before* reaching the LLM.
2. **Selective memory** — only the *n* most-recent summaries are included as
   context (not the full history).
3. **Concise output instruction** — the system prompt asks for bullet-point
   output capped at 800 words.

---

## License

MIT
