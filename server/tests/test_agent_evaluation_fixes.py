import pytest

from app.agent.analyzer import RequirementAnalyzer
from app.agent.models import TravelRequirement, CollectedInfo, Itinerary, ItineraryDay, ItineraryItem, POIInfo
from app.agent.preferences import parse_preference_command
from app.agent.generator import StructuredItineraryGenerator
from app.agent.factual import FactualAnswerer


class Client:
    def __init__(self, requirement):
        self.requirement = requirement

    def complete_structured(self, **kwargs):
        return self.requirement


@pytest.mark.parametrize('word,mode', [('步行', 'walking'), ('驾车', 'driving')])
def test_explicit_city_and_distance_mode_survive_llm_omission(word, mode):
    requirement = RequirementAnalyzer(Client(TravelRequirement(
        intent='distance_query', origin='中山陵', destination='夫子庙',
    ))).analyze(f'南京中山陵到夫子庙{word}有多远？')
    assert requirement.city == '南京' and requirement.distance_mode == mode


def test_unresolved_destination_is_not_invented_by_model():
    result = RequirementAnalyzer(Client(TravelRequirement(
        intent='distance_query', city='南京', origin='中山陵', destination='夫子庙',
    ))).analyze('南京中山陵到那里有多远？')
    assert result.destination is None


@pytest.mark.parametrize('message', ['请记住，我不吃辣', '请记住：我不吃辣', '以后请记住, 我不吃辣'])
def test_explicit_memory_command_accepts_punctuation(message):
    assert parse_preference_command(message) == ('save', 'food_restriction', '不吃辣')


def test_city_only_reply_keeps_pending_food_task_in_same_conversation():
    result = RequirementAnalyzer(Client(TravelRequirement(intent='general_query', city='南京'))).analyze(
        '南京的', session_state={'last_intent':'poi_recommendation', 'poi_kind':'food'},
    )
    assert result.intent == 'poi_recommendation' and result.poi_kind == 'food'


def test_one_day_trip_with_notes_is_planning_not_poi_recommendation():
    result = RequirementAnalyzer(Client(TravelRequirement(
        intent='poi_recommendation', city='南京', poi_kind='food',
    ))).analyze('南京一日游，午餐想吃鸭血粉丝汤，参考我的收藏')
    assert result.intent == 'trip_planning' and result.duration_days == 1
    assert result.poi_kind is None


def test_city_substring_in_attraction_does_not_override_city():
    result = RequirementAnalyzer(Client(TravelRequirement(
        intent='trip_planning', city='南京', duration_days=1,
    ))).analyze('我想去中山陵一日游')
    assert result.city == '南京'


def test_new_plan_can_refer_to_previous_budget_without_becoming_recall():
    result = RequirementAnalyzer(Client(TravelRequirement(
        intent='trip_planning', city='南京', duration_days=1,
    ))).analyze('按之前说的预算规划南京一日游')
    assert result.intent == 'trip_planning'


def test_rating_record_name_is_not_corrupted_by_went_before_verb():
    result = RequirementAnalyzer(Client(TravelRequirement(
        intent='history_query', history_record_name='夫子庙',
    ))).analyze('我之前去过夫子庙那次评分是多少？')
    assert result.history_record_name == '夫子庙'


def test_rmb_amount_is_not_interpreted_as_travelers(db_session):
    from app.agent.runtime import AgentRuntime
    from app.core.config import Settings

    class ReachedLLM(Exception):
        pass

    class Client:
        def complete_structured(self, **kwargs):
            raise ReachedLLM

    with pytest.raises(ReachedLLM):
        AgentRuntime(Settings(), llm_client=Client()).run(
            '南京一日游，2人，午餐预算50.5人民币', 1, db_session,
        )


@pytest.mark.parametrize('view,name,arguments', [
    ('trips', 'search_trip_history', {'start_date':'2026-01-01', 'end_date':'2026-12-31'}),
    ('ratings', 'search_records', {'trip_id':7, 'min_rating':4}),
])
def test_history_view_keeps_supported_filters(view, name, arguments):
    from test_agent_collector import FakeTool, FakeDecisionClient, build_layer, build_state
    from app.agent.collector import ReActCollector, ReActDecision, ToolCall
    from app.agent.tools.layer import ToolResult
    from app.agent.tools.internal import SearchTripHistoryInput, SearchRecordsInput

    tool = FakeTool(name, [ToolResult.completed([])])
    tool.input_model = SearchTripHistoryInput if view == 'trips' else SearchRecordsInput
    client = FakeDecisionClient([ReActDecision(tool_call=ToolCall(name=name, arguments=arguments))])
    ReActCollector(build_layer(tool), client).collect_round(build_state(TravelRequirement(
        intent='history_query', city='南京', history_view=view,
    )))
    assert tool.calls == [tool.input_model.model_validate({**arguments, 'city':'南京'}).model_dump(exclude_unset=True)]


def test_budget_response_lists_chinese_breakdown():
    answer = FactualAnswerer(None).answer(TravelRequirement(
        intent='budget_query', city='南京', duration_days=3, travelers=2,
    ))
    assert all(label in answer for label in ('人民币', '住宿', '餐饮', '交通'))


def test_sufficient_candidates_require_default_evening_period():
    pois = [POIInfo(poi_id=str(i), name=f'景点{i}', category='风景名胜', location='118.8,32.0') for i in range(3)]
    itinerary = Itinerary(days=[ItineraryDay(day_number=1, items=[
        ItineraryItem(poi_id='0', poi_name='景点0', period='morning', activity_type='ATTRACTION'),
        ItineraryItem(poi_id='1', poi_name='景点1', period='afternoon', activity_type='ATTRACTION'),
    ])])
    with pytest.raises(ValueError, match='evening'):
        StructuredItineraryGenerator._validate_requested_periods(
            itinerary, TravelRequirement(intent='trip_planning', duration_days=1), CollectedInfo(pois=pois),
        )


def test_memory_question_uses_memory_route_not_travel_database():
    from app.agent.graph import build_agent_graph, make_initial_state
    from app.agent.response import FinalResponseGenerator
    from app.agent.validator import ItineraryValidator

    class Collector:
        max_rounds = 4

        def collect_round(self, state):
            raise AssertionError('Conversation recall must not query travel records')

    graph = build_agent_graph(
        analyzer=RequirementAnalyzer(Client(TravelRequirement(intent='memory_query'))),
        collector=Collector(), itinerary_generator=None, validator=ItineraryValidator(),
        reviser=None, response_generator=FinalResponseGenerator(),
        memory_answerer=lambda state: '之前预算2000元，不去寺庙。',
    )
    result = graph.invoke(make_initial_state('最早的预算是多少？'))
    assert '2000' in result['final_response']


@pytest.mark.parametrize('number', ['0', '-1', '0.5', '零'])
def test_invalid_travelers_rejected_before_llm_or_budget_call(number, db_session):
    from app.agent.runtime import AgentRuntime
    from app.core.config import Settings

    class NoLLM:
        def complete_structured(self, **kwargs):
            raise AssertionError('Invalid input must not be silently corrected by LLM')

    result = AgentRuntime(Settings(), llm_client=NoLLM()).run(
        f'给{number}个人估算南京三日游的费用', 1, db_session,
    )
    assert '人数' in result.answer and '至少1人' in result.answer


def test_temple_exclusion_applies_to_generated_and_fallback_plans():
    from app.agent.generator import fallback_itinerary
    from app.agent.validator import ItineraryValidator
    req = TravelRequirement(intent='trip_planning', duration_days=1, constraints=['不去寺庙'])
    info = CollectedInfo(pois=[POIInfo(poi_id='T1', name='古鸡鸣寺', category='风景名胜', location='118.8,32.0')])
    itinerary = Itinerary(days=[ItineraryDay(day_number=1, items=[
        ItineraryItem(poi_id='T1', poi_name='古鸡鸣寺', period='morning', activity_type='ATTRACTION'),
    ])])
    with pytest.raises(ValueError, match='constraint'):
        StructuredItineraryGenerator(None)._validate_itinerary(itinerary, req, info)
    assert not ItineraryValidator().validate(req, itinerary, info).valid
    assert not fallback_itinerary(req, info).days[0].items


def test_explicit_unique_attractions_applies_across_days():
    from app.agent.validator import ItineraryValidator
    req = TravelRequirement(intent='trip_planning', duration_days=2, constraints=['景点不要重复'])
    info = CollectedInfo(pois=[POIInfo(poi_id='A1', name='中山陵', category='风景名胜', location='118.8,32.0')])
    itinerary = Itinerary(days=[ItineraryDay(day_number=n, items=[
        ItineraryItem(poi_id='A1', poi_name='中山陵', period='morning', activity_type='ATTRACTION'),
    ]) for n in (1, 2)])
    with pytest.raises(ValueError, match='repeat'):
        StructuredItineraryGenerator(None)._validate_itinerary(itinerary, req, info)
    assert not ItineraryValidator().validate(req, itinerary, info).valid
