"""Bounded real-LLM/real-AMap latency probe, isolated from production data.

Instrumentation is confined to this process; spans are nested and must not be
summed across parent/child levels. Output may contain test answers, never keys.
"""
import argparse
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
from time import monotonic, sleep
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
ACTIVE_CASE = ContextVar('latency_case', default=None)
PARENT_SPAN = ContextVar('latency_parent', default=None)
SPANS = []
ORIGIN = monotonic()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def timed(name, operation):
    @wraps(operation)
    def run(*args, **kwargs):
        row = {'id': uuid4().hex, 'parent': PARENT_SPAN.get(), 'case_id': ACTIVE_CASE.get(),
               'name': name, 'start_ms': (monotonic() - ORIGIN) * 1000}
        started = monotonic()
        token = PARENT_SPAN.set(row['id'])
        try:
            result = operation(*args, **kwargs)
            row['status'] = 'ok'
            if name == 'poi_search':
                row['kind'] = kwargs.get('kind', args[2] if len(args) > 2 else None)
            return result
        except Exception as error:
            row.update(status='error', error_type=type(error).__name__)
            raise
        finally:
            row['duration_ms'] = (monotonic() - started) * 1000
            row['end_ms'] = (monotonic() - ORIGIN) * 1000
            SPANS.append(row)
            PARENT_SPAN.reset(token)
    return run


def instrument(owner, attribute, label):
    setattr(owner, attribute, timed(label, getattr(owner, attribute)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--offline-check', action='store_true')
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--token-limit', type=int, default=40000)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    dataset = json.loads((ROOT / 'latency_cases.json').read_text(encoding='utf-8'))
    assert len(dataset['cases']) == 4 and dataset['token_limit'] == 40000
    assert 0 < args.token_limit <= 40000
    if args.cases:
        selected = set(args.cases)
        assert len(selected) == len(args.cases)
        dataset['cases'] = [case for case in dataset['cases'] if case['id'] in selected]
        assert len(dataset['cases']) == len(selected), 'Unknown latency case'
    database = output / 'isolated.sqlite'
    os.environ.update(FOOTMARKS_DATABASE_URL='sqlite:///' + database.as_posix(),
        FOOTMARKS_TOKEN_SECRET=secrets.token_urlsafe(48), FOOTMARKS_TOKEN_QUOTA_ENABLED='true',
        FOOTMARKS_DEFAULT_MONTHLY_TOKEN_LIMIT=str(args.token_limit), FOOTMARKS_PUBLIC_REGISTRATION_ENABLED='false')
    sys.path.insert(0, str(ROOT.parent))
    import httpx
    import uvicorn
    from sqlalchemy import select
    import app.agent.graph as graph_module
    from app.agent.analyzer import RequirementAnalyzer
    from app.agent.collector import ReActCollector
    from app.agent.generator import StructuredItineraryGenerator
    from app.agent.llm import OpenAICompatibleTransport, StructuredLLMClient
    from app.agent.memory import ConversationMemoryService
    from app.agent.observability import RecordingAgentObserver
    from app.agent.quota import QuotaExceeded, TokenQuota
    from app.agent.response import FinalResponseGenerator
    from app.agent.reviser import LocalItineraryReviser
    from app.agent.runtime import AgentRuntime
    from app.agent.tools.amap import AmapWebClient, default_amap_transport
    from app.agent.tools.budget import EstimateBudgetTool
    from app.agent.validator import ItineraryValidator
    from app.core.config import get_settings
    from app.database import Base, engine, SessionLocal
    from app.main import create_app
    from app.models import ChatMessage, KnowledgeEntry, MonthlyTokenUsage, TokenUsageCall, User, UserPreference
    from app.security import hash_password
    from app.storage import DisabledObjectStorage
    from run_pilot import read_sse

    settings = get_settings()
    assert settings.database_url == 'sqlite:///' + database.as_posix()
    Base.metadata.create_all(engine)
    password = secrets.token_urlsafe(24)
    with SessionLocal() as db:
        user = User(username='latency_probe', password_hash=hash_password(password), monthly_token_limit=args.token_limit)
        db.add(user)
        db.commit()
        uid = user.id

    # Atomic quota applies to the only account and includes every retry/summary.
    def usage():
        with SessionLocal() as db:
            rows = db.scalars(select(MonthlyTokenUsage)).all()
            return {key: sum(getattr(row, key) for row in rows)
                    for key in ('input_tokens', 'output_tokens', 'fallback_tokens', 'reserved_tokens')}

    llm_calls = []
    class ProbeTransport(OpenAICompatibleTransport):
        def _reserve(self, system_prompt, user_prompt):
            call = {'case_id': ACTIVE_CASE.get(), 'input_utf8_bytes': len(system_prompt.encode()) + len(user_prompt.encode()),
                    'start_ms': (monotonic() - ORIGIN) * 1000}
            try:
                result = super()._reserve(system_prompt, user_prompt)
            except QuotaExceeded:
                call['quota_rejected'] = True
                llm_calls.append(call)
                raise
            assert result is not None, 'Unmetered LLM call blocked'
            call['quota_id'] = result
            llm_calls.append(call)
            return result

    instrument(ConversationMemoryService, 'build_context', 'memory_context')
    instrument(ConversationMemoryService, 'record_tool_run', 'tool_trace_save')
    instrument(RequirementAnalyzer, 'analyze', 'requirement_analyzer')
    instrument(ReActCollector, 'collect_round', 'react_round')
    instrument(graph_module, '_initialize_information_node', 'initialize_information')
    AgentRuntime._search_knowledge = staticmethod(timed('knowledge_search', AgentRuntime._search_knowledge))
    instrument(EstimateBudgetTool, 'run', 'budget_estimate')
    instrument(AmapWebClient, 'search_verified_pois', 'poi_search')
    instrument(StructuredItineraryGenerator, 'generate', 'itinerary_generator')
    instrument(ItineraryValidator, 'validate', 'validator')
    instrument(LocalItineraryReviser, 'revise', 'reviser')
    instrument(FinalResponseGenerator, 'generate', 'final_response')
    instrument(AgentRuntime, 'run', 'agent_runtime')

    first_delta = []
    class CaptureLLM:
        def __init__(self, client):
            self.client = client
        def complete_structured(self, **kwargs):
            return timed('llm:' + kwargs['output_model'].__name__, self.client.complete_structured)(**kwargs)
        def complete_structured_stream(self, **kwargs):
            callback = kwargs['on_delta']
            observed = False
            def delta(text):
                nonlocal observed
                if text and not observed:
                    first_delta.append({'case_id': ACTIVE_CASE.get(), 'at_ms': (monotonic() - ORIGIN) * 1000})
                    observed = True
                callback(text)
            kwargs['on_delta'] = delta
            return timed('llm_stream:' + kwargs['output_model'].__name__, self.client.complete_structured_stream)(**kwargs)

    transport = ProbeTransport(settings)
    observer = RecordingAgentObserver()
    amap_http = timed('amap_http', default_amap_transport)
    runtime = AgentRuntime(settings, llm_client=CaptureLLM(StructuredLLMClient(transport)),
                           observer=observer, amap_transport=amap_http)
    application = create_app(settings, storage=DisabledObjectStorage(), agent_runtime=runtime)
    original_run = runtime.run
    def labeled_run(*arguments, **keywords):
        token = ACTIVE_CASE.set(application.state.latency_case_id)
        try:
            return original_run(*arguments, **keywords)
        finally:
            ACTIVE_CASE.reset(token)
    runtime.run = labeled_run
    manifest = {'date': '2026-10-21', 'model': settings.llm_model, 'cases': dataset,
        'token_cap': args.token_limit, 'production_database_mounted': False, 'real_amap': not args.offline_check,
        'timing_scope': 'server loopback HTTP/SSE; excludes Nginx, public network and Android',
        'timeout_total': settings.agent_total_timeout_seconds, 'timeout_stage': settings.agent_stage_timeout_seconds,
        'source_sha256': {str(p.relative_to(Path('/app'))): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path('/app/app').rglob('*.py')},
        'started_at': datetime.now(timezone.utc).isoformat()}
    save(output / 'manifest.json', manifest)
    if args.offline_check:
        assert all(hasattr(owner, method) for owner, method in [(FinalResponseGenerator, 'generate'), (runtime, 'run')])
        save(output / 'offline-check.json', {'database_isolated': True, 'case_count': len(dataset['cases']), 'llm_calls': 0})
        transport.close()
        print('Offline check passed; 0 LLM calls', flush=True)
        return
    assert settings.llm_api_key and settings.amap_web_key
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, log_level='warning'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = monotonic() + 15
    while not server.started and monotonic() < deadline:
        sleep(0.05)
    assert server.started
    results = []
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=max(180, settings.agent_total_timeout_seconds + 30)) as client:
            login = client.post('/api/v1/auth/login', json={'username': 'latency_probe', 'password': password})
            login.raise_for_status()
            client.headers['Authorization'] = 'Bearer ' + login.json()['access_token']
            for case in dataset['cases']:
                conversation = client.post('/api/v1/agent/conversations')
                conversation.raise_for_status()
                cid = conversation.json()['id']
                if case['setup'] == 'knowledge':
                    response = client.post('/api/v1/agent/knowledge', json={'title': '南京历史文化与饮食提示',
                        'body': '想了解历史文化可以关注南京博物院、夫子庙。用餐请确认不放辣椒，收藏内容不代表当前营业情况。',
                        'city_code': '320100', 'city_name': '南京市', 'category': 'travel_guide', 'tags': ['历史文化', '不吃辣']})
                    response.raise_for_status()
                if case['setup'] == 'long_conversation':
                    with SessionLocal() as db:
                        for index in range(26):
                            # Artificial history, not paid warm-up calls. Creates memory pressure.
                            content = ('我们讨论南京三日游，关注历史文化、景点安排、适合三餐的当地餐饮，不需要具体路线。' * 7
                                       + f' 这是第{index + 1}条预置历史。')
                            db.add(ChatMessage(conversation_id=cid, role='user' if index % 2 == 0 else 'assistant', content=content))
                        db.commit()
                case_token = ACTIVE_CASE.set(case['id'])
                # ContextVars on the client do not cross HTTP; bind the label at the
                # runtime boundary using the matching X-Request-ID, single concurrency.
                application.state.latency_case_id = case['id']
                before_usage = usage()
                started = monotonic()
                row = dict(case, request_id='latency-' + case['id'] + '-' + uuid4().hex[:12],
                           started_ms=(started - ORIGIN) * 1000, usage_before=before_usage)
                observer_offset = len(observer.events)
                try:
                    with client.stream('POST', '/api/v1/agent/chat/stream', headers={'X-Request-ID': row['request_id']},
                        json={'message': case['message'], 'conversation_id': cid, 'client_message_id': uuid4().hex}) as response:
                        row['http_status'] = response.status_code
                        response.raise_for_status()
                        row.update(read_sse(response, started))
                except Exception as error:
                    row.update(final_event='client_error', error_type=type(error).__name__)
                finally:
                    row['wall_ms'] = (monotonic() - started) * 1000
                    row['usage_after'] = usage()
                    row['agent_events'] = [event.model_dump(mode='json') for event in observer.events[observer_offset:]]
                    ACTIVE_CASE.reset(case_token)
                results.append(row)
                save(output / 'results.json', results)
                save(output / 'spans.json', SPANS)
                save(output / 'llm-calls.json', llm_calls)
                save(output / 'stream-first-delta.json', first_delta)
                with SessionLocal() as db:
                    ledger = [{'id': call.id, 'input_tokens': call.input_tokens, 'output_tokens': call.output_tokens,
                               'reserved_tokens': call.reserved_tokens, 'status': call.status}
                              for call in db.scalars(select(TokenUsageCall)).all()]
                save(output / 'usage-ledger.json', ledger)
                print(json.dumps({'case': case['id'], 'terminal': row['final_event'], 'wall_ms': row['wall_ms'], 'usage': usage()}), flush=True)
                if row['final_event'] != 'completed':
                    break  # Keep failures; do not silently run extra paid requests.
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        transport.close()
        save(output / 'usage.json', usage())


if __name__ == '__main__':
    main()
