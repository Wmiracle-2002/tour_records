"""Canonical selectable cities for account-owned travel notes."""

import json
import logging
import re
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.observability import current_request_id
from app.models import KnowledgeEntry
from app.agent.utils import NON_SPICY_FOOD_TERMS, NON_SPICY_QUERY_TERMS, SPICY_FOOD_TERMS, non_spicy_required

if TYPE_CHECKING:
    from app.agent.models import TravelRequirement


logger = logging.getLogger("footmarks.agent.knowledge")

_TOPIC_ALIASES = {
    "历史文化": ("历史文化", "博物馆", "博物院", "古建筑", "历史街区"),
    "自然风光": ("自然风光", "山水", "湖泊", "森林", "自然景观"),
}


@dataclass(frozen=True)
class KnowledgeQuery:
    required_terms: tuple[str, ...] = ()
    preferred_topics: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    non_spicy: bool = False
    preferred_districts: tuple[str, ...] = ()
    required_districts: tuple[str, ...] = ()
    excluded_districts: tuple[str, ...] = ()


def _district_condition(text: str, city_code: str) -> tuple[str, str] | None:
    """Recognize a district prefix within the already resolved city."""
    city = selectable_cities()[city_code]
    for code, name in city_districts().get(city_code, {}).items():
        short = name.removesuffix("区").removesuffix("县").removesuffix("市")
        aliases = {prefix + suffix for prefix in ("", city, city.removesuffix("市"))
                   for suffix in (name, short)}
        for alias in sorted(aliases, key=len, reverse=True):
            if text == alias:
                return code, ""
            if text.startswith(alias):
                rest = text[len(alias):]
                if re.match(r"^(?:的|范围内|以内|内|以外|之外)", rest):
                    return code, rest
    return None


def knowledge_query(requirement: "TravelRequirement") -> KnowledgeQuery:
    """Separate supported search conditions without another model call."""
    required, preferred, excluded = [], [], []
    scope = resolve_knowledge_scope(requirement.city or "")
    preferred_districts = [scope[1]] if scope and scope[1] else []
    required_districts, excluded_districts = [], []
    non_spicy = non_spicy_required(requirement)
    for hard, values in ((False, requirement.preferences), (True, requirement.constraints)):
        for value in values:
            for text in re.split(r"[，,；;]", value):
                text = text.strip(" 。")
                if not text or re.fullmatch(
                    r"(?:可以|请|希望)?(?:参考|结合|使用|优先参考)(?:我(?:的)?|个人)?(?:收藏|保存)(?:的)?(?:旅行攻略|攻略|笔记|内容)?", text,
                ):
                    continue
                include = re.match(r"^(?:必须(?:同时)?(?:包含|有)|只(?:要|推荐|看|在)|仅(?:推荐|限))\s*(.+)$", text)
                reject = re.match(r"^(?:不想去|不去|不要|排除|避开)\s*(.+)$", text)
                if scope and scope[1] and text in {"不要其他区", "不去其他区", "不考虑其他区"}:
                    required_districts.append(scope[1])
                    continue
                region_text = (include or reject)[1] if include or reject else re.sub(
                    r"^(?:最好(?:在|是)?|优先(?:考虑)?|希望在|尽量在|偏好|喜欢)\s*", "", text,
                )
                district = _district_condition(region_text, scope[0]) if scope else None
                if district:
                    code, rest = district
                    if rest.startswith(("以外", "之外")):
                        target_districts = required_districts if reject else excluded_districts
                        target_districts.append(code)
                        rest = rest[2:]
                    elif reject:
                        excluded_districts.append(code)
                    elif include:
                        required_districts.append(code)
                    else:
                        preferred_districts.append(code)
                    rest = re.sub(r"^(?:范围内|以内|内)?的?", "", rest)
                    if rest in {"", "内容", "笔记", "攻略", "旅游攻略", "旅行攻略"}:
                        continue
                    # Keep mixed geographic/content conditions conjunctive.
                    category = re.search(r"(景点|美食|餐厅)$", rest)
                    values = [rest[:category.start()], category[0]] if category else [rest]
                    target = excluded if reject else required if include else preferred
                    target.extend(term.strip() for value in values for term in re.split(r"[、]|和|及", value) if term.strip())
                    continue
                if include:
                    required.extend(term.strip() for term in re.split(r"[、]|和|及", include[1]) if term.strip())
                elif non_spicy and (text in NON_SPICY_QUERY_TERMS or "辣" in text):
                    continue  # Dietary evidence is checked only for food sections.
                elif reject:
                    excluded.extend(term.strip() for term in re.split(r"[、]|和|及", reject[1]) if term.strip())
                elif not hard:
                    topic = re.sub(r"^(?:我(?:们)?(?:比较)?|比较)?(?:喜欢|偏好|倾向于|想体验|想了解)\s*", "", text)
                    if topic:
                        preferred.append(topic.casefold())
                else:
                    required.append(text)
    return KnowledgeQuery(tuple(dict.fromkeys(required)), tuple(dict.fromkeys(preferred)),
                          tuple(dict.fromkeys(excluded)), non_spicy,
                          tuple(dict.fromkeys(preferred_districts)), tuple(dict.fromkeys(required_districts)),
                          tuple(dict.fromkeys(excluded_districts)))


def _positive_positions(text: str, term: str) -> list[int]:
    """Do not count an explicit negative mention as evidence for a term."""
    positions = []
    for clause in re.finditer(r"[^，,。；;！？!?\n]+", text):
        for match in re.finditer(re.escape(term), clause[0], re.IGNORECASE):
            before, after = clause[0][:match.start()], clause[0][match.end():]
            if re.search(r"(?:不是|并非|不推荐|不要|不放|不加|不想去|不去|别去|避雷|不保证|不能保证|不能做|无法确认).{0,4}$|不$", before):
                continue
            if re.match(r"\s*(?:不推荐|不适合|别去|不要去)", after):
                continue
            positions.append(clause.start() + match.start())
    return positions


def _term_score(term: str, text: str, title: str, tags: list[str]) -> int:
    dietary = term in NON_SPICY_QUERY_TERMS
    if dietary and any(_positive_positions(title + "。" + text, word) for word in SPICY_FOOD_TERMS):
        return 0
    scores = []
    for word in NON_SPICY_FOOD_TERMS if dietary else (term,):
        metadata = (3 if _positive_positions(title, word) else 0) + (2 if any(word in tag.casefold() for tag in tags) else 0)
        if _positive_positions(text, word):
            scores.append(metadata + 1)
        elif word not in text.casefold():
            scores.append(metadata)
        # A title/tag cannot override an explicit negative body mention.
    return max(scores, default=0)


def _excluded_section(text: str, title: str, category: str, query: KnowledgeQuery) -> bool:
    for term in query.excluded_terms:
        if term == "寺庙":
            if category == "food_guide":
                continue
            terms = ["寺庙", "寺院", *re.findall(r"[\u4e00-\u9fff]{1,10}寺", title + text)]
        else:
            terms = [term]
        if any(_positive_positions(title + "。" + text, word) for word in terms):
            return True
    if query.non_spicy and category == "food_guide":
        supported = any(_positive_positions(text, word) for word in NON_SPICY_FOOD_TERMS)
        spicy = any(_positive_positions(title + "。" + text, word) for word in SPICY_FOOD_TERMS)
        return not supported or spicy
    return False


def _excerpt(text: str, terms: list[str], limit: int, category: str) -> tuple[str, int]:
    terms = [word for term in terms for word in (NON_SPICY_FOOD_TERMS if term in NON_SPICY_QUERY_TERMS else (term,))]
    positions = sorted(position for term in terms for position in _positive_positions(text, term))
    if not positions and category == "food_guide":
        positions = sorted(position for term in ("餐食", "早餐", "午餐", "晚餐", "小吃", "推荐")
                           for position in _positive_positions(text, term))
    starts = {max(0, min(position - 40, len(text) - limit)) for position in positions}
    start = max(starts, key=lambda offset: (
        bisect_left(positions, offset + limit) - bisect_left(positions, offset), -offset,
    )) if starts else 0
    return text[start:start + limit], start


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
    district_name: str | None = None


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
    query: KnowledgeQuery | None = None,
) -> list[KnowledgeExcerpt]:
    if city_code not in selectable_cities():
        return []
    query = query or KnowledgeQuery()
    terms = [term.strip().casefold() for term in [*(keywords or []), *query.required_terms] if term.strip()]
    statement = select(KnowledgeEntry).where(
        KnowledgeEntry.user_id == user_id, KnowledgeEntry.city_code == city_code,
    )
    if district_code and district_code not in city_districts().get(city_code, {}):
        return []
    candidates = db.scalars(statement.order_by(KnowledgeEntry.id.desc())).yield_per(100)

    def score(entry: KnowledgeEntry, text: str, section_category: str) -> int:
        # Whole-note metadata cannot supply evidence for a different section.
        scores = [
            int(section_category == {"景点": "attraction_guide", "美食": "food_guide", "餐厅": "food_guide"}[term])
            if term in {"景点", "美食", "餐厅"} else
            _term_score(term, text, entry.title if not entry.sections else "", entry.tags if not entry.sections else [])
            for term in terms
        ]
        if scores and not all(scores):
            return 0
        preferred = sum(max(_term_score(alias, text, entry.title if not entry.sections else "",
                                       entry.tags if not entry.sections else [])
                            for alias in _TOPIC_ALIASES.get(topic, (topic,)))
                        for topic in query.preferred_topics)
        return sum(scores) + preferred

    matches = []
    for entry in candidates:
        entry_matches = []
        sections = entry.sections or [{"text": entry.body, "district_code": None, "category": entry.category}]
        for section in sections:
            if section.get("district_code") and section["district_code"] not in city_districts().get(city_code, {}):
                continue
            if district_code and section.get("district_code") != district_code:
                continue
            section_district = section.get("district_code")
            if any(section_district != code for code in query.required_districts):
                continue
            if query.excluded_districts and (not section_district or section_district in query.excluded_districts):
                continue
            if category and (section.get("category") or entry.category) != category:
                continue
            text = section["text"]
            if text not in entry.body:
                continue
            section_category = section.get("category") or entry.category
            if _excluded_section(text, entry.title if not entry.sections else "", section_category, query):
                continue
            value = score(entry, text, section_category)
            if terms and value == 0:
                continue
            entry_matches.append((int(section_district in query.preferred_districts), value, entry, section))
        if any(item[0] for item in entry_matches):
            entry_matches = [item for item in entry_matches if item[0]]
        matches.extend(entry_matches)
        matches.sort(key=lambda item: (item[0], item[1], item[2].id), reverse=True)
        del matches[5:]
    selected = matches[:5]
    logger.info(
        "Knowledge search request_id=%s user_id=%s city_code=%s district_code=%s required=%s preferred=%s excluded=%s non_spicy=%s preferred_districts=%s required_districts=%s excluded_districts=%s count=%s ids=%s",
        current_request_id() or "unknown", user_id, city_code, district_code,
        terms, query.preferred_topics, query.excluded_terms, query.non_spicy,
        query.preferred_districts, query.required_districts, query.excluded_districts,
        len(selected), [entry.id for _, _, entry, _ in selected],
    )
    remaining = 800
    result: list[KnowledgeExcerpt] = []
    for _, _, entry, section in selected:
        if remaining <= 0:
            break
        topic_terms = [alias for topic in query.preferred_topics for alias in _TOPIC_ALIASES.get(topic, (topic,))]
        section_category = section.get("category") or entry.category
        excerpt_terms = list(NON_SPICY_FOOD_TERMS) if query.non_spicy and section_category == "food_guide" else terms + topic_terms
        excerpt, offset = _excerpt(section["text"], excerpt_terms, min(240, remaining), section_category)
        remaining -= len(excerpt)
        result.append(KnowledgeExcerpt(
            id=entry.id, title=entry.title, category=section.get("category") or entry.category,
            city_code=entry.city_code, tags=tuple(entry.tags),
            excerpt=excerpt, updated_at=entry.updated_at.isoformat(),
            district_code=section.get("district_code"), source_start=entry.body.index(section["text"]) + offset,
            district_name=city_districts().get(city_code, {}).get(section.get("district_code")),
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
