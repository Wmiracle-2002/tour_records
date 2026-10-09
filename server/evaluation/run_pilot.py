"""Small real-LLM pilot over authenticated loopback HTTP and fixed tool data."""

import argparse
import hashlib
import json
import os
import secrets
import socket
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from time import monotonic, sleep


ROOT = Path(__file__).resolve().parent
PILOT_IDS = ("H01", "R02", "W01", "D01", "P01", "M01")


class SnapshotProvider:
    def __init__(self, fixtures: dict) -> None:
        self.fixtures = fixtures
        self.calls: list[dict] = []

    def __call__(self, url: str, params: dict, timeout: float) -> dict:
        path = url.removeprefix("https://restapi.amap.com")
        safe_params = {key: value for key, value in params.items() if key != "key"}
        self.calls.append({"path": path, "parameters": safe_params})
        snapshots = self.fixtures["tool_snapshots"]
        if path == "/v3/place/text":
            keyword, city = params["keywords"], str(params.get("city", "南京"))
            pool = [poi for poi in snapshots["pois"] if city in {
                poi["city"], poi["city"].removesuffix("市"), poi["city_code"], poi["adcode"]
            }]
            if keyword == "美食":
                pool = [poi for poi in pool if poi["category"] == "FOOD"]
            elif keyword == "景点":
                pool = [poi for poi in pool if poi["category"] == "ATTRACTION"]
            else:
                pool = [poi for poi in pool if poi["name"] == keyword]
            return {"status": "1", "infocode": "10000", "pois": [
                {"id": poi["poi_id"], "name": poi["name"], "cityname": poi["city"],
                 "adcode": poi["adcode"], "location": poi["location"],
                 "address": "合成评测地址", "type": (
                     "餐饮服务;中餐厅" if poi["category"] == "FOOD" else "风景名胜;景点"
                 )} for poi in pool[:10]
            ]}
        if path == "/v3/config/district":
            require(params["keywords"] in {"南京", "南京市", "320100"}, "unsupported pilot city")
            return {"status": "1", "infocode": "10000", "districts": [
                {"name": "南京市", "level": "city", "adcode": "320100"}
            ]}
        if path == "/v3/weather/weatherInfo":
            require(params["city"] == "320100", "wrong weather city")
            weather = snapshots["weather"]
            if params["extensions"] == "base":
                return {"status": "1", "infocode": "10000", "lives": [
                    {**weather["realtime"], "adcode": "320100", "temperature": "23"}
                ]}
            return {"status": "1", "infocode": "10000", "forecasts": [
                {"adcode": "320100", "reporttime": "2026-10-08 10:00:00", "casts": weather["forecasts"]}
            ]}
        if path == "/v3/distance":
            mode = {"0": "straight", "1": "driving", "3": "walking"}[str(params["type"])]
            pois = {poi["ref"]: poi for poi in snapshots["pois"]}
            require(params["origins"] == pois["A1"]["location"], "wrong distance origin")
            require(params["destination"] == pois["A2"]["location"], "wrong distance destination")
            return {"status": "1", "infocode": "10000", "results": [
                {"distance": str(snapshots["distance"]["values_meters"][mode])}
            ]}
        raise ValueError(f"unexpected tool endpoint: {path}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_sse(response, started_at: float) -> dict:
    events, content = [], []
    event_name, data_lines = None, []
    first_body_ms, completed_ms, answer = None, None, None
    terminal = None
    for line in response.iter_lines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif not line and data_lines:
            data = json.loads("\n".join(data_lines))
            elapsed = (monotonic() - started_at) * 1000
            events.append({"event": event_name, "elapsed_ms": elapsed, "data": data})
            if event_name in {"preview", "content"} and data.get("text", "").strip():
                first_body_ms = first_body_ms if first_body_ms is not None else elapsed
            if event_name == "content":
                content.append(data["text"])
            if event_name in {"completed", "error"}:
                terminal = event_name
                if event_name == "completed":
                    answer = data.get("answer") or "".join(content)
                    completed_ms = elapsed
            event_name, data_lines = None, []
    return {"events": events, "final_event": terminal, "answer": answer,
            "first_body_ms": first_body_ms, "completion_ms": completed_ms,
            "termination_ms": (monotonic() - started_at) * 1000}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--offline-check", action="store_true")
    parser.add_argument("--cases", nargs="+", default=list(PILOT_IDS))
    parser.add_argument("--token-limit", type=int, default=30000)
    args = parser.parse_args()
    require(0 < args.token_limit <= 30000, "pilot token limit must be 1..30000")
    output = Path(args.output).resolve()
    require(any(part.startswith(".test-run-") for part in output.parts), "output must be inside .test-run-* directory")
    output.mkdir(parents=True, exist_ok=False)
    database_path = output / "evaluation.sqlite"
    # Configure isolation before importing app.database or app.main.
    os.environ["FOOTMARKS_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    os.environ["FOOTMARKS_TOKEN_SECRET"] = secrets.token_urlsafe(48)
    os.environ["FOOTMARKS_TOKEN_QUOTA_ENABLED"] = "true"
    os.environ["FOOTMARKS_DEFAULT_MONTHLY_TOKEN_LIMIT"] = str(args.token_limit)
    os.environ["FOOTMARKS_PUBLIC_REGISTRATION_ENABLED"] = "false"
    sys.path.insert(0, str(ROOT.parent))

    import httpx
    import uvicorn
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    import app.agent.runtime as runtime_module
    from app.agent.analyzer import RequirementAnalyzer
    from app.agent.factual import FactualAnswerer
    from app.agent.llm import OpenAICompatibleTransport, StructuredLLMClient
    from app.agent.observability import RecordingAgentObserver
    from app.agent.quota import TokenQuota
    from app.agent.tools.amap import AmapWebClient
    from app.core.config import get_settings
    from app.database import Base, engine, SessionLocal
    from app.main import create_app
    from app.models import AgentToolRun, ChatMessage, Record, RecordType, Trip, User
    from app.security import hash_password
    from app.storage import DisabledObjectStorage

    settings = get_settings()
    require(settings.database_url == f"sqlite:///{database_path.as_posix()}", "database isolation failed")
    Base.metadata.create_all(engine)
    fixtures = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    dataset = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    available = {case["id"]: case for case in dataset["cases"]}
    require(all(case_id in available for case_id in args.cases), "unknown case ID")
    require(all(
        case.get("setup", {}).get("account") == "alice"
        and set(case.get("setup", {})) == {"account"}
        and all(step.get("action") == "message" and step.get("account") == "alice"
                for step in case["steps"])
        for case_id, case in available.items() if case_id in args.cases
    ), "pilot supports only Alice message cases without additional setup")
    password = secrets.token_urlsafe(24)
    user_ids = {}
    with SessionLocal() as db:
        for alias, account in fixtures["accounts"].items():
            user = User(username=f"eval_{alias}", password_hash=hash_password(password), monthly_token_limit=args.token_limit)
            db.add(user)
            db.flush()
            user_ids[alias] = user.id
            for item in account["trips"]:
                trip = Trip(user_id=user.id, province_code=item["city_code"][:2] + "0000",
                            city_code=item["city_code"], city_name=item["city"],
                            start_date=date.fromisoformat(item["start_date"]), end_date=date.fromisoformat(item["end_date"]))
                db.add(trip)
                db.flush()
                for record in item["records"]:
                    db.add(Record(trip_id=trip.id, type=RecordType(record["type"]), name=record["name"],
                                  date=date.fromisoformat(record["date"]), cost=record["cost"], rating=record["rating"]))
        db.commit()

    model_outputs = []
    requirements = []
    class FrozenAnalyzer(RequirementAnalyzer):
        def __init__(self, *arguments, **kwargs):
            super().__init__(*arguments, **kwargs, today_provider=lambda: date(2026, 10, 8))

        def analyze(self, *arguments, **kwargs):
            value = super().analyze(*arguments, **kwargs)
            requirements.append(value.model_dump(mode="json"))
            return value

    class FrozenFactual(FactualAnswerer):
        def __init__(self, *arguments, **kwargs):
            super().__init__(*arguments, **kwargs, today_provider=lambda: date(2026, 10, 8))

    class CaptureLLM:
        def __init__(self, client):
            self.client = client

        def complete_structured(self, **kwargs):
            value = self.client.complete_structured(**kwargs)
            model_outputs.append({"model": kwargs["output_model"].__name__, "output": value.model_dump(mode="json")})
            return value

        def complete_structured_stream(self, **kwargs):
            value = self.client.complete_structured_stream(**kwargs)
            model_outputs.append({"model": kwargs["output_model"].__name__, "output": value.model_dump(mode="json")})
            return value

    runtime_module.RequirementAnalyzer = FrozenAnalyzer
    runtime_module.FactualAnswerer = FrozenFactual
    provider = SnapshotProvider(fixtures)
    # Only the AMap transport is replaced. LLM uses the configured live provider.
    transport = OpenAICompatibleTransport(settings)
    observer = RecordingAgentObserver()
    runtime = runtime_module.AgentRuntime(settings, llm_client=CaptureLLM(StructuredLLMClient(transport)),
                                          observer=observer, amap_transport=provider)
    application = create_app(settings, storage=DisabledObjectStorage(), agent_runtime=runtime)
    quota = TokenQuota(SessionLocal, args.token_limit)
    if args.offline_check:
        amap = AmapWebClient("evaluation-only", transport=provider)
        require(len(amap.search_verified_pois("南京", "food")["pois"]) == 9, "food snapshot mismatch")
        require(len(amap.search_verified_pois("南京", "attraction")["pois"]) == 10, "attraction snapshot mismatch")
        require(amap.resolve_adcode("南京") == "320100", "district mismatch")
        require(amap.measure_distance(fixtures["tool_snapshots"]["pois"][0]["location"],
                                      fixtures["tool_snapshots"]["pois"][1]["location"], mode=0) == 5200,
                "distance mismatch")
        with Session(engine) as db:
            counts = {alias: len(db.scalars(select(Trip).where(Trip.user_id == uid)).all()) for alias, uid in user_ids.items()}
        require(counts == {"alice": 4, "bob": 1}, "history isolation mismatch")
        from fastapi.testclient import TestClient
        with TestClient(application) as client:
            require(client.get("/api/v1/health").status_code == 200, "health failed")
            require(client.get("/api/v1/auth/me").status_code == 401, "anonymous access accepted")
            login = client.post("/api/v1/auth/login", json={"username": "eval_alice", "password": password})
            require(login.status_code == 200, "isolated login failed")
            client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
            require(client.get("/api/v1/auth/me").json()["username"] == "eval_alice", "wrong identity")
        save(output / "offline-check.json", {"database_isolated": True, "trip_counts": counts,
                                              "tool_snapshots_checked": True, "llm_calls": 0})
        transport.close()
        print("offline-check passed; no model requests")
        return

    save(output / "manifest.json", {"track": "A", "pilot": True, "model": settings.llm_model,
        "temperature": 0, "started_at": datetime.now(timezone.utc).isoformat(),
        "cases": args.cases, "repetitions": 1, "token_limit": args.token_limit,
        "code_commit": os.environ.get("EVALUATION_CODE_COMMIT", "unknown"),
        "source_sha256": {str(path.relative_to(ROOT.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted((ROOT.parent / "app").rglob("*.py"))},
        "case_sha256": hashlib.sha256((ROOT / "cases.json").read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256((ROOT / "fixtures.json").read_bytes()).hexdigest(),
        "timing_scope": "server-loopback HTTP, fixed AMap snapshots, excludes Nginx and Android",
        "total_timeout_seconds": settings.agent_total_timeout_seconds,
        "stage_timeout_seconds": settings.agent_stage_timeout_seconds,
        "llm_max_retries": settings.llm_max_retries})
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, log_level="warning"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = monotonic() + 10
    while not server.started and monotonic() < deadline:
        sleep(0.05)
    require(server.started, "pilot HTTP server failed to start")
    results = []
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180) as client:
            login = client.post("/api/v1/auth/login", json={"username": "eval_alice", "password": password})
            login.raise_for_status()
            client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
            for case_id in args.cases:
                case = next(case for case in dataset["cases"] if case["id"] == case_id)
                conversation = client.post("/api/v1/agent/conversations")
                conversation.raise_for_status()
                conversation_id = conversation.json()["id"]
                for index, step in enumerate(case["steps"], start=1):
                    trace_start, model_start, requirement_start, tool_start = len(observer.events), len(model_outputs), len(requirements), len(provider.calls)
                    before = quota.balance(user_ids["alice"])
                    started = monotonic()
                    row = {"case_id": case_id, "step": index, "message": step["message"], "status": "needs_review"}
                    try:
                        with client.stream("POST", "/api/v1/agent/chat/stream", json={
                            "message": step["message"], "conversation_id": conversation_id,
                            "client_message_id": secrets.token_hex(16),
                        }) as response:
                            row["http_status"] = response.status_code
                            row["request_id"] = response.headers.get("X-Request-ID")
                            if response.is_success:
                                row.update(read_sse(response, started))
                            else:
                                response.read()
                                row.update(final_event="http_error", error=response.text, termination_ms=(monotonic()-started)*1000)
                    except Exception as error:
                        row.update(final_event="client_error", error=type(error).__name__, termination_ms=(monotonic()-started)*1000)
                    row["requirements"] = requirements[requirement_start:]
                    row["model_outputs"] = model_outputs[model_start:]
                    row["stage_events"] = [event.model_dump(mode="json", exclude_none=True) for event in observer.events[trace_start:]]
                    row["provider_calls"] = provider.calls[tool_start:]
                    after = quota.balance(user_ids["alice"])
                    row["usage_delta"] = {key: after[key] - before[key] for key in ("input_tokens", "output_tokens", "fallback_tokens", "used")}
                    with SessionLocal() as db:
                        runs = db.scalars(select(AgentToolRun).join(
                            ChatMessage, AgentToolRun.source_message_id == ChatMessage.id
                        ).where(ChatMessage.request_id == row["request_id"])).all()
                        row["tool_runs"] = [
                            {**{column.name: getattr(run, column.name) for column in AgentToolRun.__table__.columns},
                             "result_json": run.tool_result.result_json if run.tool_result else None}
                            for run in runs
                        ]
                    # JSON serializer converts timestamps, not credentials.
                    row["tool_runs"] = json.loads(json.dumps(row["tool_runs"], default=str))
                    results.append(row)
                    save(output / "results.json", results)
                    save(output / "usage.json", after)
                    print(f"{case_id}/{index} terminal={row.get('final_event')} used={after['used']} first_body_ms={row.get('first_body_ms')}", flush=True)
                    if row.get("final_event") != "completed":
                        print("pilot stopped after non-completed response; inspect result before retry", flush=True)
                        return
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        transport.close()


if __name__ == "__main__":
    main()
