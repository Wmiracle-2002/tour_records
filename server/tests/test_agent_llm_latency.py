"""Regression cases for expensive thinking-only streams and bounded waiting."""
import json
import logging

import httpx
import pytest
from pydantic import BaseModel

from app.agent.budget import AgentBudget, AgentTimeoutError, AgentCancellation, AgentClientDisconnected, cancellation_context
from app.agent.llm import LLMInvalidResponseError, OpenAICompatibleTransport, StructuredLLMClient
from app.core.config import Settings


class Answer(BaseModel):
    answer: str


def config(**overrides):
    return Settings(_env_file=None, llm_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
                    llm_api_key='test-key', llm_model='deepseek-v4-pro-0813', **overrides)


def frame(value):
    return 'data: ' + json.dumps(value) + '\n\n'


@pytest.mark.parametrize('stream', [False, True])
def test_dashscope_deepseek_uses_non_thinking_for_both_paths(stream):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        if stream:
            return httpx.Response(200, text=frame({'choices': [{'delta': {'content': '{"answer":"ok"}'}}]}) + 'data: [DONE]\n\n')
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"answer":"ok"}'}, 'finish_reason': 'stop'}]})
    transport = OpenAICompatibleTransport(config(), http_transport=httpx.MockTransport(handle))
    client = StructuredLLMClient(transport)
    options = dict(system_prompt='Return JSON', user_prompt='hello', output_model=Answer)
    if stream:
        result = client.complete_structured_stream(**options, on_delta=lambda part: None)
    else:
        result = client.complete_structured(**options)
    assert result.answer == 'ok'
    assert requests[0]['enable_thinking'] is False
    assert requests[0]['max_tokens'] == 4096
    if stream:
        assert requests[0]['stream_options'] == {'include_usage': True}


@pytest.mark.parametrize('mode, expected', [('auto', None), ('enabled', True), ('disabled', False)])
def test_unknown_provider_only_receives_thinking_switch_when_explicit(mode, expected):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"answer":"ok"}'}}]})
    settings = Settings(_env_file=None, llm_base_url='https://provider.example/v1', llm_api_key='test-key',
                        llm_model='deepseek-v4-pro-0813', llm_thinking_mode=mode)
    transport = OpenAICompatibleTransport(settings, http_transport=httpx.MockTransport(handle))
    transport.complete_json(system_prompt='JSON', user_prompt='hi', output_model=Answer)
    transport.close()
    if expected is None:
        assert 'enable_thinking' not in requests[0]
    else:
        assert requests[0]['enable_thinking'] is expected


@pytest.mark.parametrize('stream', [False, True])
def test_length_finish_is_explicit_even_if_json_is_valid_and_is_not_retried(stream):
    calls = []
    def handle(request):
        calls.append(request)
        choice = {'finish_reason': 'length', 'delta' if stream else 'message': {'content': '{"answer":"partial"}'}}
        if stream:
            return httpx.Response(200, text=frame({'choices': [choice]}) + 'data: [DONE]\n\n')
        return httpx.Response(200, json={'choices': [choice]})
    transport = OpenAICompatibleTransport(config(), http_transport=httpx.MockTransport(handle))
    client = StructuredLLMClient(transport)
    with pytest.raises(LLMInvalidResponseError, match='output token limit'):
        if stream:
            client.complete_structured_stream(system_prompt='JSON', user_prompt='hi', output_model=Answer, on_delta=lambda part: None)
        else:
            client.complete_structured(system_prompt='JSON', user_prompt='hi', output_model=Answer)
    assert len(calls) == 1


def test_stream_logs_usage_and_finish_metadata_without_reasoning_text(caplog):
    secret = 'private reasoning must never be logged'
    text = (frame({'choices': [{'delta': {'reasoning_content': secret}}]})
            + frame({'choices': [{'delta': {'content': '{"answer":"ok"}'}}]})
            + frame({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})
            + frame({'choices': [], 'usage': {'prompt_tokens': 20, 'completion_tokens': 12,
                                             'completion_tokens_details': {'reasoning_tokens': 7}}})
            + 'data: [DONE]\n\n')
    transport = OpenAICompatibleTransport(config(), http_transport=httpx.MockTransport(lambda request: httpx.Response(200, text=text)))
    received = []
    with caplog.at_level(logging.INFO, logger='footmarks.agent.llm'):
        transport.complete_json_stream(system_prompt='private prompt', user_prompt='private query', output_model=Answer, on_delta=received.append)
    assert received == ['{"answer":"ok"}']
    assert 'reasoning_tokens=7' in caplog.text
    assert 'finish_reason=stop' in caplog.text
    assert 'content_chars=15' in caplog.text
    assert secret not in caplog.text and 'private prompt' not in caplog.text


@pytest.mark.parametrize('cancel', [False, True])
def test_reasoning_only_stream_checks_budget_and_cancellation_on_every_event(cancel):
    clock = [100.0]
    cancellation = AgentCancellation()
    closed = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(4):
                clock[0] += 1
                if cancel:
                    cancellation.cancel()
                yield frame({'choices': [{'delta': {'reasoning_content': 'hidden'}}]}).encode()
            yield b'data: [DONE]\n\n'
        def close(self):
            closed.append(True)
    transport = OpenAICompatibleTransport(config(), http_transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream())))
    budget = AgentBudget(total_timeout_seconds=10, stage_timeout_seconds=2, clock=lambda: clock[0])
    with cancellation_context(cancellation):
        with pytest.raises(AgentClientDisconnected if cancel else AgentTimeoutError):
            with budget.stage('itinerary_generator'):
                transport.complete_json_stream(system_prompt='JSON', user_prompt='hi', output_model=Answer, on_delta=lambda part: pytest.fail('No public content expected'))
    assert closed
    assert clock[0] <= 102


@pytest.mark.parametrize('stream', [False, True])
def test_partial_response_cannot_keep_socket_alive_past_wall_clock_deadline(stream):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Event, Thread
    from time import monotonic
    from app.agent.llm import LLMTimeoutError
    release = Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            try:
                self.wfile.write(b'data: {"choices":[')
                self.wfile.flush()
                for _ in range(30):
                    if release.wait(0.03):
                        break
                    self.wfile.write(b' ')
                    self.wfile.flush()
                release.wait(1)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = Settings(_env_file=None, llm_base_url=f'http://127.0.0.1:{server.server_port}',
                        llm_api_key='test-key', llm_model='test-model', llm_timeout_seconds=0.12)
    transport = OpenAICompatibleTransport(settings)
    try:
        started = monotonic()
        with pytest.raises(LLMTimeoutError):
            if stream:
                transport.complete_json_stream(system_prompt='JSON', user_prompt='hi', output_model=Answer, on_delta=lambda part: None)
            else:
                transport.complete_json(system_prompt='JSON', user_prompt='hi', output_model=Answer)
        assert monotonic() - started < 0.5
    finally:
        release.set()
        transport.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
