"""Explicit, account-level travel preference commands and API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserPreference


PreferenceCategory = Literal[
    "food_restriction",
    "attraction_interest",
    "travel_pace",
    "budget_tendency",
]

PREFERENCE_LABELS = {
    "food_restriction": "饮食偏好/忌口",
    "attraction_interest": "景点兴趣",
    "travel_pace": "旅行节奏",
    "budget_tendency": "预算倾向",
}


class PreferenceUpsert(BaseModel):
    content: str = Field(min_length=1, max_length=240)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be blank")
        return normalized


class PreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: PreferenceCategory
    content: str
    created_at: datetime
    updated_at: datetime


def parse_preference_command(
    message: str,
) -> tuple[Literal["save", "delete"], PreferenceCategory, str] | None:
    text = message.strip()
    action: Literal["save", "delete"]
    if text.startswith(("请记住我", "记住我", "以后记住我", "以后请记住我")):
        action = "save"
        body = _remove_prefix(text, ("以后请记住我", "以后记住我", "请记住我", "记住我"))
    elif text.startswith(("请忘记我", "忘记我")):
        action = "delete"
        body = _remove_prefix(text, ("请忘记我", "忘记我"))
    else:
        return None

    if not body or "这次" in body or any(
        subject in body for subject in ("朋友", "家人", "同事", "孩子", "伴侣")
    ):
        return None
    if body.startswith(("，", ",", "：", ":")):
        body = body[1:].strip()
    if body.startswith("我"):
        body = body[1:].strip()
    body = body.strip(" ，,。.!！")
    matches = _matched_categories(body)
    if len(matches) != 1 or not body or len(body) > 240:
        return None
    return action, matches[0], body


def apply_preference_command(
    db: Session,
    user_id: int,
    message: str,
) -> str | None:
    command = parse_preference_command(message)
    if command is None:
        return None
    action, category, content = command
    row = db.scalar(
        select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.category == category,
        )
    )
    label = PREFERENCE_LABELS[category]
    if action == "save":
        if row is None:
            row = UserPreference(user_id=user_id, category=category, content=content)
            db.add(row)
        else:
            row.content = content
        db.flush()
        return f"已记住你的{label}：{content}。可在个人中心查看、修改或删除。"
    if row is None:
        return f"目前没有保存{label}。"
    if content not in row.content:
        return f"目前保存的{label}是“{row.content}”，没有删除。"
    db.delete(row)
    db.flush()
    return f"已删除保存的{label}。"


def _remove_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return ""


def _matched_categories(text: str) -> list[PreferenceCategory]:
    categories: list[PreferenceCategory] = []
    if any(word in text for word in (
        "饮食", "不吃", "不喝", "忌口", "过敏", "素食", "吃辣", "香菜", "海鲜"
    )):
        categories.append("food_restriction")
    if any(word in text for word in (
        "博物馆", "历史", "古迹", "自然", "景点", "建筑", "文化"
    )):
        categories.append("attraction_interest")
    if any(word in text for word in (
        "慢节奏", "不赶", "悠闲", "节奏", "紧凑", "每天安排"
    )):
        categories.append("travel_pace")
    if any(word in text for word in (
        "预算", "省钱", "经济型", "花费", "宽裕"
    )):
        categories.append("budget_tendency")
    return categories
