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
├── digest/          # Build/render/export structured daily digests (JSON/MD/PDF)
├── examples/        # Mock inputs + sample output
├── sources.csv      # List of AI research websites to scrape
├── .env.example     # Template for required environment variables
├── requirements.txt # Python dependencies
└── README.md        # This file
```

---

## Quick Start

### 1 — Clone & install dependencies

**Windows PowerShell**

```powershell
git clone https://github.com/RAYNingTime/AI-Research-Assistant.git
cd .\AI-Research-Assistant
python -m venv .venv

# If activation is blocked:
# Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1

python -m pip install -r .\requirements.txt
```

**macOS/Linux**

```bash
git clone https://github.com/RAYNingTime/AI-Research-Assistant.git
cd AI-Research-Assistant
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2 — Configure environment variables

**Windows PowerShell**

```powershell
Copy-Item .\.env.example .\.env
```

**macOS/Linux**

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

## Structured Daily Digests (JSON → Markdown → PDF)

This repo includes a `digest/` module that produces **human-readable**, **deduplicated** daily reports.
It reads from `memory.json` (or a single raw `{date,sources,summary}` JSON file) and writes:

- JSON output: `./reports_json/YYYY-MM-DD.json`
- Markdown output: `./reports_md/YYYY-MM-DD.md`
- PDF output: `./reports_pdf/YYYY-MM-DD.pdf`

### Commands (Windows PowerShell)

Run these from the repo root:

```powershell
# (Optional) activate the venv first, then just use `python`
.\.venv\Scripts\Activate.ps1

# 1) Run the main pipeline (updates memory.json)
python .\main.py

# 2) Build digest JSON for a specific date (YYYY-MM-DD)
python -m digest build --date 2026-03-05 --input .\memory.json --out .\reports_json --force

# 3) Render Markdown from the digest JSON
python -m digest render --date 2026-03-05 --in .\reports_json --out .\reports_md

# 4) Export PDF from the Markdown
python -m digest pdf --date 2026-03-05 --md-dir .\reports_md --out .\reports_pdf

# Or do steps 2–4 in one go:
python -m digest all --date 2026-03-05 --input .\memory.json --force
```

If you don’t have a PDF backend installed yet, run only build+render:

```powershell
python -m digest build  --date 2026-03-05 --input .\examples\mock_raw.json --out .\reports_json --force
python -m digest render --date 2026-03-05 --in .\reports_json --out .\reports_md
```

### PDF dependencies

Two backends are supported (auto-selected):

1) **Pandoc (preferred)**: install `pandoc` and a TeX engine (MiKTeX / TeX Live).  
2) **Python fallback**: install `markdown2` (or `markdown`) plus `weasyprint`.
   - On Windows, WeasyPrint also requires external GTK/Pango libraries; if those aren’t installed, PDF export fails with missing `libgobject-2.0-0`.
   - Install the Python packages with: `python -m pip install markdown2 weasyprint`

Notes:
- If you see PowerShell errors like “`.venv\\Scripts\\python.exe` is not recognized”, use `.\.venv\Scripts\python.exe` (or activate the venv first).
- If `memory.json` contains multiple entries for the same `date` (from multiple runs), `digest build` selects the most informative one.

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
