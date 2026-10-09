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
    district_code: str | None = None
    source_start: int | None = None


@lru_cache(maxsize=1)
def city_districts() -> dict[str, dict[str, str]]:
    """Retain district children without expanding the selectable city list."""
    provinces = json.loads(Path(__file__).with_name("administrative_divisions_2023.json").read_text(encoding="utf-8"))
    result = {}
    for province in provinces:
        for city in province["children"]:
            code = province["code"].ljust(6, "0") if province["code"] in {"11", "12", "31", "50"} else city["code"].ljust(6, "0")
            if code in selectable_cities():
                result.setdefault(code, {}).update({node["code"]: node["name"] for node in city.get("children", [])})
    return result


def resolve_knowledge_scope(name: str) -> tuple[str, str | None] | None:
    city_code = resolve_city_code(name)
    if city_code:
        return city_code, None
    matches = set()
    normalized = name.strip()
    for code, districts in city_districts().items():
        city = selectable_cities()[code]
        for district_code, district in districts.items():
            short = district.removesuffix("区").removesuffix("县").removesuffix("市")
            aliases = {district, short}
            aliases.update(prefix + suffix for prefix in (city, city.removesuffix("市")) for suffix in (district, short))
            if normalized in aliases:
                matches.add((code, district_code))
    return next(iter(matches)) if len(matches) == 1 else None


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
    district_code: str | None = None,
) -> list[KnowledgeExcerpt]:
    if city_code not in selectable_cities():
        return []
    terms = [term.strip().casefold() for term in (keywords or []) if term.strip()]
    statement = select(KnowledgeEntry).where(
        KnowledgeEntry.user_id == user_id, KnowledgeEntry.city_code == city_code,
    )
    if district_code and district_code not in city_districts().get(city_code, {}):
        return []
    candidates = db.scalars(statement.order_by(KnowledgeEntry.id.desc())).yield_per(100)

    def score(entry: KnowledgeEntry, text: str) -> int:
        # Whole-note metadata cannot supply evidence for a different section.
        scores = [
            (3 if not entry.sections and term in entry.title.casefold() else 0)
            + (2 if not entry.sections and any(term in tag.casefold() for tag in entry.tags) else 0)
            + (1 if term in text.casefold() else 0)
            for term in terms
        ]
        return sum(scores) if all(scores) else 0

    matches = []
    for entry in candidates:
        sections = entry.sections or [{"text": entry.body, "district_code": None, "category": entry.category}]
        for section in sections:
            if section.get("district_code") and section["district_code"] not in city_districts().get(city_code, {}):
                continue
            if district_code and section.get("district_code") != district_code:
                continue
            if category and (section.get("category") or entry.category) != category:
                continue
            text = section["text"]
            if text not in entry.body:
                continue
            value = score(entry, text)
            if terms and value == 0:
                continue
            matches.append((value, entry, section))
            matches.sort(key=lambda item: (item[0], item[1].id), reverse=True)
            del matches[5:]
    selected = matches[:5]
    logger.info(
        "Knowledge search request_id=%s user_id=%s city_code=%s count=%s ids=%s",
        current_request_id() or "unknown", user_id, city_code,
        len(selected), [entry.id for _, entry, _ in selected],
    )
    remaining = 800
    result: list[KnowledgeExcerpt] = []
    for _, entry, section in selected:
        if remaining <= 0:
            break
        excerpt = section["text"][:min(240, remaining)]
        remaining -= len(excerpt)
        result.append(KnowledgeExcerpt(
            id=entry.id, title=entry.title, category=section.get("category") or entry.category,
            city_code=entry.city_code, tags=tuple(entry.tags),
            excerpt=excerpt, updated_at=entry.updated_at.isoformat(),
            district_code=section.get("district_code"), source_start=entry.body.index(section["text"]),
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
