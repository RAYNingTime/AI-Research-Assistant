from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse, urlunparse

from .schema import BriefBullet, DailyDigest, DigestItem, DigestSection, StatusLine

logger = logging.getLogger(__name__)


SECTION_TITLES: list[str] = [
    "Top papers",
    "Benchmarks & datasets",
    "Safety & reliability",
    "Robotics & embodied AI",
    "Lab releases",
]

LAB_KEYWORDS = {
    "openai",
    "deepmind",
    "anthropic",
    "meta",
    "microsoft",
    "nvidia",
    "apple",
}

TAG_PATTERNS: list[tuple[str, list[str]]] = [
    ("Benchmark", ["benchmark", "leaderboard", "eval", "evaluation", "mt-bench", "mmlu", "gsm8k"]),
    ("Dataset", ["dataset", "corpus", "data release", "curated", "synthetic data"]),
    ("LLM", ["llm", "language model", "transformer", "instruction", "rlhf", "alignment"]),
    ("MoE", ["moe", "mixture of experts", "experts"]),
    ("Efficiency", ["quantization", "distillation", "inference", "serving", "throughput", "latency", "streaming"]),
    ("Vision", ["vision", "vit", "image", "video", "multimodal", "vlm"]),
    ("Diffusion", ["diffusion", "denoising", "score-based", "stable diffusion"]),
    ("Robotics", ["robot", "robotics", "manipulation", "locomotion", "embodied", "slam"]),
    ("Safety", ["safety", "reliability", "robust", "red team", "jailbreak", "toxicity", "hallucination"]),
    ("Federated", ["federated", "on-device", "privacy", "secure aggregation"]),
]

_ARXIV_URL_RE = re.compile(r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", re.I)
_ARXIV_ID_RE = re.compile(r"\b([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?\b")
_HF_PAPERS_ARXIV_RE = re.compile(r"https?://(?:www\.)?huggingface\.co/papers/([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?", re.I)
_OPENREVIEW_FORUM_RE = re.compile(r"https?://(?:www\.)?openreview\.net/forum\?id=([A-Za-z0-9_-]+)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_URL_RE = re.compile(r"(https?://\S+)")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_DATE_LINE_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}\]\s*$")
_ARXIV_PAREN_RE = re.compile(r"\(\s*arxiv\s*:\s*([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?\s*\)\.?\s*$", re.I)


def _canonicalize_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip()

    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    # Keep query (OpenReview uses it for ids), drop fragment.
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def stable_item_id(url: str, title: str = "") -> tuple[str, dict[str, Any]]:
    """
    Return (stable_id, extra_fields) from the best available stable identifier.
    """
    url_c = _canonicalize_url(url)
    extra: dict[str, Any] = {"canonical_url": url_c}

    # Helpful extras for downstream inspection.
    try:
        parsed = urlparse(url_c)
        if "huggingface.co" in (parsed.netloc or "").lower() and parsed.path.startswith("/papers/"):
            extra["hf_slug"] = parsed.path.split("/papers/", 1)[1].strip("/")
    except Exception:
        pass

    arxiv_id = extract_arxiv_id(url_c) or extract_arxiv_id(title)
    if arxiv_id:
        extra["arxiv_id"] = arxiv_id
        return f"arxiv:{arxiv_id}", extra

    forum_id = extract_openreview_forum_id(url_c)
    if forum_id:
        extra["openreview_forum"] = forum_id
        return f"openreview:{forum_id}", extra

    return f"url:{_sha1(url_c)}", extra


def extract_arxiv_id(text_or_url: str) -> Optional[str]:
    if not text_or_url:
        return None
    m = _ARXIV_URL_RE.search(text_or_url) or _HF_PAPERS_ARXIV_RE.search(text_or_url)
    if m:
        return m.group(1)
    m2 = _ARXIV_ID_RE.search(text_or_url)
    return m2.group(1) if m2 else None


def extract_openreview_forum_id(url: str) -> Optional[str]:
    if not url:
        return None
    m = _OPENREVIEW_FORUM_RE.search(url)
    return m.group(1) if m else None


def _source_label_from_url(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if "arxiv.org" in host:
        parsed = urlparse(url)
        m = re.match(r"^/list/([^/]+)/new/?$", parsed.path or "")
        if m:
            return f"arXiv {m.group(1)}/new"
        return "arXiv"
    if "huggingface.co" in host:
        parsed = urlparse(url)
        if (parsed.path or "").startswith("/papers"):
            return "Hugging Face Papers"
        return "Hugging Face"
    if "openreview.net" in host:
        parsed = urlparse(url)
        if (parsed.path or "") == "/group":
            # e.g. ICLR.cc/2026/Conference -> "OpenReview ICLR 2026"
            q = parsed.query or ""
            m = re.search(r"(?:^|&)id=([^&]+)", q)
            if m:
                group_id = m.group(1)
                m2 = re.search(r"([A-Za-z]+)\.cc/(\d{4})", group_id)
                if m2:
                    return f"OpenReview {m2.group(1).upper()} {m2.group(2)}"
        return "OpenReview"
    if "openai.com" in host:
        return "OpenAI"
    if "deepmind" in host:
        return "DeepMind"
    if "anthropic" in host:
        return "Anthropic"
    if host:
        return host
    return url


def load_source_labels_csv(path: Path) -> dict[str, str]:
    """
    Optional helper: map URL -> human label using a CSV with columns `url` and
    optionally `name`.
    """
    if not path.exists():
        return {}

    by_url: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row:
                continue
            url = (row.get("url") or "").strip()
            name = (row.get("name") or "").strip()
            if url:
                by_url[_canonicalize_url(url)] = name or _source_label_from_url(url)
    return by_url


def _dedupe_merge(items: Iterable[DigestItem]) -> dict[str, DigestItem]:
    merged: dict[str, DigestItem] = {}
    for item in items:
        if item.id not in merged:
            merged[item.id] = item
            continue

        existing = merged[item.id]
        existing_urls = set(existing.extra.get("urls", [existing.url]))
        existing_sources = set(existing.extra.get("sources", [existing.source]))

        existing_urls.add(item.url)
        existing_sources.add(item.source)

        existing.extra["urls"] = sorted(existing_urls)
        existing.extra["sources"] = sorted(existing_sources)
        existing.source = " | ".join(sorted(existing_sources))

        if len(item.title.strip()) > len(existing.title.strip()):
            existing.title = item.title
        if len(item.why.strip()) > len(existing.why.strip()):
            existing.why = item.why

        existing.tags = sorted(set(existing.tags).union(item.tags))
        existing.score = max(existing.score, item.score)
        if not existing.published_at and item.published_at:
            existing.published_at = item.published_at

        existing.extra.update({k: v for k, v in item.extra.items() if k not in existing.extra})
    return merged


def assign_tags(text: str) -> list[str]:
    t = (text or "").lower()
    tags: list[str] = []
    for tag, patterns in TAG_PATTERNS:
        if any(p in t for p in patterns):
            tags.append(tag)

    # Ensure 2–4 tags.
    if "Paper" not in tags and len(tags) < 2:
        tags.append("Paper")
    if len(tags) < 2:
        tags.append("Research")

    # Prefer deterministic order, cap at 4.
    return tags[:4]


def score_item(
    *,
    title: str,
    why: str,
    url: str,
    source: str,
    extra: dict[str, Any],
) -> float:
    text = f"{title}\n{why}\n{source}\n{url}".lower()
    score = 0.05

    if "huggingface.co/papers" in url.lower() or "hugging face" in source.lower():
        score += 0.25

    if any(k in text for k in ["benchmark", "leaderboard", "eval", "evaluation", "dataset"]):
        score += 0.20

    if any(k in text for k in ["moe", "quantization", "distillation", "inference", "streaming", "latency"]):
        score += 0.15

    if any(lab in text for lab in LAB_KEYWORDS):
        score += 0.20

    sources = extra.get("sources") or []
    if isinstance(sources, list) and len(set(sources)) > 1:
        score += 0.10

    if extra.get("arxiv_categories") and isinstance(extra["arxiv_categories"], list) and len(extra["arxiv_categories"]) > 1:
        score += 0.05

    return max(0.0, min(1.0, score))


def _looks_like_no_change(text: str) -> bool:
    t = (text or "").lower()
    return any(
        phrase in t
        for phrase in [
            "no new significant",
            "no significant submissions",
            "no major updates",
            "no notable updates",
            "no changes detected",
        ]
    )


def parse_legacy_summary(summary_md: str) -> tuple[list[dict[str, Any]], dict[str, StatusLine]]:
    """
    Heuristic parser for the old Grok-generated markdown blob grouped by source.
    Returns (raw_items, status_by_source_label).
    """
    if not summary_md:
        return [], {}

    raw_items: list[dict[str, Any]] = []
    status_by_source: dict[str, StatusLine] = {}

    def _strip_bullet_prefix(text: str) -> str:
        return re.sub(r"^[-*•]\s+", "", text.strip())

    current_source = "Unknown"
    for line in summary_md.splitlines():
        s = line.strip()
        if not s:
            continue

        if _DATE_LINE_RE.match(s):
            continue

        m_heading = _MD_HEADING_RE.match(s)
        if m_heading:
            current_source = m_heading.group(2).strip()
            status_by_source.setdefault(
                current_source, StatusLine(source=current_source, changed=True)
            )
            continue

        m_source = re.match(r"^\*\*([^*]+)\*\*\s*(?:—|-|:)?\s*(.*)$", s)
        if m_source:
            current_source = m_source.group(1).strip()
            rest = (m_source.group(2) or "").strip()
            if rest and _looks_like_no_change(rest):
                status_by_source[current_source] = StatusLine(
                    source=current_source, changed=False, note=rest
                )
            else:
                status_by_source.setdefault(
                    current_source, StatusLine(source=current_source, changed=True)
                )
            continue

        if _looks_like_no_change(s):
            status_by_source[current_source] = StatusLine(
                source=current_source, changed=False, note=s
            )
            continue

        is_bullet = s.startswith(("-", "*", "•"))
        if not is_bullet:
            continue

        # Prefer Markdown links.
        m = _MD_LINK_RE.search(s)
        if m:
            title = m.group(1).strip()
            url = m.group(2).strip()
            why = s[m.end() :].strip(" -—:\t")
            raw_items.append(
                {"title": title, "url": url, "why": why, "source": current_source}
            )
            continue

        # Fall back to bare URL extraction.
        m2 = _URL_RE.search(s)
        if m2:
            url = m2.group(1).rstrip(").,;")
            before = _strip_bullet_prefix(s[: m2.start()])
            after = s[m2.end() :].strip(" -—:\t")
            title = before or url
            why = after
            raw_items.append(
                {"title": title, "url": url, "why": why, "source": current_source}
            )
            continue

        # Fall back to arXiv IDs mentioned inline, e.g. "(arXiv:2603.02214)".
        arxiv_id = extract_arxiv_id(s)
        if arxiv_id:
            url = f"https://arxiv.org/abs/{arxiv_id}"
            content = _strip_bullet_prefix(s)

            # Prefer "**Title**: rest" (handles titles that contain ':').
            m_bold = re.match(r"^\*\*(.+?)\*\*\s*:\s*(.*)$", content)
            if m_bold:
                title = m_bold.group(1).strip()
                why = (m_bold.group(2) or "").strip()
            else:
                # Fallback: Title is usually before ":" or "—".
                title_part, sep, rest = content.partition(":")
                if not sep:
                    title_part, sep, rest = content.partition("—")
                title = title_part.replace("**", "").strip()
                why = (rest or "").strip()

            # Remove trailing "(arXiv:xxxx.xxxxx)" noise.
            why = _ARXIV_PAREN_RE.sub("", why).strip()
            if not why:
                why = re.sub(r"\s+", " ", _ARXIV_PAREN_RE.sub("", content)).strip()

            raw_items.append(
                {"title": title or f"arXiv:{arxiv_id}", "url": url, "why": why, "source": current_source}
            )
            continue

    return raw_items, status_by_source


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _select_record_for_date(raw: Any, date: str) -> dict[str, Any]:
    if isinstance(raw, dict) and "summaries" in raw and isinstance(raw["summaries"], list):
        matches = [x for x in raw["summaries"] if isinstance(x, dict) and x.get("date") == date]
        if not matches:
            raise ValueError(f"No entry with date={date!r} found in memory file.")
        if len(matches) > 1:
            logger.warning("Found %d entries for %s; selecting the most informative.", len(matches), date)

            def _item_count(rec: dict[str, Any]) -> int:
                if isinstance(rec.get("items"), list):
                    return sum(1 for it in rec["items"] if isinstance(it, dict) and it.get("url"))
                summary = str(rec.get("summary") or "")
                items, _ = parse_legacy_summary(summary)
                return len(items)

            def _summary_len(rec: dict[str, Any]) -> int:
                return len(str(rec.get("summary") or ""))

            best = None
            best_key = None
            for idx, rec in enumerate(matches):
                key = (_item_count(rec), _summary_len(rec), idx)
                if best_key is None or key > best_key:
                    best_key = key
                    best = rec
            return best or matches[-1]
        return matches[-1]

    if isinstance(raw, dict) and raw.get("date"):
        return raw

    raise ValueError("Unsupported input JSON format. Expected {date,...} or {summaries:[...]}.")


def build_digest_from_raw(
    *,
    date: str,
    raw_record: dict[str, Any],
    top_n: int = 10,
    source_labels: Optional[dict[str, str]] = None,
) -> DailyDigest:
    source_labels = source_labels or {}

    sources: list[str] = []
    if isinstance(raw_record.get("sources"), list):
        sources = [str(x) for x in raw_record["sources"] if x]
    elif isinstance(raw_record.get("scraped_content"), dict):
        sources = [str(x) for x in raw_record["scraped_content"].keys()]

    # Prefer structured items if present; otherwise parse legacy markdown summary.
    raw_items: list[dict[str, Any]] = []
    status: list[StatusLine] = []

    if isinstance(raw_record.get("status"), list):
        for st in raw_record["status"]:
            if isinstance(st, dict) and "source" in st and "changed" in st:
                status.append(
                    StatusLine(
                        source=str(st["source"]),
                        changed=bool(st["changed"]),
                        note=str(st["note"]) if st.get("note") else None,
                    )
                )

    if isinstance(raw_record.get("items"), list):
        for it in raw_record["items"]:
            if isinstance(it, dict) and it.get("url"):
                raw_items.append(it)

    if not raw_items:
        legacy_items, status_by_source = parse_legacy_summary(str(raw_record.get("summary") or ""))
        raw_items = legacy_items
        if not status:
            status = list(status_by_source.values())

    # If still no status, generate default per source URL.
    if not status and sources:
        for url in sources:
            label = source_labels.get(_canonicalize_url(url)) or _source_label_from_url(url)
            status.append(StatusLine(source=label, changed=True))

    # Normalize items into DigestItems.
    digest_items: list[DigestItem] = []
    for it in raw_items:
        url = str(it.get("url") or "").strip()
        if not url:
            continue

        title = str(it.get("title") or "").strip() or url
        why = str(it.get("why") or "").strip()
        src = str(it.get("source") or "").strip()
        if not src and sources:
            src = _source_label_from_url(url)
        if not src:
            src = "Unknown"

        item_id, extra = stable_item_id(url, title=title)
        extra.update({k: v for k, v in (it.get("extra") or {}).items() if isinstance(k, str)})

        # Track multi-source provenance for dedupe.
        extra.setdefault("sources", [])
        if isinstance(extra["sources"], list):
            extra["sources"].append(src)

        extra.setdefault("urls", [])
        if isinstance(extra["urls"], list):
            extra["urls"].append(url)

        tags = it.get("tags")
        if isinstance(tags, list) and tags:
            tags_list = [str(t) for t in tags if t]
        else:
            tags_list = assign_tags(f"{title}\n{why}\n{src}")

        score = it.get("score")
        if isinstance(score, (int, float)):
            score_f = float(score)
        else:
            score_f = score_item(title=title, why=why, url=url, source=src, extra=extra)

        published_at = it.get("published_at")
        published_at_s = str(published_at) if published_at else None

        digest_items.append(
            DigestItem(
                id=item_id,
                title=title,
                url=url,
                why=why or "Worth a closer look based on today’s sources.",
                tags=tags_list,
                source=src,
                score=max(0.0, min(1.0, score_f)),
                published_at=published_at_s,
                extra=extra,
            )
        )

    merged_items = _dedupe_merge(digest_items)

    # Recompute score/tags post-merge (now that we know multi-source info).
    for item in merged_items.values():
        item.score = score_item(
            title=item.title, why=item.why, url=item.url, source=item.source, extra=item.extra
        )
        item.tags = assign_tags(f"{item.title}\n{item.why}\n{item.source}")

    ranked_ids = sorted(
        merged_items.keys(),
        key=lambda item_id: (-merged_items[item_id].score, merged_items[item_id].title.lower()),
    )
    top_ids = ranked_ids[: max(0, int(top_n))]

    # Brief bullets: derive from top items.
    brief: list[BriefBullet] = []
    for item_id in top_ids[:5]:
        item = merged_items[item_id]
        text = f"{item.title} — {item.why}"
        brief.append(BriefBullet(text=text, links=[item.url]))

    # Theme sections (can overlap with Top papers; items stay deduped in `items`).
    def _ranked_filter(predicate) -> list[str]:
        return [item_id for item_id in ranked_ids if predicate(merged_items[item_id])]

    sections_map: dict[str, list[str]] = {
        "Top papers": list(top_ids),
        "Benchmarks & datasets": _ranked_filter(
            lambda it: ("Benchmark" in set(it.tags)) or ("Dataset" in set(it.tags))
        ),
        "Safety & reliability": _ranked_filter(lambda it: "Safety" in set(it.tags)),
        "Robotics & embodied AI": _ranked_filter(lambda it: "Robotics" in set(it.tags)),
        "Lab releases": _ranked_filter(
            lambda it: any(lab in it.source.lower() for lab in LAB_KEYWORDS)
        ),
    }

    sections = [DigestSection(title=t, items=sections_map.get(t, [])) for t in SECTION_TITLES]

    # If we have a list of checked URLs, make sure each has *some* status line,
    # but do not overwrite richer, parsed status labels (e.g. "OpenReview ICLR 2026").
    if sources:
        url_labels = [
            source_labels.get(_canonicalize_url(u)) or _source_label_from_url(u) for u in sources
        ]

        def _status_matches(label: str, st: StatusLine) -> bool:
            a = label.lower()
            b = (st.source or "").lower()
            return a == b or (a and a in b) or (b and b in a)

        for label in url_labels:
            if any(_status_matches(label, st) for st in status):
                continue
            status.append(StatusLine(source=label, changed=True))

    return DailyDigest(
        date=date,
        brief=brief,
        sections=sections,
        items=merged_items,
        status=status,
        sources=sources,
    )


def build_digest(
    *,
    date: str,
    input_path: Path,
    out_dir: Path,
    top_n: int = 10,
    sources_csv: Optional[Path] = None,
    force: bool = False,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}.json"
    if out_path.exists() and not force:
        raise FileExistsError(f"Digest already exists for {date}: {out_path}")

    raw = _load_json(input_path)
    raw_record = _select_record_for_date(raw, date)
    rec_date = str(raw_record.get("date") or "")
    if rec_date and rec_date != date:
        logger.warning("Input record date is %s but --date is %s; continuing with --date.", rec_date, date)

    source_labels = load_source_labels_csv(sources_csv) if sources_csv else {}
    digest = build_digest_from_raw(date=date, raw_record=raw_record, top_n=top_n, source_labels=source_labels)

    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(digest.to_dict(), fh, ensure_ascii=False, indent=2)

    logger.info("Wrote digest JSON: %s", out_path)
    return out_path
