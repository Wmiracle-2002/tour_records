"""Loose argument models for collector-only fake tools in tests."""

from pydantic import BaseModel, ConfigDict


class AgentTestInput(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


TEST_INFORMATION_NEEDS = {
    "get_travel_summary": "history",
    "search_trip_history": "history",
    "search_records": "history",
    "get_trip_detail": "history",
    "estimate_budget": "budget",
    "keyword_search": "pois",
    "around_search": "pois",
    "poi_detail": "pois",
    "weather": "weather",
    "distance": "distances",
    "driving_route": "routes",
    "transit_route": "routes",
    "walking_route": "routes",
    "cycling_route": "routes",
}
