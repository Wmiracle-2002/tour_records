"""Authenticated CRUD for personal travel notes and guides."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.knowledge import city_districts, selectable_cities
from app.api.auth import current_user
from app.database import get_db
from app.models import KnowledgeEntry, User


router = APIRouter(prefix="/agent/knowledge", tags=["agent knowledge"])
KnowledgeCategory = Literal["note", "travel_guide", "food_guide", "attraction_guide"]


class KnowledgeSection(BaseModel):
    model_config = {"extra": "forbid"}
    district_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    category: KnowledgeCategory | None = None
    text: str = Field(min_length=1, max_length=8000)


class KnowledgePayload(BaseModel):
    category: KnowledgeCategory
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=8000)
    city_code: str = Field(pattern=r"^\d{6}$")
    city_name: str = Field(min_length=1, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=8)
    source: str | None = Field(default=None, max_length=300)
    sections: list[KnowledgeSection] = Field(default_factory=list, max_length=32)

    @field_validator("title", "body", "city_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("field must not be blank")
        return result

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values: list[str]) -> list[str]:
        tags = [value.strip() for value in values]
        if any(not tag or len(tag) > 24 for tag in tags) or len(set(tags)) != len(tags):
            raise ValueError("tags must be unique nonblank values of at most 24 characters")
        return tags

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def valid_city(self) -> "KnowledgePayload":
        if selectable_cities().get(self.city_code) != self.city_name:
            raise ValueError("city_code and city_name must identify a selectable city")
        ranges = []
        for section in self.sections:
            if section.district_code and section.district_code not in city_districts().get(self.city_code, {}):
                raise ValueError("district_code must belong to the selected city")
            if not section.text.strip() or section.text not in self.body:
                raise ValueError("section text must be a nonblank exact excerpt of body")
            if self.body.count(section.text) != 1:
                raise ValueError("section text must identify one unique source location; include more context")
            start = self.body.index(section.text)
            end = start + len(section.text)
            if any(start < previous_end and previous_start < end for previous_start, previous_end in ranges):
                raise ValueError("sections must not overlap; split each region into its own excerpt")
            ranges.append((start, end))
        return self


class KnowledgePatch(BaseModel):
    category: KnowledgeCategory | None = None
    title: str | None = None
    body: str | None = None
    city_code: str | None = None
    city_name: str | None = None
    tags: list[str] | None = None
    source: str | None = None
    sections: list[KnowledgeSection] | None = None


class KnowledgeOut(KnowledgePayload):
    model_config = {"from_attributes": True}

    id: int
    created_at: datetime
    updated_at: datetime


def _owned_entry(db: Session, user_id: int, entry_id: int) -> KnowledgeEntry:
    entry = db.scalar(select(KnowledgeEntry).where(
        KnowledgeEntry.id == entry_id, KnowledgeEntry.user_id == user_id,
    ))
    if entry is None:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    return entry


@router.post("", response_model=KnowledgeOut, status_code=201)
def create_knowledge(
    payload: KnowledgePayload,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> KnowledgeOut:
    entry = KnowledgeEntry(user_id=user.id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return KnowledgeOut.model_validate(entry)


@router.get("", response_model=list[KnowledgeOut])
def list_knowledge(
    city_code: str | None = None,
    category: KnowledgeCategory | None = None,
    query: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[KnowledgeOut]:
    statement = select(KnowledgeEntry).where(KnowledgeEntry.user_id == user.id)
    if city_code:
        statement = statement.where(KnowledgeEntry.city_code == city_code)
    if category:
        statement = statement.where(KnowledgeEntry.category == category)
    if query:
        from sqlalchemy import or_
        statement = statement.where(or_(
            KnowledgeEntry.title.contains(query[:100]),
            KnowledgeEntry.body.contains(query[:100]),
        ))
    rows = db.scalars(statement.order_by(KnowledgeEntry.id.desc()).limit(100)).all()
    return [KnowledgeOut.model_validate(row) for row in rows]


@router.get("/districts")
def list_districts(city_code: str, user: User = Depends(current_user)) -> list[dict[str, str]]:
    if city_code not in selectable_cities():
        raise HTTPException(status_code=422, detail="Unknown city")
    return [{"code": code, "name": name} for code, name in city_districts().get(city_code, {}).items()]


@router.get("/{entry_id}", response_model=KnowledgeOut)
def get_knowledge(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> KnowledgeOut:
    return KnowledgeOut.model_validate(_owned_entry(db, user.id, entry_id))


@router.patch("/{entry_id}", response_model=KnowledgeOut)
def patch_knowledge(
    entry_id: int,
    payload: KnowledgePatch,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> KnowledgeOut:
    entry = _owned_entry(db, user.id, entry_id)
    merged = {key: getattr(entry, key) for key in KnowledgePayload.model_fields}
    merged.update(payload.model_dump(exclude_unset=True))
    try:
        validated = KnowledgePayload.model_validate(merged)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    for key, value in validated.model_dump().items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return KnowledgeOut.model_validate(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_knowledge(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    db.delete(_owned_entry(db, user.id, entry_id))
    db.commit()
    return Response(status_code=204)
