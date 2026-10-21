import pytest
from sqlalchemy import event

from app.agent.models import TravelRequirement
from app.agent.runtime import AgentRuntime
from app.agent.knowledge import search_knowledge
from app.models import KnowledgeEntry, User


def seed(db, notes):
    db.add_all([User(id=1, username="pref-owner", password_hash="unused"),
                User(id=2, username="pref-other", password_hash="unused")])
    db.flush()
    for item in notes:
        values = dict(user_id=1, city_code="320100", city_name="南京市", tags=[], category="attraction_guide")
        values.update(item)
        db.add(KnowledgeEntry(**values))
    db.commit()


def planning(db, preferences=(), constraints=(), city="南京", kind=None):
    requirement = TravelRequirement(intent="trip_planning", city=city, duration_days=3,
                                    preferences=list(preferences), constraints=list(constraints))
    return AgentRuntime._search_knowledge(db, 1, city, [], kind=kind, requirement=requirement)


def test_soft_topic_ranks_related_note_without_requiring_instruction_words(db_session):
    seed(db_session, [
        dict(id=1, title="南京历史文化", body="推荐南京博物院，提前预约。", tags=["历史文化"]),
        dict(id=2, title="公园散步", body="玄武湖适合散步。"),
        dict(id=3, user_id=2, title="历史文化私密", body="其他账号。"),
        dict(id=4, city_code="320500", city_name="苏州市", title="历史文化", body="苏州攻略。"),
    ])
    rows = planning(db_session, ["喜欢历史文化", "参考我收藏的攻略"])
    assert [row.id for row in rows] == [1, 2]


def test_topic_aliases_rank_related_content_above_new_unrelated_note(db_session):
    seed(db_session, [dict(id=1, title="南京博物院", body="参观博物馆。"),
                      dict(id=2, title="购物", body="商场购物。")])
    assert [row.id for row in planning(db_session, ["历史文化"])] == [1, 2]


def test_explicit_only_topic_remains_hard_condition(db_session):
    seed(db_session, [dict(id=1, title="历史文化", body="历史文化展览。"),
                      dict(id=2, title="散步", body="玄武湖。")])
    assert [row.id for row in planning(db_session, constraints=["只推荐历史文化"])] == [1]


@pytest.mark.parametrize("diet", ["不吃辣", "清淡"])
def test_scoped_constraints_accept_project_definition_of_light_food(db_session, diet):
    seed(db_session, [
        dict(id=1, title="古鸡鸣寺", body="寺庙参观。"),
        dict(id=2, title="南京博物院", body="博物馆参观。"),
        dict(id=3, category="food_guide", title="汤包店", body="推荐汤包，可以不放辣。"),
        dict(id=4, category="food_guide", title="清淡饭店", body="推荐清淡午餐，没有说明辣度。"),
        dict(id=5, category="food_guide", title="辣味店", body="推荐麻辣火锅。"),
        dict(id=6, category="food_guide", title="不确定饭店", body="不能保证不辣。"),
    ])
    rows = planning(db_session, ["历史文化"], ["不去寺庙", diet])
    assert {row.id for row in rows} == {2, 3, 4}


@pytest.mark.parametrize("restriction", ["不吃辣", "不辣", "清淡"])
def test_light_and_non_spicy_are_equivalent_but_explicit_spice_conflicts(db_session, restriction):
    seed(db_session, [
        dict(id=1, category="food_guide", title="家常菜", body="推荐清淡面条。"),
        dict(id=2, category="food_guide", title="汤包", body="推荐不辣汤包。"),
        dict(id=3, category="food_guide", title="矛盾描述", body="清淡面条，但是微辣。"),
        dict(id=4, category="food_guide", title="不确定", body="午餐，没有口味说明。"),
        dict(id=5, category="food_guide", title="可选口味", body="可以不放辣椒。"),
        dict(id=6, category="food_guide", title="相反口味", body="这家不清淡。"),
    ])
    assert {row.id for row in AgentRuntime._search_knowledge(db_session, 1, "南京", [restriction], kind="food")} == {1, 2, 5}


@pytest.mark.parametrize("name, conflict", [("微辣面条", True), ("麻辣火锅", True), ("不辣汤包", False)])
def test_light_food_constraint_also_applies_to_verified_poi_filter(name, conflict):
    from app.agent.utils import food_conflicts
    requirement = TravelRequirement(intent="trip_planning", constraints=["清淡"])
    assert food_conflicts(name, requirement) is conflict


@pytest.mark.parametrize("text", ["不要清淡", "不想吃清淡"])
def test_rejecting_light_food_does_not_enable_non_spicy_filter(text):
    from app.agent.utils import non_spicy_required
    assert not non_spicy_required(TravelRequirement(intent="trip_planning", constraints=[text]))


def test_district_and_section_boundaries_survive_soft_ranking(db_session):
    seed(db_session, [dict(id=1, city_code="350100", city_name="福州市", category="travel_guide",
        title="福州两区", body="长乐：博物馆参观。晋安：历史文化和寺庙。", sections=[
            {"district_code": "350112", "category": "attraction_guide", "text": "长乐：博物馆参观。"},
            {"district_code": "350111", "category": "attraction_guide", "text": "晋安：历史文化和寺庙。"},
        ])])
    rows = planning(db_session, ["历史文化"], city="福州长乐", kind="attraction")
    assert len(rows) == 1 and rows[0].district_code == "350112"
    assert "晋安" not in rows[0].excerpt


def test_negative_mention_does_not_satisfy_required_keyword(db_session):
    seed(db_session, [dict(id=1, title="中山陵笔记", body="不是中山陵游览，推荐夫子庙。"),
                      dict(id=2, title="游览", body="推荐中山陵，提前预约。")])
    rows = AgentRuntime._search_knowledge(db_session, 1, "南京", ["中山陵"])
    assert [row.id for row in rows] == [2]
    assert [row.id for row in AgentRuntime._search_knowledge(db_session, 1, "南京", ["夫子庙"])] == [1]


def test_excerpt_centers_on_match_and_preserves_original_pointer(db_session):
    body = "这是背景介绍。" * 100 + "推荐夫子庙清淡早餐：汤包。" + "结束。" * 100
    seed(db_session, [dict(id=1, category="food_guide", title="长攻略", body=body)])
    rows = search_knowledge(db_session, 1, "320100", keywords=["夫子庙", "清淡"])
    assert len(rows) == 1 and "推荐夫子庙清淡早餐：汤包。" in rows[0].excerpt
    assert len(rows[0].excerpt) <= 240
    start = rows[0].source_start
    assert start > 0 and body[start:start + len(rows[0].excerpt)] == rows[0].excerpt


def test_title_only_match_extracts_food_content_instead_of_background(db_session):
    body = "背景资料。" * 100 + "晚餐推荐：这里有面条和汤包。"
    seed(db_session, [dict(id=1, category="food_guide", title="夫子庙餐食", body=body)])
    rows = search_knowledge(db_session, 1, "320100", keywords=["夫子庙"])
    assert "晚餐推荐：这里有面条和汤包。" in rows[0].excerpt


def test_dietary_evidence_survives_excerpt_truncation(db_session):
    body = "餐食介绍。" * 100 + "这家店可以不放辣。"
    seed(db_session, [dict(id=1, category="food_guide", title="饭店", body=body)])
    rows = planning(db_session, constraints=["不吃辣"], kind="food")
    assert "可以不放辣" in rows[0].excerpt


def test_preference_search_executes_one_candidate_select(db_session):
    seed(db_session, [dict(id=i, title="历史文化", body="博物馆。") for i in range(1, 8)])
    selects = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)
    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        rows = planning(db_session, ["喜欢历史文化", "参考收藏"])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(selects) == 1
    assert len(rows) <= 5 and sum(len(row.excerpt) for row in rows) <= 800


@pytest.mark.parametrize("constraints", [["必须包含夫子庙", "必须包含清淡"], ["必须包含清淡", "必须包含夫子庙"], ["夫子庙", "清淡"]])
def test_all_required_conditions_remain_conjunctive(db_session, constraints):
    seed(db_session, [dict(id=1, category="food_guide", title="夫子庙", body="清淡早餐。"),
                      dict(id=2, category="food_guide", title="夫子庙", body="午餐。"),
                      dict(id=3, category="food_guide", title="玄武湖", body="清淡早餐。")])
    assert [row.id for row in planning(db_session, ["喜欢历史文化"], constraints, kind="food")] == [1]


def test_conjoined_exclusions_are_all_enforced(db_session):
    seed(db_session, [dict(id=1, title="古鸡鸣寺", body="参观寺庙。"),
                      dict(id=2, title="商场", body="逛商场。"),
                      dict(id=3, title="南京博物院", body="参观博物馆。")])
    assert [row.id for row in planning(db_session, constraints=["不要寺庙和商场"])] == [3]


def test_planning_node_uses_complete_requirement_for_knowledge(db_session):
    from app.agent.graph import _initialize_information_node, make_initial_state
    seed(db_session, [dict(id=1, title="历史文化", body="参观寺庙。"),
                      dict(id=2, title="南京博物院", body="参观博物馆。")])
    state = make_initial_state("南京一日游，喜欢历史文化，不去寺庙，参考收藏")
    state["requirement"] = TravelRequirement(intent="trip_planning", city="南京", duration_days=1,
        preferences=["喜欢历史文化", "参考我收藏的攻略"], constraints=["不去寺庙"])
    result = _initialize_information_node(state, knowledge_searcher=lambda requirement, kind:
        AgentRuntime._search_knowledge(db_session, 1, requirement.city, [], kind=kind, requirement=requirement))
    assert [row.id for row in result["collected_info"].knowledge] == [2]
