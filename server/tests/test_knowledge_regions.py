import pytest
from pydantic import ValidationError

from app.api.knowledge import KnowledgePayload
from app.agent.knowledge import search_knowledge
from app.agent.runtime import AgentRuntime
from app.models import KnowledgeEntry, User


BODY = "长乐：清淡海鲜。\n鼓楼：三坊七巷散步。"


def payload(**changes):
    return {"category": "travel_guide", "title": "福州攻略", "body": BODY,
            "city_code": "350100", "city_name": "福州市", "tags": [],
            "sections": [
                {"district_code": "350112", "category": "food_guide", "text": "长乐：清淡海鲜。"},
                {"district_code": "350102", "category": "attraction_guide", "text": "鼓楼：三坊七巷散步。"},
            ], **changes}


def seed(db):
    db.add(User(id=1, username="regions", password_hash="unused"))
    db.flush()
    entry = KnowledgeEntry(user_id=1, **KnowledgePayload.model_validate(payload()).model_dump())
    db.add(entry)
    db.add(KnowledgeEntry(user_id=1, category="food_guide", title="全城美食", body="未标注区域的美食",
                          city_code="350100", city_name="福州市", tags=[]))
    db.commit()
    return entry


def test_district_query_returns_only_confirmed_matching_section(db_session):
    entry = seed(db_session)
    rows = AgentRuntime._search_knowledge(db_session, 1, "福州长乐", [], kind="food")
    assert [row.id for row in rows] == [entry.id]
    assert "清淡海鲜" in rows[0].excerpt
    assert "三坊七巷" not in rows[0].excerpt
    assert rows[0].district_code == "350112"
    assert rows[0].source_start == 0


def test_city_query_includes_unscoped_and_scoped_notes(db_session):
    entry = seed(db_session)
    rows = AgentRuntime._search_knowledge(db_session, 1, "福州", [], kind="food")
    assert len(rows) == 2
    assert any(row.id == entry.id and "清淡海鲜" in row.excerpt and "三坊七巷" not in row.excerpt for row in rows)


def test_region_and_owner_never_fall_back(db_session):
    seed(db_session)
    assert AgentRuntime._search_knowledge(db_session, 1, "福州晋安", [], kind="food") == []
    assert AgentRuntime._search_knowledge(db_session, 2, "福州长乐", [], kind="food") == []
    assert AgentRuntime._search_knowledge(db_session, 1, "鼓楼区", [], kind="food") == []
    assert AgentRuntime._search_knowledge(db_session, 1, "福州长乐", ["不存在的食物"], kind="food") == []


@pytest.mark.parametrize("sections", [
    [{"district_code": "320106", "text": "长乐：清淡海鲜。"}],
    [{"district_code": "350112", "text": "编造原文"}],
    [{"district_code": "350112", "text": ""}],
    [{"district_code": "350112", "category": "invalid", "text": "长乐：清淡海鲜。"}],
])
def test_region_metadata_rejects_wrong_parent_or_invalid_source(sections):
    with pytest.raises(ValidationError):
        KnowledgePayload.model_validate(payload(sections=sections))


def test_edit_cannot_leave_stale_region_metadata(client):
    created = client.post("/api/v1/agent/knowledge", json=payload())
    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert len(created.json()["sections"]) == 2
    assert client.patch(f"/api/v1/agent/knowledge/{entry_id}", json={"body": "新的正文"}).status_code == 422
    updated = client.patch(f"/api/v1/agent/knowledge/{entry_id}", json={"body": "新的正文", "sections": []})
    assert updated.status_code == 200


def test_district_catalog_is_parent_scoped(client):
    rows = client.get("/api/v1/agent/knowledge/districts", params={"city_code": "350100"})
    assert rows.status_code == 200
    assert {row["code"]: row["name"] for row in rows.json()}["350112"] == "长乐区"
    assert "320106" not in {row["code"] for row in rows.json()}
    assert client.get("/api/v1/agent/knowledge/districts", params={"city_code": "999999"}).status_code == 422


def test_city_query_without_category_retains_both_regions(db_session):
    entry = seed(db_session)
    rows = AgentRuntime._search_knowledge(db_session, 1, "福州", [])
    excerpts = [row.excerpt for row in rows if row.id == entry.id]
    assert any("长乐" in text for text in excerpts)
    assert any("鼓楼" in text for text in excerpts)


def test_generic_guide_can_supply_food_only_via_explicit_section(db_session):
    seed(db_session)
    assert AgentRuntime._search_knowledge(db_session, 1, "福州鼓楼", [], kind="food") == []
    rows = AgentRuntime._search_knowledge(db_session, 1, "福州鼓楼", [], kind="attraction")
    assert len(rows) == 1 and rows[0].source_start == BODY.index("鼓楼")


def test_municipality_and_district_aliases():
    from app.agent.knowledge import city_districts, resolve_knowledge_scope
    assert resolve_knowledge_scope("福州市长乐区") == ("350100", "350112")
    assert resolve_knowledge_scope("长乐区") == ("350100", "350112")
    assert resolve_knowledge_scope("北京市海淀区") == ("110000", "110108")
    assert "110108" in city_districts()["110000"]
    assert resolve_knowledge_scope("仙桃") == ("429004", None)


def test_overlapping_sections_cannot_label_whole_note_as_two_districts():
    with pytest.raises(ValidationError):
        KnowledgePayload.model_validate(payload(sections=[
            {"district_code": "350112", "text": BODY},
            {"district_code": "350102", "text": "鼓楼：三坊七巷散步。"},
        ]))


def test_repeated_text_requires_a_more_specific_source_excerpt():
    with pytest.raises(ValidationError):
        KnowledgePayload.model_validate(payload(body="推荐面条。推荐面条。", sections=[
            {"district_code": "350112", "text": "推荐面条。"},
        ]))
