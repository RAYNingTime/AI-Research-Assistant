from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True, slots=True)
class BriefBullet:
    text: str
    links: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DigestSection:
    title: str
    items: list[str]


@dataclass(frozen=True, slots=True)
class StatusLine:
    source: str
    changed: bool
    note: Optional[str] = None


@dataclass(slots=True)
class DigestItem:
    id: str
    title: str
    url: str
    why: str
    tags: list[str]
    source: str
    score: float
    published_at: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "why": self.why,
            "tags": list(self.tags),
            "source": self.source,
            "score": float(self.score),
            "extra": dict(self.extra),
        }
        if self.published_at:
            data["published_at"] = self.published_at
        return data


@dataclass(slots=True)
class DailyDigest:
    date: str  # YYYY-MM-DD
    brief: list[BriefBullet]
    sections: list[DigestSection]
    items: dict[str, DigestItem]
    status: list[StatusLine]
    sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "brief": [{"text": b.text, "links": list(b.links)} for b in self.brief],
            "sections": [
                {"title": s.title, "items": list(s.items)} for s in self.sections
            ],
            "items": {item_id: item.to_dict() for item_id, item in self.items.items()},
            "status": [
                {"source": st.source, "changed": bool(st.changed), **({"note": st.note} if st.note else {})}
                for st in self.status
            ],
            "sources": list(self.sources),
        }

