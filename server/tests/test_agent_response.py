from app.agent.models import (
    BudgetInfo,
    CollectedInfo,
    DistanceInfo,
    InfoRequirement,
    InformationStatus,
    POIInfo,
    RouteInfo,
    TravelHistoryInfo,
    TravelRequirement,
    WeatherInfo,
)
from app.agent.response import FinalResponseGenerator


def test_weather_response_uses_only_collected_weather_facts() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="weather_query", destination="南京"),
        CollectedInfo(
            weather=WeatherInfo(
                location="南京市",
                date="2026-10-01",
                description="晴",
                temperature_min=20,
                temperature_max=28,
            )
        ),
        InformationStatus(weather=InfoRequirement(status="completed", critical=True)),
    )

    assert "南京市" in response
    assert "2026-10-01" in response
    assert "晴" in response
    assert "20℃至28℃" in response
    assert "降雨概率" not in response


def test_failed_information_is_explained_explicitly() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="weather_query", destination="南京"),
        CollectedInfo(),
        InformationStatus(
            weather=InfoRequirement(
                status="unavailable",
                critical=True,
                attempts=3,
                reason="天气服务没有返回数据",
            )
        ),
    )

    assert "天气信息暂不可用" in response
    assert "天气服务没有返回数据" in response

    failed_response = FinalResponseGenerator().generate(
        TravelRequirement(intent="weather_query", destination="南京"),
        CollectedInfo(),
        InformationStatus(
            weather=InfoRequirement(
                status="failed",
                critical=True,
                attempts=3,
                reason="天气服务连接超时",
            )
        ),
    )

    assert "天气信息查询失败" in failed_response
    assert "天气服务连接超时" in failed_response


def test_history_response_uses_structured_history_facts() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="history_query"),
        CollectedInfo(
            history=TravelHistoryInfo(
                trip_count=2,
                visited_cities=["南京市", "北京市"],
                visited_names=["中山陵", "故宫"],
            )
        ),
        InformationStatus(history=InfoRequirement(status="completed", critical=True)),
    )

    assert "2 次" in response
    assert "南京市、北京市" in response
    assert "中山陵、故宫" in response


def test_route_response_uses_route_facts_and_rmb_budget_is_labeled() -> None:
    route_response = FinalResponseGenerator().generate(
        TravelRequirement(intent="route_query"),
        CollectedInfo(
            routes=[
                RouteInfo(
                    origin_id="中山陵",
                    destination_id="夫子庙",
                    mode="transit",
                    distance_meters=8500,
                    duration_minutes=35,
                )
            ]
        ),
        InformationStatus(routes=InfoRequirement(status="completed", critical=True)),
    )
    budget_response = FinalResponseGenerator().generate(
        TravelRequirement(intent="budget_query", destination="南京"),
        CollectedInfo(
            budget=BudgetInfo(
                estimated_min=800,
                estimated_max=1200,
                breakdown={"住宿": 500},
            )
        ),
        InformationStatus(budget=InfoRequirement(status="completed", critical=True)),
    )

    assert "中山陵" in route_response
    assert "夫子庙" in route_response
    assert "35 分钟" in route_response
    assert "人民币" in budget_response
    assert "800 元至 1200 元" in budget_response
    assert "住宿 500 元" in budget_response


def test_poi_response_lists_only_available_poi_fields() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="poi_recommendation", destination="杭州"),
        CollectedInfo(
            pois=[
                POIInfo(
                    poi_id="A1",
                    name="西湖",
                    location="120.15,30.25",
                    category="风景名胜",
                    address="杭州市西湖区",
                )
            ]
        ),
        InformationStatus(pois=InfoRequirement(status="completed", critical=True)),
    )

    assert "西湖" in response
    assert "风景名胜" in response
    assert "杭州市西湖区" in response
    assert "评分" not in response


def test_pending_or_general_request_gets_a_truthful_fallback() -> None:
    pending_response = FinalResponseGenerator().generate(
        TravelRequirement(intent="route_query"),
        CollectedInfo(),
        InformationStatus(routes=InfoRequirement(status="pending", critical=True)),
    )
    general_response = FinalResponseGenerator().generate(
        TravelRequirement(intent="general_query"),
        CollectedInfo(),
        InformationStatus(),
    )

    assert "仍在收集" in pending_response
    assert "暂时无法给出完整结果" in pending_response
    assert "通用旅行问答" in general_response


def test_distance_is_rendered_when_distance_information_is_requested() -> None:
    response = FinalResponseGenerator().generate(
        TravelRequirement(intent="route_query"),
        CollectedInfo(
            distances=[
                DistanceInfo(
                    origin_id="南京站",
                    destination_id="中山陵",
                    distance_meters=12000,
                )
            ]
        ),
        InformationStatus(routes=InfoRequirement(status="completed", critical=True)),
    )

    assert "南京站" in response
    assert "中山陵" in response
    assert "12.0 公里" in response
