from app.agent.models import (
    BudgetInfo,
    CollectedInfo,
    InfoRequirement,
    InformationStatus,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    POIInfo,
    RouteInfo,
    TravelRequirement,
    ValidationIssue,
    ValidationResult,
    WeatherInfo,
)
from app.agent.response import FinalResponseGenerator


def _itinerary() -> Itinerary:
    return Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[
                    ItineraryItem(
                        poi_id="P1",
                        poi_name="中山陵",
                        start_time="09:00",
                        end_time="11:00",
                        activity_type="游览",
                        estimated_cost=0,
                    ),
                    ItineraryItem(
                        poi_id="P2",
                        poi_name="夫子庙",
                        start_time="13:00",
                        end_time="15:00",
                        activity_type="游览",
                        estimated_cost=30,
                    ),
                ],
            )
        ]
    )


def test_trip_response_renders_itinerary_and_available_supporting_facts() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="trip_planning", city="南京"),
        CollectedInfo(
            pois=[
                POIInfo(poi_id="P1", name="中山陵", location="118.8,32.0"),
                POIInfo(poi_id="P2", name="夫子庙", location="118.8,32.0"),
            ],
            routes=[
                RouteInfo(
                    origin_id="P1",
                    destination_id="P2",
                    mode="transit",
                    distance_meters=8500,
                    duration_minutes=35,
                )
            ],
            weather=WeatherInfo(
                location="南京",
                date="2026-10-01",
                description="晴",
                temperature_min=20,
                temperature_max=28,
            ),
            budget=BudgetInfo(estimated_min=100, estimated_max=200),
        ),
        InformationStatus(
            weather=InfoRequirement(status="completed"),
            budget=InfoRequirement(status="completed"),
        ),
        _itinerary(),
        ValidationResult(valid=True),
    )

    assert "第1天（2026-10-01）" in response
    assert "09:00-11:00：中山陵" in response
    assert "13:00-15:00：夫子庙" in response
    assert "中山陵 到 夫子庙" in response
    assert "35 分钟" in response
    assert "天气参考" in response
    assert "预算参考（人民币）" in response
    assert "P1" not in response
    assert "ValidationResult" not in response


def test_trip_response_explains_unknown_information_without_inventing_it() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="trip_planning", city="南京"),
        CollectedInfo(),
        InformationStatus(
            weather=InfoRequirement(
                status="unavailable",
                reason="天气服务没有返回数据",
            )
        ),
        _itinerary(),
        ValidationResult(
            valid=True,
            issues=[
                ValidationIssue(
                    type="opening_hours",
                    status="unknown",
                    day=1,
                    related_poi_ids=["P1"],
                    message="暂时没有中山陵的可靠开放时间。",
                    suggested_action="出发前确认景点当天的开放安排。",
                )
            ],
        ),
    )

    assert "未获取到中山陵可靠的开放时间" in response
    assert "出发前确认" in response
    assert "未将天气因素纳入安排" in response
    assert "天气服务没有返回数据" not in response
    assert "P1" not in response


def test_trip_response_exposes_remaining_failures_after_revision_limit() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="trip_planning", city="南京"),
        CollectedInfo(),
        InformationStatus(),
        _itinerary(),
        ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    type="travel_time",
                    status="fail",
                    day=1,
                    related_poi_ids=["P1", "P2"],
                    message="中山陵到夫子庙的路线时间不足。",
                    suggested_action="增加路上时间或调整景点顺序。",
                )
            ],
        ),
    )

    assert "尚未完全通过校验" in response
    assert "中山陵到夫子庙的路线时间不足" in response
    assert "增加路上时间" in response
    assert "ValidationResult" not in response


def test_trip_response_handles_missing_itinerary() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="trip_planning", city="南京"),
        CollectedInfo(),
        InformationStatus(),
        None,
        None,
    )

    assert response == "当前还没有可展示的完整行程。"


def test_coarse_trip_budget_uses_chinese_labels_and_does_not_call_unestimated_tickets_free() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="trip_planning", city="南京", duration_days=1),
        CollectedInfo(budget=BudgetInfo(
            estimated_min=168, estimated_max=252,
            breakdown={"accommodation": 0, "food": 150, "transport": 60, "poi_tickets": 0},
        )),
        InformationStatus(budget=InfoRequirement(status="completed")),
        Itinerary(days=[ItineraryDay(day_number=1, items=[])]),
        ValidationResult(valid=True),
    )

    assert "住宿 0 元" in response
    assert "餐饮 150 元" in response
    assert "交通 60 元" in response
    assert "景点门票未计入" in response
    assert "poi_tickets" not in response
    assert "校验说明：已安排地点通过规则检查" in response
    assert "行程已通过可确定规则检查" not in response
