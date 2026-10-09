import pytest

from app.agent.runtime import AgentRuntime
from app.models import KnowledgeEntry, User


def add_notes(db, notes):
    db.add(User(id=1, username="constraints", password_hash="unused"))
    db.flush()
    for note in notes:
        db.add(KnowledgeEntry(user_id=1, city_code="320100", city_name="南京市", tags=[], **note))
    db.commit()


@pytest.mark.parametrize("keywords", [["夫子庙", "清淡"], ["清淡", "夫子庙"]])
def test_place_and_diet_must_both_match(db_session, keywords):
    add_notes(db_session, [
        {"id": 1, "category": "food_guide", "title": "夫子庙餐食", "body": "清淡鸭血粉丝汤。"},
        {"id": 2, "category": "food_guide", "title": "夫子庙火锅", "body": "有辣味。"},
        {"id": 3, "category": "food_guide", "title": "玄武湖餐厅", "body": "清淡午餐。"},
        {"id": 4, "category": "food_guide", "title": "夫子庙包子", "body": "包子店，没有口味说明。"},
    ])
    rows = AgentRuntime._search_knowledge(db_session, 1, "南京", keywords, kind="food")
    assert [row.id for row in rows] == [1]


def test_separate_sections_cannot_combine_into_one_matching_fragment(db_session):
    add_notes(db_session, [{
        "id": 1, "category": "travel_guide", "title": "夫子庙和玄武湖清淡餐食",
        "body": "夫子庙：辣火锅。玄武湖：清淡午餐。",
        "sections": [
            {"category": "food_guide", "text": "夫子庙：辣火锅。"},
            {"category": "food_guide", "text": "玄武湖：清淡午餐。"},
        ],
    }])
    assert AgentRuntime._search_knowledge(db_session, 1, "南京", ["夫子庙", "清淡"], kind="food") == []


def test_history_includes_all_matching_note_categories(db_session):
    add_notes(db_session, [
        {"id": 1, "category": "food_guide", "title": "夫子庙餐食", "body": "包子。"},
        {"id": 2, "category": "attraction_guide", "title": "夫子庙夜景", "body": "散步。"},
        {"id": 3, "category": "travel_guide", "title": "夫子庙旧攻略", "body": "旧价格，需核实。"},
        {"id": 4, "category": "note", "title": "玄武湖", "body": "散步。"},
    ])
    rows = AgentRuntime._search_knowledge(db_session, 1, "南京", ["夫子庙"])
    assert {row.id for row in rows} == {1, 2, 3}
    assert {row.id for row in AgentRuntime._search_knowledge(db_session, 1, "南京", [], kind="food")} == {1}
    assert AgentRuntime._search_knowledge(db_session, 1, "南京", ["夫子庙", "不存在的条件"]) == []


def test_hard_conditions_are_not_silently_truncated(db_session):
    add_notes(db_session, [{
        "id": 1, "category": "food_guide", "title": "夫子庙清淡早餐面条", "body": "面条。",
    }])
    assert AgentRuntime._search_knowledge(
        db_session, 1, "南京", ["夫子庙", "清淡", "早餐", "面条", "海鲜"], kind="food",
    ) == []
