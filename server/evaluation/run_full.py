"""Sequential live-model evaluation against independent SQLite and fixed tools."""

import argparse
import hashlib
import json
import platform
import os
import random
import secrets
import socket
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit

from fixtures_support import FullSnapshotProvider, inspect_case, seed_case
from grading import grade_step, summarize
from run_pilot import read_sse, require, save

ROOT = Path(__file__).resolve().parent


def batch_reservation_allowed(usage, reserve, ceiling):
    return sum(usage.values()) + reserve <= ceiling


def schedule(cases, repetitions):
    result = [(repeat, case) for repeat in range(1, repetitions + 1) for case in cases]
    random.Random(20261008).shuffle(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--phase", choices=("trial", "formal"), default="trial")
    parser.add_argument("--offline-check", action="store_true")
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    require(any(part.startswith(".test-run-") for part in output.parts), "output must be inside .test-run-*")
    output.mkdir(parents=True, exist_ok=False)
    database_path = output / "evaluation.sqlite"
    cap = 400000 if args.phase == "trial" else 1200000
    repetitions = 1 if args.phase == "trial" else 3
    os.environ.update(FOOTMARKS_DATABASE_URL=f"sqlite:///{database_path.as_posix()}",
                      FOOTMARKS_TOKEN_SECRET=secrets.token_urlsafe(48), FOOTMARKS_TOKEN_QUOTA_ENABLED="true",
                      FOOTMARKS_DEFAULT_MONTHLY_TOKEN_LIMIT=str(cap), FOOTMARKS_PUBLIC_REGISTRATION_ENABLED="false")
    sys.path.insert(0, str(ROOT.parent))
    import httpx
    import uvicorn
    from sqlalchemy import select
    import app.agent.runtime as runtime_module
    from app.agent.analyzer import RequirementAnalyzer
    from app.agent.factual import FactualAnswerer
    from app.agent.llm import OpenAICompatibleTransport, StructuredLLMClient
    from app.agent.observability import RecordingAgentObserver
    from app.agent.quota import QuotaExceeded, TokenQuota
    from app.core.config import get_settings
    from app.database import Base, engine, SessionLocal
    from app.main import create_app
    from app.models import AgentToolRun, ChatMessage, MonthlyTokenUsage
    from app.security import hash_password
    from app.storage import DisabledObjectStorage

    settings = get_settings()
    require(settings.database_url == f"sqlite:///{database_path.as_posix()}", "database isolation failed")
    Base.metadata.create_all(engine)
    fixtures = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    dataset = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    cases = [case for case in dataset["cases"] if not args.cases or case["id"] in args.cases]
    require(not args.cases or len(cases) == len(set(args.cases)), "unknown case")
    password = secrets.token_urlsafe(24)
    password_hash = hash_password(password)
    outputs, requirements, states, knowledge, upstream = [], [], [], [], []
    limit_reached = threading.Event()

    def total_usage():
        with SessionLocal() as db:
            rows = db.scalars(select(MonthlyTokenUsage)).all()
            return {field: sum(getattr(row, field) for row in rows) for field in ("input_tokens", "output_tokens", "fallback_tokens", "reserved_tokens")}

    class CappedTransport(OpenAICompatibleTransport):
        def _reserve(self, system_prompt, user_prompt):
            usage = total_usage()
            reserve = len(system_prompt.encode("utf-8")) + len(user_prompt.encode("utf-8")) + self._max_output_tokens
            if not batch_reservation_allowed(usage, reserve, cap):
                limit_reached.set()
                raise QuotaExceeded("Evaluation batch token ceiling reached")
            return super()._reserve(system_prompt, user_prompt)

    class FrozenAnalyzer(RequirementAnalyzer):
        def __init__(self, *arguments, **kwargs):
            super().__init__(*arguments, **kwargs, today_provider=lambda: date(2026, 10, 8))

        def analyze(self, *arguments, **kwargs):
            result = super().analyze(*arguments, **kwargs)
            requirements.append(result.model_dump(mode="json"))
            return result

    class FrozenFactual(FactualAnswerer):
        def __init__(self, *arguments, **kwargs):
            super().__init__(*arguments, **kwargs, today_provider=lambda: date(2026, 10, 8))

    class CaptureLLM:
        def __init__(self, client):
            self.client = client

        def complete_structured(self, **kwargs):
            result = self.client.complete_structured(**kwargs)
            outputs.append({"model": kwargs["output_model"].__name__, "output": result.model_dump(mode="json")})
            return result

        def complete_structured_stream(self, **kwargs):
            result = self.client.complete_structured_stream(**kwargs)
            outputs.append({"model": kwargs["output_model"].__name__, "output": result.model_dump(mode="json")})
            return result

    build_graph = runtime_module.build_agent_graph

    class CaptureGraph:
        def __init__(self, graph):
            self.graph = graph

        def invoke(self, initial):
            result = self.graph.invoke(initial)
            def convert(value):
                if hasattr(value, "model_dump"):
                    return value.model_dump(mode="json")
                return str(value)
            states.append(json.loads(json.dumps(result, default=convert, ensure_ascii=False)))
            return result

    class CaptureRuntime(runtime_module.AgentRuntime):
        def _search_knowledge(self, db, user_id, city, preferences, *, kind=None):
            results = super()._search_knowledge(db, user_id, city, preferences, kind=kind)
            knowledge.append({"user_id": user_id, "city": city, "results": [entry.model_dump(mode="json") for entry in results]})
            return results

    runtime_module.RequirementAnalyzer = FrozenAnalyzer
    runtime_module.FactualAnswerer = FrozenFactual
    runtime_module.build_agent_graph = lambda **kwargs: CaptureGraph(build_graph(**kwargs))
    provider = FullSnapshotProvider(fixtures)
    transport = CappedTransport(settings)
    transport._client.event_hooks.setdefault("request", []).append(lambda request: upstream.append({"method": request.method, "at": datetime.now(timezone.utc).isoformat()}))
    observer = RecordingAgentObserver()
    runtime = CaptureRuntime(settings, llm_client=CaptureLLM(StructuredLLMClient(transport)), observer=observer, amap_transport=provider)
    application = create_app(settings, storage=DisabledObjectStorage(), agent_runtime=runtime)
    quota = TokenQuota(SessionLocal, cap)
    app_root = Path(runtime_module.__file__).resolve().parents[1]
    manifest = {"track": "A", "phase": args.phase, "model": settings.llm_model, "temperature": 0,
                "structured_output_mode": settings.llm_structured_output_mode,
                "started_at": datetime.now(timezone.utc).isoformat(), "repetitions": repetitions, "token_ceiling": cap,
                "code_commit": os.environ.get("EVALUATION_CODE_COMMIT", "unknown"),
                "source_sha256": {str(path.relative_to(app_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(app_root.rglob("*.py"))},
                "resource_sha256": {str(path.relative_to(app_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(app_root.rglob("*.json"))},
                "evaluation_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(ROOT.glob("*.py"))},
                "case_sha256": hashlib.sha256((ROOT / "cases.json").read_bytes()).hexdigest(),
                "fixture_sha256": hashlib.sha256((ROOT / "fixtures.json").read_bytes()).hexdigest(),
                "timing_scope": "server-loopback authenticated SSE; real LLM; synthetic AMap; excludes Android/Nginx",
                "total_timeout_seconds": settings.agent_total_timeout_seconds, "stage_timeout_seconds": settings.agent_stage_timeout_seconds,
                "llm_max_retries": settings.llm_max_retries, "max_output_tokens": settings.llm_max_output_tokens,
                "order": [[repeat, case["id"]] for repeat, case in schedule(cases, repetitions)], "concurrency": 1,
                "python": platform.python_version(), "platform": platform.platform(), "cpu_count": os.cpu_count(),
                "warmup": "H01, separate repeat=0; included in batch ledger" if args.phase == "formal" else "no warmup; exploratory trial",
                "login_setup": "unique loopback source IP per simulated household; actual login limiter retained"}
    manifest["provider_host"] = urlsplit(settings.llm_base_url or "").hostname
    save(output / "manifest.json", manifest)
    (output / "cases.json").write_bytes((ROOT / "cases.json").read_bytes())
    (output / "fixtures.json").write_bytes((ROOT / "fixtures.json").read_bytes())
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, log_level="warning"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = monotonic() + 10
    while not server.started and monotonic() < deadline:
        sleep(.05)
    require(server.started, "HTTP server did not start")
    results = []
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180) as client:
            require(client.get("/api/v1/health").status_code == 200, "health failed")
            require(client.get("/api/v1/auth/me").status_code == 401, "anonymous access accepted")
            queue = schedule(cases, repetitions)
            if args.phase == "formal" and not args.offline_check:
                queue.insert(0, (0, next(case for case in dataset["cases"] if case["id"] == "H01")))
            for order_index, (repeat, case) in enumerate(queue, 2):
                prefix = f"eval_{case['id']}_{repeat}"
                with SessionLocal() as db:
                    users, refs, conversations = seed_case(db, fixtures, case, prefix, password_hash, cap)
                    original_ids = set(db.scalars(select(ChatMessage.id).where(ChatMessage.conversation_id.in_(list(conversations.values())))).all())
                headers = {}
                # Account setup uses a distinct loopback IP per simulated household.
                # Keep the real login limiter; login is outside Agent timing scope.
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", transport=httpx.HTTPTransport(local_address=f"127.0.0.{order_index}")) as login_client:
                    for alias in users:
                        response = login_client.post("/api/v1/auth/login", json={"username": f"{prefix}_{alias}", "password": password})
                        response.raise_for_status()
                        headers[alias] = {"Authorization": "Bearer " + response.json()["access_token"]}
                for ref in case["setup"].get("knowledge", []):
                    owner = fixtures["knowledge"][ref]["account"]
                    other = "bob" if owner == "alice" else "alice"
                    require(client.get(f"/api/v1/agent/knowledge/{refs[ref]}", headers=headers[other]).status_code == 404, "cross-account knowledge exposed")
                provider.configure(case["setup"])
                for index, step in enumerate(case["steps"], 1):
                    alias = step["account"]
                    label = step["conversation"]
                    if label not in conversations or step["action"] == "new_conversation":
                        response = client.post("/api/v1/agent/conversations", headers=headers[alias])
                        response.raise_for_status()
                        conversations[label] = response.json()["id"]
                        other = "bob" if alias == "alice" else "alice"
                        require(client.get(f"/api/v1/agent/conversations/{conversations[label]}/messages", headers=headers[other]).status_code == 404, "cross-account conversation exposed")
                    if args.offline_check or step["action"] == "new_conversation":
                        continue
                    starts = [len(collection) for collection in (observer.events, outputs, requirements, provider.calls, states, knowledge, upstream)]
                    before = quota.balance(users[alias])
                    started = monotonic()
                    row = {"case_id": case["id"], "repeat": repeat, "step": index, "suite": case["suite"], "category": case["category"], "message": step["message"]}
                    try:
                        with client.stream("POST", "/api/v1/agent/chat/stream", headers=headers[alias], json={"message": step["message"], "conversation_id": conversations[label], "client_message_id": secrets.token_hex(16)}) as response:
                            row.update(http_status=response.status_code, request_id=response.headers.get("X-Request-ID"))
                            if response.is_success:
                                row.update(read_sse(response, started))
                            else:
                                response.read()
                                row.update(final_event="http_error", error=response.text, termination_ms=(monotonic()-started)*1000)
                    except Exception as error:
                        row.update(final_event="client_error", error=f"{type(error).__name__}: {error}", termination_ms=(monotonic()-started)*1000)
                    row.update(requirements=requirements[starts[2]:], model_outputs=outputs[starts[1]:],
                               stage_events=[event.model_dump(mode="json", exclude_none=True) for event in observer.events[starts[0]:]],
                               provider_calls=provider.calls[starts[3]:], state=states[-1] if len(states) > starts[4] else {},
                               knowledge_trace=knowledge[starts[5]:], llm_http_calls=len(upstream)-starts[6])
                    after = quota.balance(users[alias])
                    row["usage_delta"] = {key: after[key]-before[key] for key in ("input_tokens", "output_tokens", "fallback_tokens", "used")}
                    with SessionLocal() as db:
                        runs = db.scalars(select(AgentToolRun).join(ChatMessage, AgentToolRun.source_message_id == ChatMessage.id).where(ChatMessage.request_id == row.get("request_id"))).all()
                        row["tool_runs"] = [{**{column.name: getattr(run, column.name) for column in AgentToolRun.__table__.columns}, "result_json": run.tool_result.result_json if run.tool_result else None} for run in runs]
                        row["database"] = inspect_case(db, users, conversations, refs, original_ids)
                    row = json.loads(json.dumps(row, default=str))
                    row["grade"] = grade_step(step, row, fixtures)
                    if repeat == 0:
                        save(output / "warmup.json", row)
                        require(row.get("final_event") == "completed", "warmup failed; formal samples not started")
                        continue
                    results.append(row)
                    save(output / "results.json", results)
                    save(output / "summary.json", summarize(results, cases, repetitions))
                    save(output / "usage.json", total_usage())
                    print(f"{case['id']} r{repeat} step{index} terminal={row.get('final_event')} automatic={row['grade']['automatic_status']} tokens={sum(total_usage().values())}", flush=True)
                    if limit_reached.is_set():
                        break
                if limit_reached.is_set():
                    break
            if args.offline_check:
                require(not upstream, "offline check called model")
                save(output / "offline-check.json", {"cases_seeded": len(cases) * repetitions, "accounts_isolated": True, "llm_calls": 0})
            save(output / "review.json", [{"case_id": row["case_id"], "repeat": row["repeat"], "step": row["step"], "message": row["message"], "answer": row.get("answer"), "grade": row["grade"], "request_id": row.get("request_id")} for row in results])
    finally:
        manifest.update(ended_at=datetime.now(timezone.utc).isoformat(), budget_aborted=limit_reached.is_set(), usage=total_usage())
        save(output / "manifest.json", manifest)
        server.should_exit = True
        thread.join(timeout=10)
        transport.close()
        engine.dispose()


if __name__ == "__main__":
    main()
