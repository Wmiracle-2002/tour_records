import pytest
from sqlalchemy import event

from app.agent.knowledge import search_knowledge
from app.agent.models import TravelRequirement
from app.agent.runtime import AgentRuntime
from app.models import KnowledgeEntry, User


@pytest.fixture
def district_notes(db_session):
    db_session.add_all([User(id=1, username="district-owner", password_hash="unused"),
                        User(id=2, username="district-other", password_hash="unused")])
    db_session.flush()
    notes = [
        (1, 1, "320100", "秦淮片段", "推荐清淡汤包。", "320104"),
        (2, 1, "320100", "玄武片段", "历史文化，推荐清淡面条。", "320102"),
        (3, 1, "320100", "区域未知", "推荐清淡早餐。", None),
        (4, 2, "320100", "其他账号", "推荐清淡汤包。", "320104"),
        (5, 1, "320500", "苏州笔记", "推荐清淡汤包。", None),
    ]
    for number, user_id, city, title, body, district in notes:
        db_session.add(KnowledgeEntry(id=number, user_id=user_id, city_code=city,
            city_name="南京市" if city == "320100" else "苏州市", category="food_guide",
            title=title, body=body, tags=[], sections=[
                {"text": body, "district_code": district, "category": "food_guide"},
            ] if district else []))
    db_session.commit()
    return db_session


def recommend(db, *, city="南京秦淮区", preferences=(), constraints=()):
    requirement = TravelRequirement(intent="poi_recommendation", city=city, poi_kind="food",
                                    preferences=list(preferences), constraints=list(constraints))
    return AgentRuntime._search_knowledge(db, 1, city, [], kind="food", requirement=requirement)


def test_district_is_a_preference_but_account_and_city_are_hard(district_notes):
    rows = recommend(district_notes, preferences=["历史文化"])
    assert [row.id for row in rows] == [1, 2, 3]
    assert rows[0].district_name == "秦淮区"
    assert rows[1].district_name == "玄武区"


def test_missing_preferred_district_can_return_same_city_with_actual_metadata(district_notes):
    rows = recommend(district_notes, city="南京鼓楼区")
    assert {row.id for row in rows} == {1, 2, 3}
    assert all(row.district_code != "320106" for row in rows)


@pytest.mark.parametrize("constraint", ["只要秦淮区的内容", "仅限南京市秦淮区", "只推荐秦淮区", "只在秦淮区", "不要其他区"])
def test_explicit_district_limit_is_metadata_not_literal_keyword(district_notes, constraint):
    rows = recommend(district_notes, preferences=["清淡"], constraints=[constraint, "不要微辣"])
    assert [row.id for row in rows] == [1]
    assert "秦淮区的内容" not in rows[0].excerpt


@pytest.mark.parametrize("preference", ["秦淮区", "最好在秦淮区", "优先考虑南京市秦淮区"])
def test_district_preference_can_be_in_preferences_instead_of_city(district_notes, preference):
    assert [row.id for row in recommend(district_notes, city="南京", preferences=[preference])] == [1, 3, 2]


def test_city_only_keeps_notes_from_multiple_districts(district_notes):
    assert {row.id for row in recommend(district_notes, city="南京")} == {1, 2, 3}


def test_plain_district_in_constraints_is_still_only_a_preference(district_notes):
    assert [row.id for row in recommend(district_notes, city="南京", constraints=["秦淮区"])] == [1, 3, 2]


def test_combined_region_and_content_keep_all_hard_conditions(district_notes):
    assert [row.id for row in recommend(district_notes, constraints=["只要秦淮区的清淡美食"])] == [1]
    assert recommend(district_notes, constraints=["只要秦淮区的历史文化美食"]) == []
    assert recommend(district_notes, constraints=["只要秦淮区的内容", "必须包含海鲜"]) == []


def test_region_exclusion_does_not_match_note_body(district_notes):
    assert [row.id for row in recommend(district_notes, city="南京", constraints=["不要秦淮区"])] == [2]
    assert recommend(district_notes, constraints=["只要秦淮区的内容", "不要秦淮区"]) == []


@pytest.mark.parametrize("constraint, expected", [("只要秦淮区以外的内容", [2]), ("不要秦淮区以外的内容", [1])])
def test_region_exclusion_polarity_is_not_reversed(district_notes, constraint, expected):
    assert [row.id for row in recommend(district_notes, constraints=[constraint])] == expected


def test_unknown_or_foreign_hard_region_does_not_expand_scope(district_notes):
    assert recommend(district_notes, constraints=["只要不存在区的内容"]) == []
    assert recommend(district_notes, constraints=["只要苏州市姑苏区的内容"]) == []
    assert recommend(district_notes, constraints=["只要秦淮区的内容", "仅限玄武区"]) == []


def test_multi_region_note_prefers_its_matching_fragment(district_notes):
    body = "推荐清淡馄饨。其他区域的历史文化午餐。"
    district_notes.add(KnowledgeEntry(id=6, user_id=1, city_code="320100", city_name="南京市",
        category="travel_guide", title="多区收藏", body=body, tags=[], sections=[
            {"text": "推荐清淡馄饨。", "district_code": "320104", "category": "food_guide"},
            {"text": "其他区域的历史文化午餐。", "district_code": "320102", "category": "food_guide"},
        ]))
    district_notes.commit()
    rows = recommend(district_notes, preferences=["历史文化"])
    assert rows[0].id == 6
    assert [row.excerpt for row in rows if row.id == 6] == ["推荐清淡馄饨。"]
    assert body[rows[0].source_start:rows[0].source_start + len(rows[0].excerpt)] == rows[0].excerpt


def test_low_level_explicit_district_filter_remains_strict(district_notes):
    rows = search_knowledge(district_notes, 1, "320100", district_code="320104")
    assert [row.id for row in rows] == [1]


def test_district_preference_uses_one_candidate_select(district_notes):
    selects = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)
    engine = district_notes.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        rows = recommend(district_notes, constraints=["只要秦淮区的内容"])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert [row.id for row in rows] == [1]
    assert len(selects) == 1


def test_food_answer_labels_the_actual_district_of_a_cited_fallback(district_notes):
    from app.agent.factual import FactualAnswerer
    class Amap:
        def search_verified_pois(self, **kwargs):
            return {"pois": [{"name": "清淡面条"}]}
    answer = FactualAnswerer(Amap(), knowledge_searcher=lambda requirement, kind:
        AgentRuntime._search_knowledge(district_notes, 1, requirement.city, [], kind=kind, requirement=requirement)
    ).answer(TravelRequirement(intent="poi_recommendation", city="南京鼓楼区", poi_kind="food"))
    assert "[收藏#2] 玄武片段（玄武区）" in answer


def test_planning_citation_labels_region_instead_of_implying_requested_district(district_notes):
    from app.agent.models import CollectedInfo, InformationStatus, Itinerary, ItineraryDay, ItineraryItem, POIInfo
    from app.agent.response import FinalResponseGenerator
    rows = recommend(district_notes, city="南京鼓楼区")
    answer = FinalResponseGenerator().generate(
        TravelRequirement(intent="trip_planning", city="南京鼓楼区", duration_days=1),
        CollectedInfo(knowledge=rows, pois=[POIInfo(poi_id="F1", name="清淡面条", category="餐饮服务", location="118.8,32.0")]),
        InformationStatus(), Itinerary(days=[ItineraryDay(day_number=1, items=[
            ItineraryItem(poi_id="F1", poi_name="清淡面条", activity_type="FOOD", period="lunch"),
        ])]),
    )
    assert "[收藏#2] 玄武片段（玄武区）" in answer
