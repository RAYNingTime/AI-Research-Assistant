from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .schema import DigestItem

logger = logging.getLogger(__name__)


def _load_digest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "date" not in data:
        raise ValueError(f"Not a digest JSON file: {path}")
    return data


def _md_escape(text: str) -> str:
    return (text or "").replace("\n", " ").strip()


def _render_item_md(item: DigestItem) -> str:
    tags = ", ".join(f"`{t}`" for t in item.tags)
    lines = [
        f"[{_md_escape(item.title)}]({item.url})",
        f"  - Why it matters: {_md_escape(item.why)}",
        f"  - Tags: {tags}",
        f"  - Source: {_md_escape(item.source)}",
    ]
    return "\n".join(lines)


def render_markdown(
    *,
    date: str,
    in_dir: Path,
    out_dir: Path,
) -> Path:
    in_path = in_dir / f"{date}.json"
    if not in_path.exists():
        raise FileNotFoundError(f"Digest JSON not found: {in_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}.md"

    digest_data = _load_digest(in_path)

    # Minimal in-place parsing (keep schema dependency light).
    items: dict[str, DigestItem] = {}
    for item_id, it in (digest_data.get("items") or {}).items():
        if not isinstance(it, dict):
            continue
        items[item_id] = DigestItem(
            id=str(it.get("id") or item_id),
            title=str(it.get("title") or ""),
            url=str(it.get("url") or ""),
            why=str(it.get("why") or ""),
            tags=[str(t) for t in (it.get("tags") or []) if t],
            source=str(it.get("source") or ""),
            score=float(it.get("score") or 0.0),
            published_at=str(it.get("published_at")) if it.get("published_at") else None,
            extra=dict(it.get("extra") or {}),
        )

    lines: list[str] = []
    lines.append(f"# AI Research Digest — {date}")
    lines.append("")

    # Daily Brief
    lines.append("## Daily Brief")
    brief = digest_data.get("brief") or []
    if brief:
        for b in brief[:5]:
            if not isinstance(b, dict):
                continue
            text = _md_escape(str(b.get("text") or ""))
            links = [str(x) for x in (b.get("links") or []) if x]
            if links:
                rendered_links = ", ".join(f"[link]({u})" for u in links[:3])
                lines.append(f"- {text} ({rendered_links})")
            else:
                lines.append(f"- {text}")
    else:
        lines.append("- (No brief items.)")
    lines.append("")

    # Sections
    for section in digest_data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        ids = [str(x) for x in (section.get("items") or []) if x]
        if not title:
            continue
        lines.append(f"## {title}")
        if not ids:
            lines.append("- (No items.)")
            lines.append("")
            continue

        if title.lower().startswith("top"):
            # Numbered list for Top papers
            n = 1
            for item_id in ids:
                item = items.get(item_id)
                if not item:
                    continue
                rendered = _render_item_md(item).splitlines()
                lines.append(f"{n}. {rendered[0]}")
                for sub in rendered[1:]:
                    lines.append(sub)
                n += 1
            lines.append("")
        else:
            for item_id in ids:
                item = items.get(item_id)
                if not item:
                    continue
                rendered = _render_item_md(item).splitlines()
                lines.append(f"- {rendered[0]}")
                for sub in rendered[1:]:
                    lines.append(sub)
            lines.append("")

    # No changes detected
    lines.append("## No changes detected")
    status = digest_data.get("status") or []
    no_change: list[str] = []
    for st in status:
        if not isinstance(st, dict) or "changed" not in st:
            continue
        if bool(st.get("changed")):
            continue
        source = str(st.get("source") or "").strip()
        note = str(st.get("note") or "").strip()
        if source and note:
            no_change.append(f"- {source} — {note}")
        elif source:
            no_change.append(f"- {source}")
    if no_change:
        lines.extend(no_change)
    else:
        lines.append("- (None.)")
    lines.append("")

    # Sources checked
    lines.append("## Sources checked")
    srcs = [str(u) for u in (digest_data.get("sources") or []) if u]
    if srcs:
        for u in srcs:
            lines.append(f"- {u}")
    else:
        lines.append("- (None.)")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote digest Markdown: %s", out_path)
    return out_path
