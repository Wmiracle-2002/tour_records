"""Isolated per-case fixtures and deterministic AMap provider responses."""

from copy import deepcopy
from datetime import date
from uuid import uuid4

from run_pilot import SnapshotProvider


class FullSnapshotProvider(SnapshotProvider):
    def configure(self, setup):
        self.setup = setup

    def __init__(self, fixtures):
        super().__init__(fixtures)
        self.setup = {}

    def __call__(self, url, params, timeout):
        path = url.removeprefix("https://restapi.amap.com")
        parameters = {key: value for key, value in params.items() if key != "key"}
        if path == "/v3/place/text":
            call = {"path": path, "parameters": parameters}
            self.calls.append(call)
            if self.setup.get("fault") == "poi_timeout":
                call["fault"] = "poi_timeout"
                raise TimeoutError("Injected AMap POI timeout")
            pool = deepcopy(self.fixtures["tool_snapshots"]["pois"])
            if "poi_pool" in self.setup:
                # Return deliberately wrong candidates too: the real client must filter.
                pool = [poi for poi in pool if poi["ref"] in self.setup["poi_pool"]]
            else:
                city = str(params.get("city", ""))
                pool = [poi for poi in pool if city in {
                    poi["city"], poi["city"].removesuffix("市"), poi["city_code"], poi["adcode"]
                } or ("长乐" in city and poi["city_code"] == "350100")]
            keyword = params["keywords"]
            if keyword in {"美食", "景点"}:
                category = "FOOD" if keyword == "美食" else "ATTRACTION"
                pool = [poi for poi in pool if poi["category"] == category]
            else:
                pool = [poi for poi in pool if poi["name"] == keyword]
            call["returned_refs"] = [poi["ref"] for poi in pool[:10]]
            return {"status": "1", "infocode": "10000", "pois": [
                {"id": poi["poi_id"], "name": poi["name"], "cityname": poi["city"],
                 "adcode": poi["adcode"], "location": poi["location"], "address": "合成评测地址",
                 "type": "餐饮服务;中餐厅" if poi["category"] == "FOOD" else (
                     "风景名胜;寺庙" if "寺庙" in poi["tags"] else "风景名胜;景点")}
                for poi in pool[:10]]}
        if path == "/v3/config/district":
            self.calls.append({"path": path, "parameters": parameters})
            value = str(params["keywords"])
            city = "上海市" if value in {"上海", "上海市", "310000"} else (
                "长乐区" if "长乐" in value or value == "350112" else "南京市")
            if city == "南京市" and value not in {"南京", "南京市", "320100"}:
                raise ValueError(f"Unknown fixture district: {value}")
            code = {"上海市": "310000", "长乐区": "350112", "南京市": "320100"}[city]
            return {"status": "1", "infocode": "10000", "districts": [
                {"name": city, "level": "district" if city == "长乐区" else "city", "adcode": code}
            ]}
        if path == "/v3/weather/weatherInfo" and params["city"] == "310000":
            self.calls.append({"path": path, "parameters": parameters})
            weather = self.fixtures["tool_snapshots"]["weather_shanghai"]
            return {"status": "1", "infocode": "10000", "lives": [dict(weather["realtime"], adcode="310000")]}
        return super().__call__(url, params, timeout)


def seed_case(db, fixtures, case, prefix, password_hash, token_limit):
    """Create fresh identities, trips and only the explicitly requested setup."""
    from app.models import ChatConversation, ChatMessage, KnowledgeEntry, Record, RecordType, Trip, User, UserPreference
    users, refs, conversations = {}, {}, {}
    for alias, account in fixtures["accounts"].items():
        user = User(username=f"{prefix}_{alias}", password_hash=password_hash,
                    monthly_token_limit=0 if case["setup"].get("fault") == "quota_zero" else token_limit)
        db.add(user)
        db.flush()
        users[alias] = user.id
        for item in account["trips"]:
            trip = Trip(user_id=user.id, province_code=item["city_code"][:2] + "0000",
                        city_code=item["city_code"], city_name=item["city"],
                        start_date=date.fromisoformat(item["start_date"]), end_date=date.fromisoformat(item["end_date"]))
            db.add(trip)
            db.flush()
            refs[item["ref"]] = trip.id
            for record in item["records"]:
                row = Record(trip_id=trip.id, type=RecordType(record["type"]), name=record["name"],
                             date=date.fromisoformat(record["date"]), cost=record["cost"], rating=record["rating"])
                db.add(row)
                db.flush()
                refs[record["ref"]] = row.id
    for ref in case["setup"].get("preferences", []):
        value = fixtures["preferences"][ref]
        db.add(UserPreference(user_id=users[value["account"]], category=value["category"], content=value["content"]))
    for ref in case["setup"].get("knowledge", []):
        value = fixtures["knowledge"][ref]
        row = KnowledgeEntry(user_id=users[value["account"]], city_code=value["city_code"], city_name="南京市",
                             category=value["category"], title=value["title"], body=value["body"], tags=value["tags"])
        db.add(row)
        db.flush()
        refs[ref] = row.id
    if "history" in case["setup"]:
        history = fixtures["histories"][case["setup"]["history"]]
        conversation = ChatConversation(id=str(uuid4()), user_id=users[history["account"]])
        db.add(conversation)
        db.flush()
        conversations[history["conversation"]] = conversation.id
        previous_id = None
        for message in history["messages"]:
            row = ChatMessage(conversation_id=conversation.id, role=message["role"], content=message["content"],
                              status="completed", in_reply_to_message_id=previous_id if message["role"] == "assistant" else None)
            db.add(row)
            db.flush()
            previous_id = row.id
    db.commit()
    return users, refs, conversations


def inspect_case(db, users, conversations, refs, original_ids):
    from sqlalchemy import select
    from app.models import AgentConversationSummary, ChatMessage, KnowledgeEntry, UserPreference
    preferences = {alias: [{"category": row.category, "content": row.content} for row in db.scalars(
        select(UserPreference).where(UserPreference.user_id == uid)).all()] for alias, uid in users.items()}
    messages = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id.in_(list(conversations.values())))).all()
    summary_count = len(db.scalars(select(AgentConversationSummary).where(
        AgentConversationSummary.conversation_id.in_(list(conversations.values())))).all())
    return {"preferences": preferences, "summary_count": summary_count,
            "raw_messages_retained": original_ids <= {row.id for row in messages},
            "assistant_messages": [{"content": row.content, "status": row.status} for row in messages if row.role == "assistant"],
            "knowledge_owners": {ref: db.get(KnowledgeEntry, refs[ref]).user_id for ref in refs if ref.startswith("K")},
            "knowledge_refs": {ref: refs[ref] for ref in refs if ref.startswith("K")},
            "user_ids": users}
