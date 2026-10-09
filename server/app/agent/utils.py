"""Shared pure helpers used by multiple Agent modules."""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.models import KnowledgeInfo, POIInfo, TravelRequirement


_PREVIOUS_PLACE_KEYWORDS = ("以前", "之前", "曾经", "去过", "visited", "previous")


def avoids_previous_places(constraints: list[str]) -> bool:
    """Return whether constraints ask to avoid places visited before."""
    normalized = " ".join(constraints).lower()
    return any(keyword in normalized for keyword in _PREVIOUS_PLACE_KEYWORDS)


def is_food_category(category: str | None) -> bool:
    normalized = (category or "").lower()
    return any(word in normalized for word in ("餐饮", "美食", "food"))


def excluded_periods(requirement: TravelRequirement) -> set[str]:
    """Explicit exclusions and period-only requests override default coverage."""
    labels = {
        "breakfast": "早餐|早饭", "lunch": "午餐|午饭", "dinner": "晚餐|晚饭",
        "morning": "上午", "afternoon": "下午", "evening": "晚上|晚间|夜间",
    }
    words = "(?:" + "|".join(labels.values()) + ")"
    excluded: set[str] = set()
    for text in requirement.preferences + requirement.constraints:
        for match in re.finditer(
            rf"(?<!不)(?:只|仅)(?:安排|游玩|游览)\s*((?:{words}(?:和|与|及|[、/\s])*)+)", text,
        ):
            excluded.update(period for period, aliases in labels.items()
                            if not re.search(aliases, match.group(1)))
        for period, aliases in labels.items():
            if re.search(
                rf"(?:不(?:要|用|想)?(?:安排|推荐|吃)?|无需(?:安排)?|取消|跳过)\s*(?:{aliases})"
                rf"|(?:{aliases})\s*(?:休息|不(?:要|用)?安排(?:景点|活动|行程)?(?=$|[，,。；;\s]))", text,
            ):
                excluded.add(period)
    return excluded


def non_spicy_required(requirement: TravelRequirement) -> bool:
    text = " ".join(requirement.preferences + requirement.constraints)
    return any(word in text for word in ("不吃辣", "不能吃辣", "不要辣", "不辣", "忌辣"))


def food_conflicts(name: str, requirement: TravelRequirement) -> bool:
    """Exclude explicitly spicy labels; absence of these labels is not safety proof."""
    return non_spicy_required(requirement) and any(
        word in name for word in ("麻辣", "香辣", "酸辣", "辣椒", "剁椒")
    )


def poi_conflicts(poi: POIInfo, requirement: TravelRequirement) -> bool:
    text = " ".join(requirement.constraints + requirement.preferences)
    avoid_temples = any(word in text for word in ("不去寺庙", "不要寺庙", "排除寺庙", "不想去寺庙"))
    return (is_food_category(poi.category) and food_conflicts(poi.name, requirement)) or (
        avoid_temples and (poi.name.endswith("寺") or "寺庙" in (poi.category or ""))
    )


def unique_attractions_required(requirement: TravelRequirement) -> bool:
    return any(word in " ".join(requirement.constraints + requirement.preferences)
               for word in ("不重复", "不要重复", "不重样"))


def meal_matches(name: str, period: str) -> bool:
    """Respect explicit meal labels, without inventing business hours."""
    labels = {"breakfast": ("早餐", "早饭", "早点", "早午餐"),
              "lunch": ("午餐", "午饭"), "dinner": ("晚餐", "晚饭", "夜宵")}
    mentioned = {key for key, words in labels.items() if any(word in name for word in words)}
    return not mentioned or period in mentioned


def stale_note(note: KnowledgeInfo) -> bool:
    return any(word in note.title + note.excerpt for word in ("过时", "已失效", "已过期", "旧笔记", "旧景点票价"))


def note_supports_food(note: KnowledgeInfo, name: str, period: str | None = None) -> bool:
    """Use positive mentions in bounded excerpts, never instructions or stale claims."""
    if stale_note(note) or len(name) < 2:
        return False
    label = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}.get(period)
    mentions = [name] + [tag for tag in note.tags if len(tag) >= 2 and tag in name]
    for sentence in re.split(r"[。；;\n]", note.excerpt):
        if not any(mention in sentence for mention in mentions) or any(word in sentence for word in ("不推荐", "不要", "避雷", "不适合", "别去")):
            continue
        if any(word in sentence for word in ("推荐", "值得尝试", "适合", "可以吃", "优先选择")) and (label is None or label in sentence):
            return True
    return False


def meal_candidates(pois: list[POIInfo], requirement: TravelRequirement,
                    notes: list[KnowledgeInfo], period: str) -> list[POIInfo]:
    candidates = [poi for poi in pois if is_food_category(poi.category)
                  and meal_matches(poi.name, period) and not food_conflicts(poi.name, requirement)]
    return sorted(candidates, key=lambda poi: any(
        note_supports_food(note, poi.name, period) for note in notes
    ), reverse=True)


def dietary_notice(requirement: TravelRequirement) -> str | None:
    if non_spicy_required(requirement):
        return ("忌口筛选依据：按“不吃辣”排除名称明确含麻辣、香辣、酸辣、辣椒或剁椒的候选；"
                "其余仅为待核实餐饮候选，高德地点信息无法确认实际菜品辣度或过敏原。"
                "请点餐时向商家确认不放辣及交叉接触风险；收藏笔记仅作个人经验参考，不能证明安全。")
    return None


def time_to_minutes(value: str) -> int:
    """Convert an exact HH:MM value to minutes after midnight."""
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError(f"invalid date or time format: {value}")
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError(f"invalid date or time format: {value}")
    return hour * 60 + minute
