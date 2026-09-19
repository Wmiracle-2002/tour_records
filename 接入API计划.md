# Footmarks LLM 与 Agent API 接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已完成的 Travel Agent V1 接入真实 LLM，通过受认证的 FastAPI 接口提供给 Android 智能规划页面使用。

**Architecture:** Android 只调用 Footmarks 服务端的 `POST /api/v1/agent/chat`，不保存或接触 LLM Key。服务端使用一个兼容 OpenAI Chat Completions JSON Schema 输出的适配器驱动 Requirement Analyzer、ReAct 决策、Itinerary Generator 和 Local Reviser；数据库、高德和预算 Tool 仍由服务端执行，Validator 和 Final Response 继续使用确定性代码。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、LangGraph、SQLAlchemy、httpx、pytest、Android/Kotlin、Retrofit、Hilt、Jetpack Compose。

**Spec:** [Agent架构.md](./Agent架构.md)

## Global Constraints

- LLM Key、模型名和服务地址只保存在服务器 `server/.env`，不得写入 Android、源码、日志或 Git。
- Android 只能访问 Footmarks HTTPS 域名，不得直接请求 LLM 或高德服务。
- V1 使用同步单轮接口；Android 可在当前页面显示多条消息，但服务端暂不保存会话历史。
- V1 不实现 Web Search、RAG、攻略知识库、服务端会话表和 SSE。
- LLM 只输出结构化数据，不直接执行 SQL、高德请求或预算计算。
- Tool 调用必须经过 `ToolLayer`，原始返回必须经过 Normalizer 后才能进入 State。
- Validator 保持纯程序逻辑；Final Response 保持确定性模板，首版不交给 LLM 润色。
- 每个信息需求最多尝试 3 次，ReAct 最多 8 轮，Validator/Reviser 最多 2 轮。
- 每完成一个任务都运行该任务定向测试；完成一个服务端任务后运行服务端 Agent 回归，完成一个 Android 任务后运行对应 JVM/UI 回归。
- 不修改或清空现有 `.env`；部署时只追加缺少的变量。

---

## 1. 接入步骤审查结论

### 1.1 当前已经具备

- `RequirementAnalyzer`、`ReActCollector`、`StructuredItineraryGenerator`、`LocalItineraryReviser` 都已通过 Protocol 预留 LLM 客户端接口。
- LangGraph 主流程、最大轮次、异常降级、Validator/Reviser 回路和结构化日志已经完成。
- Internal DB、预算和高德 Web API 已经统一接入 `ToolLayer`。
- FastAPI 已有 Bearer Token 鉴权，Android 已有 Retrofit、Token 存储和 401 自动刷新。
- Android 已有智能规划页面和输入框，只需要接入状态管理和网络请求。

### 1.2 仍然缺少

- 真实 LLM HTTP 传输和结构化输出适配器。
- ReAct 决策所需的 LLM Prompt 与输出校验。
- 按当前用户组装数据库 Tool、公共 Tool、LLM Client 和 LangGraph 的运行时入口。
- `POST /api/v1/agent/chat` 请求/响应模型和 FastAPI 路由。
- Android Agent 请求模型、ViewModel、消息列表和错误/加载状态。
- 真实模型、真实高德、服务器 HTTPS 和手机的端到端验收。

### 1.3 对原接入思路的修正

- 不在 Android 中接入模型 SDK。这样会暴露 LLM Key，也无法安全使用服务器数据库 Tool。
- 不让四个 Agent 节点各自实现一套供应商调用代码。它们共用一个结构化 LLM 客户端。
- 首版不依赖供应商原生 Tool Calling。LLM 返回现有 `ReActDecision` JSON，服务端再执行允许的 Tool，可降低供应商锁定。
- `/agent/chat` 首版只返回 `request_id` 和 `answer`。结构化 Itinerary 仍留在服务端 State，避免提前形成第二套 Android 行程展示协议。
- 首版不接 SSE。同步接口稳定后再为耗时反馈单独设计流式协议。

---

## 2. 首版 API 契约

### 请求

```http
POST /api/v1/agent/chat
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "message": "帮我规划南京三日游，预算 3000 元"
}
```

约束：

- `message` 去除首尾空白后长度为 1～2000 字符。
- 必须使用现有 Access Token。
- 一次请求对应一次独立 Agent 运行，不读取上一轮对话。

### 成功响应

```json
{
  "request_id": "95761b9d-e20a-4dbe-ae7d-cda86837d884",
  "answer": "为你整理了一份南京三日行程……"
}
```

### 错误语义

| HTTP 状态 | 场景 | 用户提示 |
|---|---|---|
| 401 | 未登录、Access Token 无效或刷新失败 | 请先登录或重新登录 |
| 422 | 消息为空或超过 2000 字符 | 请检查输入内容 |
| 502 | LLM 返回非法结构或上游调用失败 | 智能规划服务暂时不可用 |
| 503 | LLM 配置缺失 | 智能规划服务尚未配置 |
| 504 | LLM 请求超时 | 智能规划响应超时，请稍后重试 |

错误响应继续使用项目现有统一格式：

```json
{
  "error": {
    "code": "http_error",
    "message": "智能规划服务暂时不可用"
  }
}
```

---

### Task 1: 增加 LLM 服务端配置

**Files:**

- Modify: `server/app/core/config.py`
- Modify: `server/.env.example`
- Modify: `server/compose.yaml`
- Modify: `server/requirements.txt`
- Modify: `server/requirements-dev.txt`
- Create: `server/tests/test_agent_llm_config.py`

**Interfaces:**

- Produces: `Settings.llm_base_url`、`llm_api_key`、`llm_model`、`llm_timeout_seconds`、`llm_max_retries`。
- Consumes: 现有 `FOOTMARKS_` 环境变量前缀。

- [x] **Step 1: 编写配置失败测试**

```python
def test_llm_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("FOOTMARKS_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("FOOTMARKS_LLM_API_KEY", "test-key")
    monkeypatch.setenv("FOOTMARKS_LLM_MODEL", "test-model")
    settings = Settings(_env_file=None)
    assert settings.llm_base_url == "https://llm.example/v1"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_model == "test-model"
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd server && pytest tests/test_agent_llm_config.py -q`

Expected: FAIL，提示 `Settings` 没有 LLM 配置字段。

- [x] **Step 3: 增加配置字段**

```python
llm_base_url: str | None = None
llm_api_key: str | None = None
llm_model: str | None = None
llm_timeout_seconds: float = 30.0
llm_max_retries: int = 1
```

在 `server/.env.example` 和 `server/compose.yaml` 增加对应 `FOOTMARKS_LLM_*` 变量。将 `httpx==0.28.1` 移到生产 `requirements.txt`，从 `requirements-dev.txt` 删除重复声明。

- [x] **Step 4: 验证配置和 Compose**

Run: `cd server && pytest tests/test_agent_llm_config.py -q`

Expected: PASS。

Run: `docker compose --env-file server/.env.example -f server/compose.yaml config --quiet`

Expected: exit code 0，且不输出真实密钥。

- [x] **Step 5: 提交**

```bash
git add server/app/core/config.py server/.env.example server/compose.yaml server/requirements.txt server/requirements-dev.txt server/tests/test_agent_llm_config.py
git commit -m "Agent API: add LLM configuration"
```

---

### Task 2: 实现兼容 OpenAI Chat Completions 的结构化 LLM 客户端

**Files:**

- Create: `server/app/agent/llm.py`
- Create: `server/tests/test_agent_llm.py`

**Interfaces:**

- Produces: `OpenAICompatibleTransport.complete_json(system_prompt: str, user_prompt: str, output_model: type[T]) -> dict[str, Any]`。
- Produces: `StructuredLLMClient.complete_structured(system_prompt: str, user_prompt: str, output_model: type[T]) -> T`。
- Produces: `LLMNotConfiguredError`、`LLMTimeoutError`、`LLMUpstreamError`、`LLMInvalidResponseError`。
- Consumes: Task 1 的 LLM Settings。

- [x] **Step 1: 编写传输层和结构化输出失败测试**

测试函数固定为：

```text
test_structured_client_sends_json_schema_and_validates_result
test_missing_configuration_is_rejected_before_network_call
test_timeout_is_converted_to_llm_timeout_error
test_429_and_5xx_are_retried_once
test_invalid_json_and_schema_violation_are_rejected
test_api_key_is_absent_from_exception_text
```

第一项断言请求包含配置的模型、`temperature=0` 和 `output_model.model_json_schema()`，并断言返回值是对应 Pydantic 模型；其余用例分别断言异常类型、请求次数和异常文本中不存在测试 Key。

使用 `httpx.MockTransport`，测试不得访问真实网络。

- [x] **Step 2: 运行测试确认失败**

Run: `cd server && pytest tests/test_agent_llm.py -q`

Expected: FAIL，提示 `app.agent.llm` 不存在。

- [x] **Step 3: 实现最小传输接口**

```python
T = TypeVar("T", bound=BaseModel)

class OpenAICompatibleTransport:
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> dict[str, Any]:
        return self._request_chat_completions(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=output_model,
        )

class StructuredLLMClient:
    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> T:
        payload = self._transport.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=output_model,
        )
        return output_model.model_validate(payload)
```

请求体固定包含：

```json
{
  "model": "<configured-model>",
  "temperature": 0,
  "messages": [
    {"role": "system", "content": "system instructions"},
    {"role": "user", "content": "structured user input"}
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "PydanticModelName",
      "strict": true,
      "schema": {}
    }
  }
}
```

只重试连接错误、超时、HTTP 429 和 HTTP 5xx；HTTP 4xx、JSON 解析失败和 Pydantic 校验失败不重试。异常和日志中不得包含 API Key、完整 Prompt 或原始模型响应。

- [x] **Step 4: 运行客户端测试和既有 Analyzer/Generator/Reviser 测试**

Run: `cd server && pytest tests/test_agent_llm.py tests/test_agent_analyzer.py tests/test_agent_generator.py tests/test_agent_reviser.py -q`

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add server/app/agent/llm.py server/tests/test_agent_llm.py
git commit -m "Agent API: add structured LLM client"
```

---

### Task 3: 用 LLM 驱动 ReAct Tool 决策

**Files:**

- Modify: `server/app/agent/llm.py`
- Modify: `server/app/agent/collector.py`
- Create: `server/tests/test_agent_llm_decision.py`

**Interfaces:**

- Produces: `LLMReActDecisionClient.decide(context: ReActContext) -> ReActDecision`。
- Produces: 公共常量 `TOOL_INFORMATION_NEEDS`，供运行时过滤可用 Tool。
- Consumes: `ReActContext`、`ReActDecision`、`ToolCall` 和 Task 2 的 `StructuredLLMClient`。

- [ ] **Step 1: 编写 ReAct 决策失败测试**

```text
test_react_client_returns_one_valid_tool_call
test_react_client_can_stop_without_tool_call
test_react_client_rejects_unknown_tool_name
test_react_client_does_not_expose_chain_of_thought
```

用例分别断言：合法 Tool 名称和参数被保留；无 Tool Call 时正常停止；不在 `available_tools` 中的名称触发 `LLMInvalidResponseError`；观察器事件和日志中不存在 `ReActDecision.reason`。

测试输入必须包含需求、当前信息状态、已收集信息、可用 Tool 描述和当前轮次。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd server && pytest tests/test_agent_llm_decision.py -q`

Expected: FAIL，提示 `LLMReActDecisionClient` 不存在。

- [ ] **Step 3: 实现结构化决策客户端**

```python
class LLMReActDecisionClient:
    def __init__(self, client: StructuredLLMClient) -> None:
        self._client = client

    def decide(self, context: ReActContext) -> ReActDecision:
        decision = self._client.complete_structured(
            system_prompt=REACT_DECISION_SYSTEM_PROMPT,
            user_prompt=context.model_dump_json(indent=2),
            output_model=ReActDecision,
        )
        if decision.tool_call is not None:
            allowed = {tool.name for tool in context.available_tools}
            if decision.tool_call.name not in allowed:
                raise LLMInvalidResponseError("LLM selected an unavailable tool")
        return decision
```

Prompt 明确要求每轮最多一个 Tool Call；`reason` 只能是简短操作说明，不要求或保存思维链。

- [ ] **Step 4: 运行 ReAct 和 Collector 回归**

Run: `cd server && pytest tests/test_agent_llm_decision.py tests/test_agent_collector.py tests/test_agent_information.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add server/app/agent/llm.py server/app/agent/collector.py server/tests/test_agent_llm_decision.py
git commit -m "Agent API: connect LLM ReAct decisions"
```

---

### Task 4: 组装真实 Agent 运行时

**Files:**

- Create: `server/app/agent/runtime.py`
- Create: `server/tests/test_agent_runtime.py`

**Interfaces:**

- Produces: `AgentRunResult(request_id: str, answer: str)`。
- Produces: `AgentRuntime.run(message: str, user_id: int, db: Session) -> AgentRunResult`。
- Consumes: `StructuredLLMClient`、`LLMReActDecisionClient`、Internal DB Tool、预算 Tool、高德 Tool、LangGraph 和 `StructuredLoggingObserver`。

- [ ] **Step 1: 编写运行时失败测试**

```text
test_runtime_builds_user_scoped_tools_and_returns_final_response
test_runtime_does_not_expose_unsupported_amap_tools
test_runtime_passes_user_id_and_request_id_to_observer
test_runtime_propagates_typed_llm_errors
```

第一项建立两个用户的数据并断言当前运行只能看到传入 `user_id` 的记录；第二项断言 Tool 描述中没有 `geocode` 和 `reverse_geocode`；第三项检查事件关联字段；第四项断言四类 LLM 异常不会被改写成普通回答。

使用 Fake LLM Transport、测试数据库和 Fake AMap Transport，禁止真实网络。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd server && pytest tests/test_agent_runtime.py -q`

Expected: FAIL，提示 `app.agent.runtime` 不存在。

- [ ] **Step 3: 实现运行时组装**

```python
class AgentRunResult(BaseModel):
    request_id: str
    answer: str

class AgentRuntime:
    def run(self, message: str, user_id: int, db: Session) -> AgentRunResult:
        registry = ToolRegistry()
        for tool in create_internal_db_tools(db, user_id):
            registry.register(tool)
        for tool in create_budget_tools():
            registry.register(tool)
        for tool in create_amap_tools_from_settings(self._settings):
            if tool.name in TOOL_INFORMATION_NEEDS:
                registry.register(tool)
        graph = build_agent_graph(
            analyzer=analyzer,
            collector=collector,
            itinerary_generator=itinerary_generator,
            validator=validator,
            reviser=reviser,
            response_generator=response_generator,
            observer=self._observer,
        )
        initial = make_initial_state(message, user_id=user_id)
        result = graph.invoke(initial)
        return AgentRunResult(
            request_id=initial["request_id"],
            answer=result["final_response"],
        )
```

同一个 `StructuredLLMClient` 注入 Analyzer、Itinerary Generator 和 Local Reviser；`LLMReActDecisionClient` 包装该客户端后注入 Collector。`geocode` 和 `reverse_geocode` 暂无对应结构化 State，不暴露给 ReAct。

- [ ] **Step 4: 运行运行时、Graph 和端到端场景回归**

Run: `cd server && pytest tests/test_agent_runtime.py tests/test_agent_graph.py tests/test_agent_phase13.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add server/app/agent/runtime.py server/tests/test_agent_runtime.py
git commit -m "Agent API: assemble production runtime"
```

---

### Task 5: 提供受认证的 HTTP Agent API

**Files:**

- Create: `server/app/api/agent.py`
- Modify: `server/app/main.py`
- Create: `server/tests/test_agent_api.py`

**Interfaces:**

- Produces: `POST /api/v1/agent/chat`。
- Produces: `AgentChatRequest(message: str)` 和 `AgentChatResponse(request_id: str, answer: str)`。
- Consumes: `current_user`、`get_db`、`AgentRuntime.run(message: str, user_id: int, db: Session)`。

- [ ] **Step 1: 编写 API 契约失败测试**

```text
test_agent_chat_requires_access_token
test_agent_chat_rejects_blank_and_oversized_message
test_agent_chat_returns_request_id_and_final_answer
test_agent_chat_uses_authenticated_user_id
test_agent_chat_returns_503_when_llm_is_not_configured
test_agent_chat_maps_timeout_to_504_and_upstream_failure_to_502
```

成功用例断言响应键严格等于 `{"request_id", "answer"}`；用户隔离用例断言 Fake Runtime 收到登录用户 ID；错误用例分别断言 401、422、502、503 和 504。

测试通过 `app.state.agent_runtime` 注入 Fake Runtime，不访问真实模型。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd server && pytest tests/test_agent_api.py -q`

Expected: FAIL，接口返回 404。

- [ ] **Step 3: 实现路由和依赖注入**

```python
class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized

class AgentChatResponse(BaseModel):
    request_id: str
    answer: str

@router.post("/agent/chat", response_model=AgentChatResponse)
def chat(
    payload: AgentChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AgentChatResponse:
    result = request.app.state.agent_runtime.run(payload.message, user.id, db)
    return AgentChatResponse(**result.model_dump())
```

`create_app()` 接受可选 `agent_runtime`，测试可注入 Fake；生产默认从 Settings 创建真实 Runtime。路由使用同步 `def`，让 FastAPI 在线程池执行当前同步 LangGraph，不阻塞事件循环。

- [ ] **Step 4: 运行 API、认证和服务端全量回归**

Run: `cd server && pytest tests/test_agent_api.py tests/test_auth.py -q`

Expected: PASS。

Run: `cd server && pytest -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add server/app/api/agent.py server/app/main.py server/tests/test_agent_api.py
git commit -m "Agent API: expose authenticated chat endpoint"
```

---

### Task 6: 增加 LLM/API 可靠性和脱敏回归

**Files:**

- Modify: `server/tests/test_agent_phase12.py`
- Modify: `server/tests/test_agent_observability.py`
- Create: `server/tests/test_agent_api_boundaries.py`

**Interfaces:**

- Consumes: Task 2～5 的异常类型、运行时和 HTTP API。
- Produces: 不泄露密钥/Prompt/原始响应的回归保护。

- [ ] **Step 1: 增加边界用例**

```text
test_llm_429_is_retried_within_configured_limit
test_llm_timeout_does_not_enter_infinite_react_loop
test_invalid_itinerary_never_reaches_http_answer
test_logs_exclude_api_key_prompt_tool_arguments_and_raw_response
test_agent_api_does_not_return_internal_state_or_validation_models
```

测试分别断言实际调用次数不超过 `llm_max_retries + 1`、ReAct 轮次不超过 8、非法行程返回 502、日志脱敏，以及 HTTP JSON 不含 `information_status`、`collected_info`、`itinerary`、`validation` 或 `reason`。

- [ ] **Step 2: 运行新用例并修复暴露出的最小问题**

Run: `cd server && pytest tests/test_agent_api_boundaries.py tests/test_agent_phase12.py tests/test_agent_observability.py -q`

Expected: PASS；响应只包含 `request_id` 和 `answer`。

- [ ] **Step 3: 运行 Agent 全量回归**

Run: `cd server && pytest tests/test_agent_*.py -q`

Expected: 全部 PASS，无真实网络调用。

- [ ] **Step 4: 提交**

```bash
git add server/tests/test_agent_api_boundaries.py server/tests/test_agent_phase12.py server/tests/test_agent_observability.py
git commit -m "Agent API: cover LLM failure boundaries"
```

---

### Task 7: Android 接入 Agent HTTP 数据层

**Files:**

- Modify: `app/src/main/java/com/miracle/footmarks/data/remote/FootmarksApi.kt`
- Modify: `app/src/main/java/com/miracle/footmarks/data/remote/CloudSession.kt`
- Modify: `app/src/test/java/com/miracle/footmarks/data/remote/FootmarksApiTest.kt`

**Interfaces:**

- Produces: `AgentChatRequest`、`AgentChatResponse`。
- Produces: `FootmarksApi.chat(authorization: String, request: AgentChatRequest)` 和 `CloudSession.askAgent(message: String)`。
- Consumes: 现有 Token、401 刷新和 Retrofit Base URL。

- [ ] **Step 1: 编写 Android API 契约失败测试**

```text
agentChatUsesAuthenticatedEndpointAndParsesResponse
agentChatRefreshesExpiredAccessTokenOnce
```

第一项让 MockWebServer 返回 `{"request_id":"req-1","answer":"行程结果"}`，断言 Retrofit 解析两个字段并发送正确路径、方法、Authorization 和请求 JSON；第二项依次返回 401、刷新 Token、200，断言刷新接口只调用一次且重试使用新 Access Token。

MockWebServer 需要断言：

```text
POST /api/v1/agent/chat
Authorization: Bearer access
{"message":"北京三日游"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\gradlew.bat testDebugUnitTest --tests "*FootmarksApiTest"`

Expected: FAIL，提示 Agent 数据类型或接口不存在。

- [ ] **Step 3: 增加 Retrofit 和 Session 方法**

```kotlin
data class AgentChatRequest(val message: String)

data class AgentChatResponse(
    @SerializedName("request_id") val requestId: String,
    val answer: String
)

@POST("api/v1/agent/chat")
suspend fun chat(
    @Header("Authorization") authorization: String,
    @Body request: AgentChatRequest
): AgentChatResponse
```

```kotlin
suspend fun askAgent(message: String): AgentChatResponse =
    authorized { api.chat(it, AgentChatRequest(message)) }
```

- [ ] **Step 4: 运行 Android API 回归**

Run: `.\gradlew.bat testDebugUnitTest --tests "*FootmarksApiTest"`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/src/main/java/com/miracle/footmarks/data/remote/FootmarksApi.kt app/src/main/java/com/miracle/footmarks/data/remote/CloudSession.kt app/src/test/java/com/miracle/footmarks/data/remote/FootmarksApiTest.kt
git commit -m "Agent API: add Android chat client"
```

---

### Task 8: Android 智能规划页面接入 ViewModel

**Files:**

- Create: `app/src/main/java/com/miracle/footmarks/ui/screen/smartplanning/SmartPlanningViewModel.kt`
- Modify: `app/src/main/java/com/miracle/footmarks/ui/screen/smartplanning/SmartPlanningScreen.kt`
- Create: `app/src/test/java/com/miracle/footmarks/ui/screen/smartplanning/SmartPlanningViewModelTest.kt`
- Modify: `app/src/androidTest/java/com/miracle/footmarks/ui/SmartPlanningScreenTest.kt`
- Modify: `app/build.gradle.kts`

**Interfaces:**

- Produces: `SmartPlanningUiState(messages, draft, isSending, error)`。
- Produces: `SmartPlanningViewModel.updateDraft()`、`send()` 和 `dismissError()`。
- Consumes: `CloudSession.askAgent()`。

- [ ] **Step 1: 增加协程测试依赖和 ViewModel 失败测试**

```kotlin
data class ChatMessage(
    val id: Long,
    val role: ChatRole,
    val text: String
)

data class SmartPlanningUiState(
    val messages: List<ChatMessage> = emptyList(),
    val draft: String = "",
    val isSending: Boolean = false,
    val error: String? = null
)
```

测试至少覆盖：发送成功、未登录、HTTP 错误、发送期间禁用重复提交、空输入不发送、成功后清空输入框。

- [ ] **Step 2: 运行 ViewModel 测试确认失败**

Run: `.\gradlew.bat testDebugUnitTest --tests "*SmartPlanningViewModelTest"`

Expected: FAIL，提示 ViewModel 不存在。

- [ ] **Step 3: 实现 ViewModel 和可测试页面**

```kotlin
@HiltViewModel
class SmartPlanningViewModel @Inject constructor(
    private val cloudSession: CloudSession
) : ViewModel() {
    val uiState: StateFlow<SmartPlanningUiState>
    fun updateDraft(value: String)
    fun send()
    fun dismissError()
}
```

页面行为：

- 用户消息立即进入列表。
- 请求期间显示“正在规划…”并禁用发送按钮。
- 成功后追加 Agent 消息。
- 401/未登录提示“请先在个人中心登录”。
- 502/503/504 显示可重试错误，不删除用户输入和已有消息。
- 删除原有“暂未开放，待完善”Snackbar 逻辑。

- [ ] **Step 4: 更新 Compose 测试**

将旧测试替换为：

```text
sendDisplaysUserAndAgentMessages
sendIsDisabledWhileRequestIsRunning
errorKeepsExistingMessagesAndAllowsRetry
draftSurvivesSavedStateRestoration
```

测试通过可注入的 `SmartPlanningUiState` 和回调验证 UI，不发真实网络请求；ViewModel 单元测试负责验证协程状态变化和 `CloudSession` 调用次数。

- [ ] **Step 5: 运行 Android 单元和仪器测试**

Run: `.\gradlew.bat testDebugUnitTest`

Expected: PASS。

Run: `.\gradlew.bat connectedDebugAndroidTest`

Expected: PASS；需要已启动的 API 34 模拟器。

- [ ] **Step 6: 提交**

```bash
git add app/src/main/java/com/miracle/footmarks/ui/screen/smartplanning app/src/test/java/com/miracle/footmarks/ui/screen/smartplanning app/src/androidTest/java/com/miracle/footmarks/ui/SmartPlanningScreenTest.kt app/build.gradle.kts
git commit -m "Agent API: connect smart planning UI"
```

---

### Task 9: 真实 LLM 与服务器部署验收

**Files:**

- Modify: `README.md`
- Modify: `开发日志.md`
- Modify: `测试指南.md`

**Interfaces:**

- Consumes: 用户提供的 LLM Base URL、API Key、模型名，以及现有高德 Key。
- Produces: 可通过 HTTPS 调用的生产 `POST /api/v1/agent/chat`。

- [ ] **Step 1: 在服务器 `.env` 追加 LLM 配置**

```env
FOOTMARKS_LLM_BASE_URL=https://provider.example/v1
FOOTMARKS_LLM_API_KEY=replace-with-server-secret
FOOTMARKS_LLM_MODEL=replace-with-model-name
FOOTMARKS_LLM_TIMEOUT_SECONDS=30
FOOTMARKS_LLM_MAX_RETRIES=1
```

这三个供应商值必须由用户提供或确认。不得删除现有 Token、COS、高德或数据库配置。

- [ ] **Step 2: 重建并检查服务端**

在服务器项目目录执行：

```bash
sudo docker compose --env-file server/.env -f server/compose.yaml up -d --build
sudo docker compose --env-file server/.env -f server/compose.yaml ps
sudo docker compose --env-file server/.env -f server/compose.yaml logs --tail=100 api
```

Expected: API 容器为 `Up`，日志中没有 Key、Prompt 或原始 LLM 响应。

- [ ] **Step 3: 执行真实 HTTPS 冒烟测试**

先调用现有登录接口获得 Access Token，再执行：

```bash
curl -X POST "https://www.cq-footmark.online/api/v1/agent/chat" \
  -H "Authorization: Bearer <access-token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"南京明天天气怎么样？"}'
```

Expected: HTTP 200，包含非空 `request_id` 和 `answer`；日志包含结构化事件，不包含敏感内容。

- [ ] **Step 4: 执行六类真实场景**

```text
1. 天气查询
2. 历史旅行查询
3. POI 推荐
4. 预算估算
5. 路线查询
6. 三日行程规划
```

逐项确认：无虚构开放时间、天气/路线失败会降级、预算明确是估算、行程经过 Validator。

- [ ] **Step 5: 在本机生成真机 APK**

```powershell
.\gradlew.bat assembleDebug -PfootmarksApiBaseUrl=https://www.cq-footmark.online/
```

APK 在本机生成到：

```text
app/build/outputs/apk/debug/app-debug.apk
```

该命令在本机仓库执行，不在云服务器执行。

- [ ] **Step 6: 真机验收**

- 在个人中心登录共享账号。
- 进入智能规划，发送天气和三日行程请求。
- 验证加载状态、成功消息、错误重试和 Token 自动刷新。
- 断网时显示错误且保留已有消息。
- 连续点击发送不会产生重复请求。

- [ ] **Step 7: 更新文档并提交**

```bash
git add README.md 开发日志.md 测试指南.md
git commit -m "Agent API: document LLM deployment and testing"
```

---

## 3. 全量验收标准

### 服务端

- [ ] 未配置 LLM 时启动不崩溃，调用 Agent API 返回 503。
- [ ] LLM Key 不出现在响应、异常、结构化日志或 Git 中。
- [ ] Agent API 必须通过现有 Access Token 认证。
- [ ] Internal DB Tool 只能读取当前认证用户的数据。
- [ ] LLM 不能调用未注册或当前 State 不支持的 Tool。
- [ ] 所有 LLM 输出都经过 Pydantic 校验。
- [ ] 无效结构化输出、超时、429 和 5xx 有确定的错误映射。
- [ ] Agent 全量测试、服务端全量测试和 `pip check` 通过。

### Android

- [ ] 未登录时明确提示去个人中心登录。
- [ ] 请求期间不能重复发送。
- [ ] 成功后同时显示用户消息和 Agent 回答。
- [ ] Access Token 过期时复用现有刷新逻辑并重试一次。
- [ ] 网络失败不会清空已有消息。
- [ ] JVM 单元测试、Compose 仪器测试、Lint 和 Debug APK 构建通过。

### 真实链路

- [ ] 手机只访问 `https://www.cq-footmark.online/`。
- [ ] 服务端可以访问 LLM 和高德 API。
- [ ] Nginx、Docker 和 FastAPI 超时足以覆盖正常 Agent 请求。
- [ ] 六类真实场景均返回最终回答，没有内部 State、Tool Raw Response 或 ReAct 决策泄露。

---

## 4. 后置阶段：多轮会话与 SSE

以下内容不与首版同步 API 同时开发。首版真实链路稳定后，再单独建立计划：

1. 多轮会话：确定由 Android 上送短期上下文，还是由服务端新增 Conversation/Message 表。个人应用优先考虑 Android 上送最近消息，避免先增加数据库迁移。
2. SSE：复用现有 `AgentEvent`，只推送 `requirement_ready`、Tool 状态、校验状态和 `final_response_ready`，不推送 Prompt、Tool 参数或隐藏推理。
3. Android 流式客户端：使用 OkHttp 读取 `text/event-stream`，按 `request_id` 更新同一条 Agent 消息。
4. 断线策略：SSE 断线只允许用户重新发起本次请求，不在 V1 实现服务端事件重放。

---

## 5. 推荐执行顺序

```text
Task 1 配置
  ↓
Task 2 结构化 LLM 客户端
  ↓
Task 3 ReAct 决策
  ↓
Task 4 Agent Runtime
  ↓
Task 5 HTTP Agent API
  ↓
Task 6 服务端边界回归
  ↓
Task 7 Android 数据层
  ↓
Task 8 Android 页面
  ↓
Task 9 服务器与真机验收
```

每个 Task 完成并回归通过后再进入下一个 Task。真实 LLM Key 只在 Task 9 的部署验收阶段需要，Task 1～8 都应使用 Fake Client 或 Mock Transport 完成测试。
