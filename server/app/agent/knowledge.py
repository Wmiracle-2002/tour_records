"""Canonical selectable cities for account-owned travel notes."""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.observability import current_request_id
from app.models import KnowledgeEntry


logger = logging.getLogger("footmarks.agent.knowledge")


@dataclass(frozen=True)
class KnowledgeExcerpt:
    id: int
    title: str
    category: str
    city_code: str
    tags: tuple[str, ...]
    excerpt: str
    updated_at: str


@lru_cache(maxsize=1)
def selectable_cities() -> dict[str, str]:
    source = Path(__file__).with_name("administrative_divisions_2023.json")
    provinces = json.loads(source.read_text(encoding="utf-8"))
    cities: dict[str, str] = {}
    for province in provinces:
        province_code = province["code"].ljust(6, "0")
        for city in province["children"]:
            if province_code in {"110000", "120000", "310000", "500000"}:
                if city["name"] == "市辖区":
                    cities[province_code] = province["name"]
            elif city["name"] in {"省直辖县级行政区划", "自治区直辖县级行政区划"}:
                cities.update({
                    area["code"]: area["name"]
                    for area in city.get("children", []) if area["name"].endswith("市")
                })
            else:
                cities[city["code"].ljust(6, "0")] = city["name"]
    return cities


def resolve_city_code(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.strip().removesuffix("市")
    matches = [
        code for code, label in selectable_cities().items()
        if label.removesuffix("市") == normalized
    ]
    return matches[0] if len(matches) == 1 else None


def search_knowledge(
    db: Session, user_id: int, city_code: str, *,
    category: str | None = None, keywords: list[str] | None = None,
) -> list[KnowledgeExcerpt]:
    if city_code not in selectable_cities():
        return []
    terms = [term.strip().casefold()[:40] for term in (keywords or [])[:4] if term.strip()]
    statement = select(KnowledgeEntry).where(
        KnowledgeEntry.user_id == user_id, KnowledgeEntry.city_code == city_code,
    )
    if category:
        statement = statement.where(KnowledgeEntry.category == category)
    candidates = db.scalars(statement.order_by(KnowledgeEntry.id.desc()).limit(200)).all()

    def score(entry: KnowledgeEntry) -> int:
        return sum(
            (3 if term in entry.title.casefold() else 0)
            + (2 if any(term in tag.casefold() for tag in entry.tags) else 0)
            + (1 if term in entry.body.casefold() else 0)
            for term in terms
        )

    matches = [entry for entry in candidates if not terms or score(entry) > 0]
    matches.sort(key=lambda entry: (score(entry), entry.id), reverse=True)
    selected = matches[:5]
    logger.info(
        "Knowledge search request_id=%s user_id=%s city_code=%s count=%s ids=%s",
        current_request_id() or "unknown", user_id, city_code,
        len(selected), [entry.id for entry in selected],
    )
    remaining = 800
    result: list[KnowledgeExcerpt] = []
    for entry in selected:
        excerpt = entry.body[:min(240, remaining)]
        remaining -= len(excerpt)
        result.append(KnowledgeExcerpt(
            id=entry.id, title=entry.title, category=entry.category,
            city_code=entry.city_code, tags=tuple(entry.tags),
            excerpt=excerpt, updated_at=entry.updated_at.isoformat(),
        ))
    return result


def read_knowledge_excerpt(
    db: Session, user_id: int, entry_id: int, *, offset: int = 0,
) -> str | None:
    if offset < 0 or offset > 8000:
        raise ValueError("offset must be between 0 and 8000")
    entry = db.scalar(select(KnowledgeEntry).where(
        KnowledgeEntry.id == entry_id, KnowledgeEntry.user_id == user_id,
    ))
    if entry is None:
        return None
    return entry.body[offset:offset + 600]
