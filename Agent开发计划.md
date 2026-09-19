# Travel Agent V1 - Agent Implementation Plan

> 本文档是 `Travel Agent V1 - Agent Architecture Specification` 的实施计划。
>
> 开发过程中必须遵循 Architecture Specification 中定义的架构和职责边界。
>
> 核心原则：
>
> - 按阶段实现，不一次性完成所有模块。
> - 每一步完成后先进行测试，再进入下一步。
> - 优先保证 State、节点边界和数据流正确，再完善 Prompt 和业务效果。
> - 不增加 Specification 中未定义的功能。
> - V1 不实现 Web Search 和 RAG。

---

# Phase 0：检查现有项目并确定集成位置

## 目标

在修改代码前理解现有项目结构，避免重新创建已经存在的基础设施。

## Step 0.1：检查项目目录

重点确认：

- 当前 Python 项目目录结构
- LangGraph / LangChain 是否已经安装
- LLM Client 是否已经存在
- 配置管理方式
- 数据库访问层
- 已有 Service / Repository
- 已有 API 层
- 已有 MCP 接入代码
- 已有用户 / Trip / Record 数据模型
- 日志模块
- 测试目录

## Step 0.2：确定 Agent 模块位置

Agent 代码应该与：

- API
- Database
- MCP
- Service

保持解耦。

不要为了实现 Agent 大规模修改现有项目结构。

## Step 0.3：输出集成方案

正式修改代码前，明确：

```text
Agent 模块放在哪里
State Model 放在哪里
Tool Adapter 放在哪里
Validator 放在哪里
Prompt 放在哪里
Graph 构建代码放在哪里
测试放在哪里
```

## 验收标准

能够明确说明：

```text
现有代码
    ↓
哪些可以复用
    ↓
哪些需要新增
    ↓
Agent 如何接入现有项目
```

## Phase 0 执行记录（2026-09-18）

### 现有项目检查结果

- 服务端位于 `server/`，使用 FastAPI、SQLAlchemy、Alembic、SQLite 和 Pydantic Settings。
- 已有用户认证、Trip、Record、图片、COS 存储和健康检查 API；数据库模型位于 `server/app/models.py`，数据库会话位于 `server/app/database.py`。
- 服务端当前没有 LangGraph、LangChain、LLM Client 或 AMap MCP 接入代码，因此本阶段不安装依赖，也不选择具体模型供应商。
- 服务端当前没有独立的 Service / Repository 层，旅行查询逻辑主要位于 `server/app/api/travel.py`。后续实现数据库 Tool 时优先增加只读查询适配层，不在本阶段重构现有 CRUD API。
- Android 已有 `SmartPlanningScreen` 和底部导航入口，目前仍是输入、显示消息和“暂未开放”提示；后续通过现有 Retrofit/网络配置接入 Agent API。
- 服务端测试位于 `server/tests/`，Android 测试位于 `app/src/test/` 和 `app/src/androidTest/`。

### Agent 集成位置

```text
server/app/agent/
├── models.py       # TravelRequirement、CollectedInfo、Itinerary 等业务模型
├── state.py        # TravelAgentState
├── prompts/        # Requirement Analyzer、Generator 等 Prompt
├── tools/          # 数据库、预算和 AMap MCP 适配器
├── validator/      # 确定性行程校验规则
└── graph.py        # 最终 LangGraph 构建入口
```

配套接入位置：

- `server/app/api/agent.py`：后续提供 Agent HTTP 接口，只负责请求和响应转换。
- `server/app/core/config.py`：后续增加 LLM 和 MCP 配置读取，密钥只放服务器 `.env`。
- `server/tests/test_agent_*.py`：按模型、Tool、Normalizer、Validator 和 Graph 分层测试。
- Android 后续新增 Agent Retrofit 接口和 ViewModel；现有 `SmartPlanningScreen` 保留为用户交互入口。

### 可复用与新增范围

| 范围 | 复用或新增内容 |
|---|---|
| 用户与旅行数据 | 复用现有 User、Trip、Record、RecordImage 模型和数据库连接 |
| 认证 | 复用现有 Bearer Token，不为 Agent 单独设计登录体系 |
| Agent State | 新增 `server/app/agent/models.py` 和 `state.py` |
| 数据库 Tool | 后续新增只读适配层，复用现有数据库会话和模型 |
| LLM / MCP | 后续新增适配器，本阶段不接入具体供应商 |
| 行程校验 | 后续新增独立 Validator，不放入 API 或 LLM Prompt 中 |
| 用户入口 | 复用现有 Android 智能规划页面，后续接入 Agent API |

### Phase 0 结论

本阶段没有新增 Agent 运行代码。后续从 Phase 1 开始，只在 `server/app/agent/` 中定义结构化 State 和数据模型；不修改现有记录 CRUD，不接入 LLM、MCP 或 Android 网络请求。

---

# Phase 1：定义 Agent State 和核心数据模型

## 目标

先建立整个 Agent 的数据契约。

此阶段不实现 ReAct，不调用 LLM，不调用 MCP。

---

## Step 1.1：实现 TravelRequirement

实现：

```python
TravelRequirement
```

至少包含：

```text
intent
origin
destination
start_date
end_date
duration_days
travelers
budget
preferences
constraints
```

Intent：

```text
trip_planning
poi_recommendation
route_query
weather_query
budget_query
history_query
general_query
```

---

## Step 1.2：实现 InformationStatus

实现：

```python
InfoRequirement
InformationStatus
```

InfoRequirement 至少包含：

```text
status
critical
attempts
reason
```

Status：

```text
pending
completed
unavailable
failed
```

---

## Step 1.3：实现 CollectedInfo

建立统一业务模型。

至少包括：

```text
TravelHistoryInfo
POIInfo
WeatherInfo
RouteInfo
DistanceInfo
BudgetInfo
CollectedInfo
```

注意：

这些 Model 是 Agent 内部统一数据格式。

禁止直接使用：

```text
AMap Raw Response
Database Raw Result
```

作为 Agent 的长期 State 数据。

---

## Step 1.4：实现 Itinerary Models

实现：

```text
ItineraryItem
ItineraryDay
Itinerary
```

Itinerary 必须是结构化数据。

不要使用自然语言字符串作为内部行程。

---

## Step 1.5：实现 Validation Models

实现：

```text
ValidationIssue
ValidationResult
```

至少支持：

```text
opening_hours
travel_time
time_conflict
daily_load
constraint
budget
```

Issue 状态：

```text
fail
unknown
```

---

## Step 1.6：实现 TravelAgentState

最终组合：

```python
class TravelAgentState(TypedDict):
    messages: ...

    requirement: TravelRequirement

    information_status: InformationStatus
    collected_info: CollectedInfo

    itinerary: Itinerary | None

    validation: ValidationResult | None

    react_round: int
    validation_round: int

    final_response: str | None
```

---

## Step 1.7：编写 Model 测试

至少测试：

- 默认值
- Optional 字段
- Literal 校验
- 非法 Intent
- 非法 Status
- Itinerary 序列化
- ValidationResult 序列化

## Phase 1 验收标准

能够构造一个完整的：

```text
TravelAgentState
```

并完成：

```text
serialize
deserialize
validate
```

此阶段不要求 Agent 可以运行。

## Phase 1 执行记录（2026-09-18）

### 新增代码

- `server/app/agent/models.py`：新增 `TravelRequirement`、`InfoRequirement`、`InformationStatus`、`CollectedInfo`、POI、天气、路线、距离、预算、行程和校验结果模型。
- `server/app/agent/state.py`：新增 `TravelAgentState`，组合需求、信息状态、已收集信息、行程、校验结果、轮次和最终回答字段。
- `server/app/agent/__init__.py`：建立 Agent Python 包。
- `server/tests/test_agent_models.py`：覆盖默认值、Optional、Literal、结构化业务模型、行程 JSON 往返、校验结果序列化和完整 State 往返。

### 设计说明

- 所有列表字段使用 `default_factory`，避免不同 State 实例共享可变默认值。
- `TravelAgentState.messages` 暂时使用 `list[Any]`，因为当前项目还没有引入 LangGraph；等 Phase 11 组装 Graph 时再接入 `add_messages` reducer。
- 本阶段只定义数据契约，不调用 LLM、MCP、数据库 Tool，也不修改现有 CRUD 和 Android 页面。

### 回归结果

- Agent 模型测试：7/7 通过。
- 服务端全量测试：26/26 通过。

---

# Phase 2：实现 Requirement Analyzer

## 目标

实现：

```text
User Query
    ↓
TravelRequirement
```

---

## Step 2.1：编写 Requirement Analyzer Prompt

Prompt 明确要求 LLM：

- 判断用户主要任务
- 提取旅行参数
- 提取 preferences
- 提取 constraints
- 不决定调用哪些 Tool
- 不生成旅行方案

---

## Step 2.2：使用 Structured Output

使用项目当前 LLM 封装实现：

```text
LLM
 ↓
TravelRequirement
```

不要手动解析自由文本 JSON。

优先使用模型支持的 Structured Output / Pydantic Output。

---

## Step 2.3：处理缺失字段

例如：

```text
帮我规划南京三日游
```

允许：

```text
origin = None
budget = None
travelers = None
```

不要为了填满 Schema 让 LLM 猜测。

---

## Step 2.4：测试典型 Intent

至少测试：

```text
帮我规划南京三日游
→ trip_planning
```

```text
南京明天天气怎么样
→ weather_query
```

```text
推荐几个杭州自然景点
→ poi_recommendation
```

```text
从中山陵怎么去夫子庙
→ route_query
```

```text
我以前去过南京吗
→ history_query
```

```text
南京玩三天大概多少钱
→ budget_query
```

---

## Step 2.5：测试复杂需求抽取

例如：

```text
十一从上海去南京玩三天，两个人预算3000，
喜欢历史文化，不想去之前去过的景点。
```

确认：

```text
origin
destination
date
duration
travelers
budget
preferences
constraints
```

能够正确进入 TravelRequirement。

## Phase 2 验收标准

Requirement Analyzer 可以稳定完成：

```text
Natural Language
→
TravelRequirement
```

且不会调用任何 Tool。

---

## Phase 2 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/prompts/requirement_analyzer.py`，定义需求分析器 Prompt。
- 新增 `server/app/agent/analyzer.py`，通过 `StructuredOutputClient` 接收结构化输出并校验为 `TravelRequirement`。
- Requirement Analyzer 只负责需求理解，不传入 Tool、不规划 Tool 调用、不生成旅行方案。
- 缺失字段继续保持为空，不强行猜测出发地、预算或人数。
- 新增 `server/tests/test_agent_analyzer.py`，覆盖复杂需求、缺失字段、典型 Intent、空输入和非法结构化输出。

### 当前集成边界

Phase 0 已确认项目暂时没有 LLM SDK 或现成 LLM 封装，因此本阶段只定义了结构化输出接口，并使用测试客户端验证调用契约。后续接入具体模型时，实现 `StructuredOutputClient.complete_structured()` 即可，不需要修改 Requirement Analyzer 的业务逻辑。

### 回归结果

- Agent Analyzer 测试：11/11 通过。
- 服务端全量测试：48/48 通过。

---

# Phase 3：建立统一 Tool Layer

## 目标

让 ReAct 不直接依赖数据库实现或 AMap Web Service API 返回格式。

统一：

```text
Agent
 ↓
Tool Layer
 ↓
Internal DB / Budget / AMap Web Service API
```

---

## Phase 3 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/tools/layer.py`，建立统一工具接口和执行边界。
- 新增 `ToolResult`，统一表示 `completed`、`unavailable` 和 `failed`。
- 新增 `ToolRegistry`，按名称注册和查找工具，并拒绝重复注册。
- 新增 `ToolLayer`，统一转发参数并将工具异常转换为结构化结果。
- 增加 `ToolUnavailableError`，用于区分外部服务暂时不可用和工具执行失败。
- 新增 `server/tests/test_agent_tool_layer.py`，覆盖正常执行、参数转发、重复注册、工具不存在、服务不可用和异常隔离。

### 当前范围

本阶段只完成 Tool Layer 的统一契约，没有实现具体的数据库、预算或高德工具。后续分别由 Phase 3A、Phase 3B 和 Phase 3C 实现，并通过本阶段的 `ToolResult` 和 `ToolLayer` 接入。

### 回归结果

- Tool Layer 测试：7/7 通过。
- 服务端全量测试：55/55 通过。

---

# Phase 3A：Internal DB Tools

实现：

```text
get_travel_summary
search_trip_history
search_records
get_trip_detail
```

优先复用现有 Repository / Service。

Tool 不应该自己重复实现数据库业务逻辑。

---

## Step 3.1：get_travel_summary

返回统一结构。

不要返回 ORM Object。

---

## Step 3.2：search_trip_history

支持必要查询参数，例如：

```text
city
date range
```

---

## Step 3.3：search_records

支持必要过滤：

```text
trip_id
city
category
rating
cost
```

具体参数根据现有数据库能力确定。

---

## Step 3.4：get_trip_detail

根据：

```text
trip_id
```

返回完整旅行详情。

---

## Phase 3A 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/tools/internal.py`。
- 实现 `get_travel_summary`：返回旅行次数、城市数、总花费和平均评分。
- 实现 `search_trip_history`：支持城市和重叠日期区间筛选。
- 实现 `search_records`：支持旅行、城市、记录类型、评分区间和花费区间筛选。
- 实现 `get_trip_detail`：返回指定旅行及其全部记录。
- 所有工具都绑定 `user_id`，只能查询当前用户的数据。
- 所有查询结果都转换为 Pydantic 结构化模型，不直接返回 ORM 对象。
- 复查后将重复的 `TripHistoryItem` 和 `TripDetailInfo` 合并为 `TripInfo`，由同一模型同时承载旅行摘要和详情。
- 查询参数包含日期范围、评分、花费和旅行 ID 的边界校验。
- 新增 `server/tests/test_agent_internal_tools.py`，覆盖汇总、筛选、用户隔离、详情、不存在旅行和非法参数。

### 回归结果

- Internal DB Tools 测试：5/5 通过。
- 服务端全量测试：60/60 通过。

---

# Phase 3B：Budget Tool

## Step 3.5：实现 estimate_budget

输入可包含：

```text
destination
duration
travelers
accommodation_level
food_level
transport_mode
pois
```

输出：

```text
BudgetInfo
```

应返回：

```text
estimated_min
estimated_max
breakdown
assumptions
```

明确属于估算。

禁止声称为实时精确价格。

---

## Phase 3B 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/tools/budget.py`，实现 `estimate_budget`。
- 支持目的地、天数、人数、住宿档次、餐饮档次、交通方式和景点列表。
- 按住宿、餐饮、交通和景点门票拆分预算。
- 返回人民币估算下限、上限、明细和假设说明。
- 对天数、人数、消费档次和景点名称进行输入校验。
- 明确说明当前是通用 Demo 估算，不是实时精确价格。
- 新增 `server/tests/test_agent_budget_tool.py`，覆盖计算结果、默认值和边界输入。

### 回归结果

- Budget Tool 测试：4/4 通过。
- 服务端全量测试：64/64 通过。

---

# Phase 3C：AMap Web Service API Adapter

## Step 3.6：接入 AMap Web Service API

封装当前需要的能力：

```text
keyword search
around search
poi detail
weather
distance
driving route
transit route
walking route
cycling route
geocoding
reverse geocoding
```

Agent Node 不直接处理高德 Web Service API 协议细节。

---

## Phase 3C 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/tools/amap.py`，实现高德 Web 服务 API 适配器。
- 支持关键词搜索、周边搜索、POI 详情、天气、地理编码、逆地理编码、距离测量，以及驾车、公交、步行、骑行路线。
- 高德接口返回的原始 JSON 先保持原样，后续由 Phase 3D Normalizer 转换为 `POIInfo`、`WeatherInfo`、`RouteInfo` 等业务模型。
- 统一处理 Key 未配置、网络不可用和高德业务错误。
- 新增 `amap_web_key`、`amap_base_url` 和 `amap_timeout_seconds` 配置。
- 更新 `server/.env.example`、`server/compose.yaml` 和 `README.md`，说明 Key 只填服务器 `server/.env`。
- 新增 `server/tests/test_agent_amap.py`，使用假传输层测试请求参数和接口路径，不消耗高德额度。

### 配置位置

在服务器的 `server/.env` 中填写：

```text
FOOTMARKS_AMAP_WEB_KEY=你的高德Web服务Key
```

不要把真实 Key 写进代码、APK 或 Git。

### 回归结果

- AMap Adapter 测试：6/6 通过。
- 服务端全量测试：70/70 通过。

---

# Phase 3D：Normalizer

## Step 3.7：建立 Tool Result Normalizer

例如：

```text
AMap POI Raw Response
        ↓
normalize_poi()
        ↓
POIInfo
```

```text
AMap Route Raw Response
        ↓
normalize_route()
        ↓
RouteInfo
```

```text
DB Result
        ↓
normalize_history()
        ↓
TravelHistoryInfo
```

---

## Step 3.8：处理空数据

Tool 正常返回但无数据：

```text
[]
null
empty result
```

必须能够被识别。

不能与异常混为一谈。

---

## Step 3.9：处理异常

统一捕获：

```text
timeout
connection error
MCP error
database error
invalid response
```

转换为 Agent 可以识别的错误结果。

## Phase 3 验收标准

能够在没有 ReAct 的情况下独立测试：

```text
调用 Tool
↓
获得 Raw Result
↓
Normalizer
↓
Agent Business Model
```

---

## Phase 3D 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/normalizer.py`，将高德 POI、天气、路线、距离原始响应转换为 `POIInfo`、`WeatherInfo`、`RouteInfo` 和 `DistanceInfo`。
- 将内部数据库旅行查询结果汇总为 `TravelHistoryInfo`，将预算结果转换为 `BudgetInfo`。
- 新增 `normalize_tool_result()`，保留 `completed`、`unavailable` 和 `failed` 状态；无效原始响应统一返回 `invalid_tool_response`。
- 空列表、`null` 和空对象按“查询成功但没有数据”处理，不转换成异常。
- 实时天气没有可靠温度范围时保留未知值，不自行推断最低温和最高温。

### 测试结果

- 新增 `server/tests/test_agent_normalizer.py`，覆盖 POI、实时天气、天气预报、路线、距离、历史、预算、空数据和异常响应。
- Normalizer 专项测试：9/9 通过。
- 不依赖数据库临时目录的 Agent 测试：55/55 通过。
- Phase 3A 的数据库 Tool 测试此前已通过 5/5；本次本机全量回归另外受到 pytest 临时目录访问权限限制，未发现业务断言失败。

### 当前边界

Normalizer 已完成独立转换和错误边界处理，但尚未接入 Phase 4 Information Status 或后续 ReAct Graph。

---

# Phase 4：实现 Information Status 管理

## 目标

实现 ReAct 的信息任务状态系统。

---

## Step 4.1：初始化 InformationStatus

根据：

```text
TravelRequirement
```

生成当前信息需求。

注意：

不要设计独立 Information Planner Node。

初始化逻辑可以由 ReAct / Collector 完成。

---

## Step 4.2：实现状态更新

成功：

```text
pending
→
completed
```

空结果：

```text
attempts += 1
```

异常：

```text
attempts += 1
```

---

## Step 4.3：实现最大单项尝试次数

定义：

```python
MAX_INFO_ATTEMPTS = 3
```

连续空结果达到上限：

```text
unavailable
```

连续异常达到上限：

```text
failed
```

---

## Step 4.4：区分 critical

支持：

```text
critical = true
critical = false
```

核心信息失败时：

允许结束 ReAct，但 Final Generator 必须明确说明无法完成核心数据查询。

非核心信息失败时：

允许降级继续完成任务。

---

## Step 4.5：测试状态机

至少测试：

```text
pending → completed
```

```text
pending → empty → empty → unavailable
```

```text
pending → error → error → failed
```

以及：

```text
attempts < 3
```

时仍然允许继续获取。

## Phase 4 验收标准

InformationStatus 可以独立运行并正确管理信息生命周期。

---

## Phase 4 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/information.py`，定义 `MAX_INFO_ATTEMPTS = 3` 和信息需求生命周期操作。
- 新增 `initialize_information_status()`，根据 `TravelRequirement` 创建当前直接需要的信息项；行程规划中的预算和“不要去以前去过的地方”等约束会登记对应核心信息。
- 新增 `ensure_information_need()`，为后续 ReAct 动态加入新的 `pending` 信息项。
- 新增 `update_information_status()`，实现成功、空结果和异常三类状态更新；空结果达到上限后进入 `unavailable`，异常达到上限后进入 `failed`。
- 新增 `all_information_terminal()` 和 `has_critical_failure()`，分别支持 ReAct 退出判断和核心信息失败判断。
- 终止状态不会被后续结果重新激活，状态更新返回深拷贝，不直接修改调用方的旧状态。

### 测试结果

- 新增 `server/tests/test_agent_information.py`，覆盖各类意图初始化、预算和历史约束、无需求、成功、空结果重试、异常重试、最大次数、终止状态、核心失败和非法输入。
- Phase 4 状态机测试：10/10 通过。
- Phase 1～4 Agent 测试（不包含需要数据库临时目录的 Internal DB 测试）：65/65 通过。
- Python 模块编译检查通过。

### 当前边界

InformationStatus 已可独立管理信息生命周期，但尚未接入 Phase 5 ReAct Collector；当前没有 LLM Tool Calling 或自动状态更新流程。

---

# Phase 5：实现 ReAct Information Collector

## 目标

实现整个 Agent 最核心的动态信息收集循环。

---

## Step 5.1：定义 ReAct 输入上下文

ReAct 应读取：

```text
TravelRequirement
InformationStatus
CollectedInfo
Available Tools
```

避免每次把不必要的大量 Raw Data 重新放入 Prompt。

---

## Step 5.2：绑定 Tools

让 LLM 可以调用：

```text
Internal DB Tools
estimate_budget
AMap MCP Tools
```

---

## Step 5.3：执行 Tool

流程：

```text
LLM
 ↓
Tool Call
 ↓
Tool Execution
 ↓
Raw Result
 ↓
Normalizer
 ↓
Update CollectedInfo
 ↓
Update InformationStatus
```

---

## Step 5.4：继续 ReAct

Tool 执行完成后：

```text
返回 ReAct Collector
```

让 Agent 根据最新 State 决定下一步。

---

## Step 5.5：实现无 Tool Call 判断

如果 LLM 不产生 Tool Call：

```text
检查 InformationStatus
```

如果 required information 均处于终止状态：

```text
completed
unavailable
failed
```

结束 ReAct。

如果仍有：

```text
pending
```

继续 ReAct。

---

## Step 5.6：实现总轮次限制

定义：

```python
MAX_REACT_ROUNDS = 8
```

每轮：

```text
react_round += 1
```

达到上限：

```text
强制结束 ReAct
```

不能出现无限 Tool Calling。

---

## Step 5.7：防止重复无意义 Tool Call

同一个 Information Need：

```text
attempts >= 3
```

后，不允许再次调用 Tool 获取同一信息。

---

## Step 5.8：测试 ReAct

至少测试：

### Case 1

```text
南京明天天气怎么样
```

Agent 应主要获取 weather。

### Case 2

```text
我以前去过南京吗
```

Agent 应主要调用 Internal DB Tool。

### Case 3

```text
帮我规划南京三日游，不要去以前去过的地方
```

Agent 应根据需求动态获取：

```text
history
POIs
routes/distances
budget 等必要信息
```

具体顺序不需要硬编码。

## Phase 5 验收标准

ReAct 可以：

```text
根据 State
→
选择 Tool
→
更新 State
→
继续判断
→
自动退出
```

---

## Phase 5 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/collector.py`，实现不依赖具体 LLM SDK 的 ReAct Collector。
- 新增 `ToolCall`、`ReActDecision`、`ReActContext` 和 `ReActDecisionClient` 协议，决策客户端只负责返回结构化 Tool Call。
- Collector 每轮读取 `TravelRequirement`、`InformationStatus`、`CollectedInfo` 和可用工具说明，执行 Tool Layer 后调用 Normalizer，再更新结构化 State。
- 支持天气、历史、POI、预算、路线和距离工具的默认绑定；`search_records` 也会转换为历史事实。
- 成功、空结果、`unavailable` 和 `failed` 均接入 Phase 4 状态机；单项最多尝试 3 次，ReAct 总轮次最多 8 次。
- 信息已经全部进入终止状态时立即结束；仍有 `pending` 信息但没有 Tool Call 时继续循环，达到总轮次后强制停止。
- `ToolLayer` 增加只读工具说明接口，供决策上下文使用；Collector 深拷贝输入 State，不直接修改调用方对象。

### 测试结果

- 新增 `server/tests/test_agent_collector.py`，覆盖天气、历史、三类失败/空结果重试、最大轮次、无 Tool Call、State 不变性和多信息动态收集。
- Phase 5 Collector 测试：8/8 通过。
- Phase 1～5 Agent 测试（不包含需要数据库临时目录的 Internal DB 测试）：74/74 通过。
- Python 模块编译检查通过。

### 当前边界

当前使用 `ReActDecisionClient` 抽象接口和测试客户端，尚未接入真实 LLM、LangGraph 或 HTTP Agent API。高德地理编码暂未写入 State，因为现有业务模型尚无地理坐标模型。

---

# Phase 6：实现非 Trip Planning 的 Final Response

## 目标

在开发复杂行程生成前，先打通简单请求的完整链路。

---

## Step 6.1：实现 Final Response Generator 基础版本

输入：

```text
TravelRequirement
CollectedInfo
InformationStatus
```

生成用户回答。

---

## Step 6.2：限制事实来源

Final Generator 只能使用 State 中已有事实。

禁止自行补充：

```text
天气
价格
路线时间
距离
地址
历史记录
开放时间
```

---

## Step 6.3：实现降级提示

如果：

```text
unavailable
failed
```

必须明确告诉用户。

---

## Step 6.4：完成简单 Workflow

打通：

```text
START
 ↓
Requirement Analyzer
 ↓
ReAct Collector
 ↓
Final Response Generator
 ↓
END
```

先支持：

```text
weather_query
route_query
history_query
budget_query
poi_recommendation
general_query
```

## Phase 6 验收标准

非 `trip_planning` 请求已经可以端到端运行。

## Phase 6 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/response.py`，实现 `FinalResponseGenerator` 基础版本。
- Final Response Generator 只读取 `TravelRequirement`、`CollectedInfo` 和 `InformationStatus`，不会自行补充天气、价格、路线时间、距离、地址或历史记录。
- 支持天气、历史记录、预算、地点推荐、路线和通用请求的确定性回答模板；预算明确标注为人民币。
- 对 `pending`、`unavailable` 和 `failed` 状态输出对应提示，并保留状态中的原因。
- 新增 `server/app/agent/workflow.py`，实现 `RequirementAnalyzer → ReActCollector → FinalResponseGenerator` 的简单工作流。
- `general_query` 没有信息收集任务时会直接进入最终回答节点，不会调用工具。

### 测试结果

- 新增 `server/tests/test_agent_response.py`，覆盖六类非行程规划请求、正常事实输出、空字段、距离、`unavailable` 和 `failed` 边界。
- 新增 `server/tests/test_agent_workflow.py`，覆盖天气请求端到端链路和无需工具的通用请求。
- Phase 1～6 Agent 测试（不包含需要数据库临时目录的 Internal DB 测试）：83/83 通过。
- Python 模块编译检查通过。

### 当前边界

当前最终回答使用确定性模板，尚未接入真实 LLM 进行自然语言润色；工作流仍是 Python 组合器，尚未接入 LangGraph 或 HTTP Agent API。`trip_planning` 的行程生成留到 Phase 7。

---

# Phase 7：实现 Structured Itinerary Generator

## 目标

开始支持完整旅行规划。

---

## Step 7.1：定义 Generator Prompt

输入：

```text
TravelRequirement
CollectedInfo
```

要求 LLM：

- 根据候选 POI 生成行程。
- 考虑用户 preferences。
- 遵守 constraints。
- 使用已经获取的路线和距离信息。
- 不虚构不存在的事实。
- 输出结构化 Itinerary。

---

## Step 7.2：使用 Structured Output

输出：

```text
Itinerary
```

禁止输出自然语言旅行攻略。

---

## Step 7.3：保证 POI 可追踪

行程中的 POI 应尽量使用：

```text
poi_id
```

关联 `CollectedInfo.pois`。

不要只使用 POI 名称。

---

## Step 7.4：测试行程生成

检查：

- 天数正确
- POI 来自 CollectedInfo
- 时间格式正确
- 用户硬约束没有明显被忽略
- 输出可以被 Validator 直接读取

## Phase 7 验收标准

能够：

```text
TravelRequirement
+
CollectedInfo
→
Structured Itinerary
```

## Phase 7 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/generator.py`，定义 `StructuredItineraryClient` 和 `StructuredItineraryGenerator`。
- 新增行程生成 Prompt，要求结构化输出 `Itinerary`，只使用 `CollectedInfo` 中已有的事实，并携带用户偏好和硬约束。
- 生成器通过 Pydantic 校验输出，并确认每个行程项的 `poi_id` 来自 `CollectedInfo.pois`，且 `poi_name` 与对应 POI 一致。
- 校验 `duration_days`、出发日期、结束日期、连续日期以及 `YYYY-MM-DD` 和 `HH:MM` 格式。
- 当已有历史记录且用户要求避开以前去过的地点时，拦截使用已访问 `poi_id` 的行程项。
- 保持生成器只负责产生结构化行程；行程冲突、开放时间、路程时间和预算规则留给 Phase 8 Validator。

### 测试结果

- 新增 `server/tests/test_agent_generator.py`，覆盖结构化客户端调用、Prompt 输入、POI 追踪、天数、日期/时间格式和历史地点约束边界。
- Phase 7 生成器测试：8/8 通过。
- Phase 1～7 Agent 测试（不包含需要数据库临时目录的 Internal DB 测试）：91/91 通过。
- Python 模块编译检查通过。

### 当前边界

当前使用 `StructuredItineraryClient` 抽象接口和测试客户端，尚未接入真实 LLM。生成的 `Itinerary` 仍是内部数据，未经 Phase 8 Validator 检查前不能作为最终用户回答展示。

---

# Phase 8：实现确定性 Itinerary Validator

## 目标

建立不依赖 LLM 猜测的行程校验系统。

Validator 建议采用可扩展 Rule 设计。

例如：

```text
Validator
 ├── OpeningHoursRule
 ├── TravelTimeRule
 ├── TimeConflictRule
 ├── DailyLoadRule
 ├── ConstraintRule
 └── BudgetRule
```

---

## Step 8.1：Time Conflict Rule

检查：

```text
Activity A
Activity B
```

是否时间重叠。

---

## Step 8.2：Travel Time Rule

检查：

```text
A.end_time
+
route.duration
<=
B.start_time
```

否则：

```text
FAIL
```

---

## Step 8.3：Opening Hours Rule

如果：

```text
opening_hours != None
```

检查计划时间是否处于开放时间。

如果：

```text
opening_hours == None
```

返回：

```text
UNKNOWN
```

禁止猜测开放时间。

---

## Step 8.4：Constraint Rule

对可以确定性计算的硬约束进行检查。

例如：

```text
不要去以前去过的地方
```

检查：

```text
planned_poi_ids ∩ visited_poi_ids
```

---

## Step 8.5：Budget Rule

如果存在：

```text
requirement.budget
```

并且存在预算估算：

检查预算约束。

---

## Step 8.6：Daily Load Rule

检查每天安排是否明显超出允许的时间范围。

具体阈值放入配置，不硬编码散落在业务代码中。

---

## Step 8.7：聚合 ValidationResult

所有 Rule 输出统一：

```text
ValidationIssue
```

最终：

```text
ValidationResult
```

---

## Step 8.8：测试 Validator

Validator 测试不调用 LLM。

使用固定 Itinerary 构造：

```text
PASS
FAIL
UNKNOWN
```

场景。

## Phase 8 验收标准

Validator 可以完全独立于 LLM 对结构化行程进行检查。

## Phase 8 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/validator.py`，实现独立于 LLM 的 `ItineraryValidator`。
- 新增 `ValidatorConfig`，将每日最大安排时长集中配置，默认上限为 720 分钟，可在调用时调整。
- 实现时间冲突校验：检查同一天活动是否重叠。
- 实现移动时间校验：使用 `CollectedInfo.routes` 检查相邻 POI 是否留出了足够的路线时间；没有可靠路线时返回 `unknown`。
- 实现开放时间校验：支持简单单时段、多时段和全天格式；缺失或无法解析时返回 `unknown`，不猜测开放时间。
- 实现历史地点硬约束校验；用户偏好不会直接触发失败。
- 实现预算上限校验；缺少预算估算时返回 `unknown`。
- 实现每日负荷校验，并聚合为统一的 `ValidationResult`。只有 `fail` 会使 `valid=False`，`unknown` 只表示信息不足。

### 测试结果

- 新增 `server/tests/test_agent_validator.py`，覆盖 PASS、时间冲突、移动时间不足、路线缺失、开放时间 FAIL/UNKNOWN、历史约束、预算和每日负荷配置。
- Phase 8 Validator 测试：9/9 通过。
- Phase 1～8 Agent 测试（不包含需要数据库临时目录的 Internal DB 测试）：100/100 通过。
- Python 模块编译检查通过。

### 当前边界

Validator 已可独立调用，但尚未接入 `TravelAgentWorkflow` 的 `trip_planning` 分支；行程修改留给 Phase 9，未经 Validator 处理的行程仍不能作为最终回答展示。

---

# Phase 9：实现 Local Itinerary Reviser

## 目标

只修复 Validator 指出的行程问题。

---

## Step 9.1：定义 Reviser Prompt

输入：

```text
Current Itinerary
Validation Issues
TravelRequirement
Relevant CollectedInfo
```

---

## Step 9.2：限制修改范围

明确要求：

```text
只修改 ValidationIssue 相关的 Day / POI / 时间段。
```

未出现问题的部分原则上保持不变。

---

## Step 9.3：输出新的 Structured Itinerary

Reviser 仍然必须：

```text
Structured Output
→
Itinerary
```

不能输出自然语言。

---

## Step 9.4：重新 Validator

流程：

```text
Reviser
 ↓
Validator
```

---

## Step 9.5：限制 Validation Round

定义：

```python
MAX_VALIDATION_ROUNDS = 2
```

达到上限后：

停止继续修改。

剩余问题保留在：

```text
ValidationResult
```

中。

## Phase 9 验收标准

能够完成：

```text
Invalid Itinerary
 ↓
Validator
 ↓
Local Reviser
 ↓
Validator
 ↓
Valid / Remaining Issues
```

## Phase 9 执行记录（2026-09-18）

### 完成内容

- 新增 `server/app/agent/reviser.py`，定义 `StructuredRevisionClient`、`LocalItineraryReviser` 和 `ItineraryValidationLoop`。
- Reviser 使用结构化输出返回新的 `Itinerary`，不输出自然语言解释。
- Reviser 将 `fail` 问题作为修订依据，只有 `unknown` 时直接保留原行程，不调用客户端。
- 增加修改范围检查：未涉及的日期、日期值和未涉及的 POI 必须保持不变；天数变化也会被拒绝。
- 增加 `Validator → Reviser → Validator` 循环，默认最多修订 2 轮；达到上限后保留最后的 `ValidationResult`。
- `unknown` 不会触发行程修改，符合 Phase 8 的验证语义。

### 测试结果

- 新增 `server/tests/test_agent_reviser.py`，覆盖结构化输出、局部修改范围、无失败时跳过修订、修订后重新校验和最大轮次。
- Phase 9 Reviser 测试：6/6 通过。
- Phase 1～9 Agent 测试（不包含需要数据库临时目录的 Internal DB 测试）：120/120 通过。
- Python 模块编译检查通过。

### 当前边界

当前 Reviser 使用 `StructuredRevisionClient` 抽象接口和测试客户端，尚未接入真实 LLM；Validation Loop 也尚未接入 `TravelAgentWorkflow` 的 `trip_planning` 分支。最终用户回答仍留到 Phase 10。

---

# Phase 10：完善 Final Response Generator

## 目标

将已经验证过的内部数据转换为真正的用户回答。

---

## Step 10.1：Trip Planning 输出

输入：

```text
TravelRequirement
CollectedInfo
Itinerary
ValidationResult
```

输出可包含：

```text
每日行程
交通建议
天气
预算
注意事项
未验证信息
```

---

## Step 10.2：处理 UNKNOWN

例如：

```text
opening_hours = UNKNOWN
```

最终必须明确说明：

```text
该景点未获取到可靠开放时间，建议出发前确认。
```

---

## Step 10.3：处理 Remaining FAIL

如果达到：

```text
MAX_VALIDATION_ROUNDS
```

仍存在 FAIL：

不得假装已经完全验证。

需要明确说明仍存在的问题。

---

## Step 10.4：保证用户只看到最终结果

以下内容禁止直接返回：

```text
Requirement Analyzer Output
ReAct Decision
Tool Raw Response
InformationStatus
Unvalidated Itinerary
Validation Intermediate Result
Reviser Intermediate Result
```

## Phase 10 验收标准

用户只能看到经过整个 Workflow 处理后的最终回答。

## Phase 10 执行记录（2026-09-18）

### 新增代码

- 更新 `server/app/agent/response.py`，为 `FinalResponseGenerator` 增加行程规划输入：`Itinerary` 和 `ValidationResult`。
- 行程最终回答现在会按天展示日期、时间、地点、活动类型和已有的估算花费。
- 只在 `CollectedInfo` 已有路线数据时展示相邻景点之间的交通参考，并将内部 POI ID 转换为行程中的地点名称。
- 只展示 State 中已有的天气和预算事实；天气、预算或历史记录缺失时明确说明降级结果，不补写外部事实。
- 将 `UNKNOWN` 校验问题转换为用户可读的待确认事项；达到校验轮次上限后仍存在 `FAIL` 时，明确告知行程尚未完全通过校验及建议处理方式。
- 行程最终回答不暴露 `InformationStatus`、原始工具结果、ReAct 决策或校验模型名称。

### 测试与验证

- 新增 `server/tests/test_agent_trip_response.py`，覆盖正常行程输出、开放时间和天气缺失、校验仍有 FAIL、行程为空四种场景。
- 当前工作区已完成 Python 语法编译和 `git diff --check`。
- 使用服务器一次性测试容器验证时，Agent 测试已有 124 项通过；数据库测试因跳过项目全局 `conftest.py` 后缺少 `db_session` fixture，另有 5 项未执行完成，该问题与 Phase 10 的最终响应模块无关。

### 当前边界

`FinalResponseGenerator` 已支持完整的行程最终输出，但尚未接入 `TravelAgentWorkflow` 的 `trip_planning` 分支。完整的 LangGraph 节点接线、生成行程后调用 Validator/Reviser，以及只从 Graph 返回最终回答，按计划留给 Phase 11。

---

# Phase 11：完成 LangGraph Wiring

## 目标

将已经独立测试过的节点组装为完整 Graph。

建议最终结构：

```text
START
 ↓
Requirement Analyzer
 ↓
ReAct Collector
 ↓
Tool Needed?
 ├── YES
 │     ↓
 │   Tool Execution
 │     ↓
 │   Normalizer
 │     ↓
 │   Update State
 │     ↓
 │   ReAct Collector
 │
 └── NO
       ↓
Information Complete?
 ├── NO
 │    ↓
 │ ReAct Collector
 │
 └── YES
       ↓
Intent Router
   ┌───────────────┴───────────────┐
   ↓                               ↓
trip_planning                     other
   ↓                               ↓
Itinerary Generator         Final Generator
   ↓                               ↓
Validator                         END
   ↓
Validation Router
   ├── FAIL
   │     ↓
   │   Reviser
   │     ↓
   │   Validator
   │
   └── PASS / UNKNOWN
           ↓
      Final Generator
           ↓
          END
```

---

## Step 11.1：实现 Conditional Edges

至少包括：

```text
tool / no_tool
information_complete / incomplete
trip_planning / other
validation_fail / finish
```

---

## Step 11.2：确保 Node 职责单一

禁止出现一个 Node 同时：

```text
调用 Tool
+
生成行程
+
校验
+
生成用户回答
```

---

## Step 11.3：检查 State 修改范围

每个 Node 只修改自己负责的 State。

## Phase 11 验收标准

完整 Graph 可以编译并成功执行端到端请求。

## Phase 11 执行记录（2026-09-19）

### 完成内容

- 新增 `server/app/agent/graph.py`，使用 `StateGraph`、`START` 和 `END` 组装 Agent 主流程并在构建时编译 Graph。
- 增加完整初始 State 构造，Analyzer 节点只负责写入 `requirement`，初始化节点负责创建信息状态并清理本次请求的中间字段。
- 接入现有 `ReActCollector`，保留其内部有限轮次的 Tool 调用、Normalizer 和信息状态更新逻辑；Graph 不重复实现 Tool 执行。
- 为 `ReActCollector` 增加 `collect_round()`，Graph 每轮只执行一次决策和可选 Tool 调用；原有 `collect()` 仍保留完整循环行为。
- 增加信息完整/不完整分支和 `trip_planning / other` 意图分流。
- 将 `StructuredItineraryGenerator`、`ItineraryValidator`、`ItineraryReviser` 和 `FinalResponseGenerator` 按职责接入 Graph。
- 增加 `FAIL → Reviser → Validator` 条件回路，并在达到 `MAX_VALIDATION_ROUNDS` 后进入最终回答。
- `messages` 使用 LangGraph 的 `add_messages` reducer；新增生产依赖 `langgraph==1.2.11`。

### 测试与验证

- 新增 `server/tests/test_agent_graph.py`，覆盖 Graph 编译、普通请求、信息不完整、行程规划、校验通过和校验失败后修订。
- Phase 11 定向测试：16/16 通过；其中包含信息不完整时回到下一轮 Collector，以及达到最大轮次后降级到最终回答的回归。
- Collector、Graph 和最终响应联合回归：24/24 通过。
- 条件边修正前的 Phase 1～11 Agent 全量回归（不包含数据库 fixture 测试）：128/128 通过；修正后新增分支测试通过，未改变其他节点实现。
- Python 模块编译检查和 `git diff --check` 通过。

### 当前边界

当前 `ReActCollector` 已经封装 Tool 调用和 Normalizer，因此 Graph 层的 `tool/no_tool` 决策仍由 Collector 单轮内部完成，避免重复执行工具；信息不完整的 Graph 回路已经按架构返回 Collector。真实 LLM、HTTP Agent API、异常降级场景和端到端真实数据测试留给后续 Phase。

---

# Phase 12：异常处理和边界测试

## 目标

验证 Agent 不会因为外部数据异常进入死循环或产生虚假结果。

---

## Step 12.1：AMap 返回空

验证：

```text
attempts
→
unavailable
→
降级回答
```

---

## Step 12.2：AMap 调用异常

验证：

```text
attempts
→
failed
→
降级回答
```

---

## Step 12.3：数据库无历史数据

必须视为：

```text
查询成功
+
结果为空
```

不能无限查询历史。

---

## Step 12.4：开放时间缺失

必须：

```text
UNKNOWN
```

不能虚构。

---

## Step 12.5：ReAct 达到最大轮次

确认：

```text
MAX_REACT_ROUNDS
```

能够强制终止。

---

## Step 12.6：Validator 达到最大轮次

确认：

```text
MAX_VALIDATION_ROUNDS
```

能够终止修改。

---

## Step 12.7：核心信息获取失败

例如：

```text
weather_query
+
weather failed
```

最终必须明确告诉用户无法获得核心信息。

---

## Phase 12 执行记录（2026-09-19）

### 完成内容

- 新增 `server/tests/test_agent_phase12.py`，覆盖空历史、核心天气信息失败、异常降级和轮次上限场景。
- 验证 AMap/Tool Layer 的空结果会进入 `unavailable`，外部异常会进入 `failed`，并在达到尝试次数后停止重试。
- 验证数据库查询无历史记录属于成功查询，结果为 `TravelHistoryInfo(trip_count=0)`，不会被误判为不可用，也不会重复查询。
- 验证缺失 `opening_hours` 时保持 `UNKNOWN`，不会生成虚假的开放时间。
- 验证 ReAct 达到 `MAX_REACT_ROUNDS`、Validator 达到 `MAX_VALIDATION_ROUNDS` 后都能结束流程。
- 验证天气这一核心信息连续失败后，Graph 会进入最终回答，并明确告知用户天气信息不可用及失败原因。
- 修正 `ReActCollector` 的空结果判断顺序：先经过 Normalizer，再判断标准化结果是否为空。这样可以区分“空历史事实”和“外部数据为空”，避免把成功的空历史查询错误降级为 `unavailable`。

### 测试与验证

- Phase 12 相关 Agent 回归：`63 passed`，覆盖 AMap、Collector、Graph、信息状态、Normalizer、异常边界、最终响应、Reviser 和 Validator。
- `python -m compileall -q server/app server/tests` 通过。
- `git diff --check` 通过；修改文件中的 CRLF 提示属于原有换行格式提示，不是 diff 错误。

### 当前边界

Phase 12 使用可控的 Fake Tool/Client 验证异常和边界状态，尚未连接真实 LLM、真实 HTTP Agent API 和真实数据源做端到端回归；这些内容进入 Phase 13。

---

# Phase 13：端到端测试

至少建立以下场景。

## Case 1：天气查询

```text
南京明天天气怎么样？
```

---

## Case 2：历史查询

```text
我之前去过杭州吗？
```

---

## Case 3：POI 推荐

```text
推荐几个南京适合看历史建筑的地方。
```

---

## Case 4：预算

```text
两个人去南京玩三天大概需要多少钱？
```

---

## Case 5：路线

```text
从中山陵去夫子庙怎么走？
```

---

## Case 6：简单行程

```text
帮我规划南京三日游。
```

---

## Case 7：带历史约束

```text
帮我规划南京三日游，不要安排我以前去过的景点。
```

---

## Case 8：复杂需求

```text
十一从上海去南京玩三天，两个人预算3000，
喜欢历史文化和当地美食，不想去以前去过的景点。
```

---

## Case 9：外部数据缺失

模拟：

```text
opening_hours unavailable
```

检查最终回答是否正确降级。

---

## Case 10：路线时间冲突

人为构造：

```text
A 结束 11:30
A → B 需要 60min
B 开始 12:00
```

验证：

```text
Validator FAIL
→
Local Reviser
→
Validator
```

---

## Phase 13 执行记录（2026-09-19）

### 完成内容

- 新增 `server/tests/test_agent_phase13.py`，从用户文本开始，贯通 Requirement Analyzer、ReAct Collector、Tool Layer、Normalizer、LangGraph、Itinerary Generator、Validator、Local Reviser 和 Final Response。
- 建立 10 个端到端场景：天气、历史、POI、预算、路线、三日行程、历史去重约束、复杂预算需求、开放时间未知和路线移动时间冲突。
- 增加 `react_action` 状态，区分本轮实际调用 Tool 和本轮没有 Tool Call。
- 修正行程规划的信息收集回路：POI 收集完成后，ReAct 可以动态发现并登记路线、预算等新信息；信息收集完成且没有新的 Tool Call 后才进入 Intent Router。
- 保持非行程请求的原有行为：天气等信息已经完成时不重复调用；pending 信息在没有 Tool Call 时仍受 `MAX_REACT_ROUNDS` 限制。
- 修正开发测试 Dockerfile，同时复制 `requirements.txt` 和 `requirements-dev.txt`，使 `requirements-dev.txt` 的基础依赖引用在容器构建时可用。
- 统一 Agent 模块命名：`information_status.py` 改为 `information.py`，`tools/internal_db.py` 改为 `tools/internal.py`，同步更新测试文件名和导入。

### 测试与验证

- Phase 13 场景测试：`10 passed`。
- Agent 非数据库 fixture 回归：`141 passed`。
- Internal DB Agent 回归：`5 passed`。
- Phase 1～13 Agent 合计回归：`146 passed`。
- 固定 `agent-test` 容器已在服务器 `/home/ubuntu/footmarks-agent-test` 启动，后续代码修改通过目录挂载直接测试。

### 当前边界

本阶段使用可控的结构化客户端和 Tool 返回值验证完整业务链路，尚未接入真实 LLM、HTTP Agent API 或真实高德数据做网络端到端测试；这些依赖接入后仍需补跑同一组场景。

---

# Phase 14：日志与可观测性

## 目标

方便后续调试 Agent，而不暴露内部推理。

建议记录：

```text
request_id
user_id
intent
node_name
tool_name
tool_duration
tool_success
information_status
react_round
validation_round
validation_issue_type
total_duration
```

不要记录或对外暴露 LLM 的隐藏推理过程。

可以记录结构化事件：

```text
requirement_ready
tool_started
tool_completed
information_updated
itinerary_generated
validation_started
validation_failed
itinerary_revised
validation_completed
final_response_ready
```

如果项目已有 SSE，可以后续使用这些事件实现运行状态反馈。

---

## Phase 14 执行记录（2026-09-19）

### 完成内容

- 新增 `server/app/agent/observability.py`，定义结构化 Agent 事件模型、事件名称、空实现观察器、测试记录观察器和标准日志观察器。
- 为 Agent State 增加 `request_id`、`user_id` 和 `run_started_at`，让一次运行可以被关联和统计耗时。
- 在 Collector、Graph 和基础 Workflow 中接入事件记录，覆盖需求就绪、Tool 开始/完成、信息状态更新、行程生成、校验开始/失败/完成、行程修订和最终响应等事件。
- Tool 事件记录执行耗时、成功状态和错误码；信息事件只记录状态快照，不记录原始结果。
- 事件中不记录 Prompt、Tool 参数、原始响应或 LLM 隐藏推理，且观察器异常不会中断正常业务流程。
- 当前事件通过内部观察器和 Python 结构化日志输出，尚未对外提供 SSE 或 Agent HTTP 事件流。

### 测试与验证

- 新增 `server/tests/test_agent_observability.py`，覆盖运行标识、Tool 生命周期、Graph 节点事件、JSON 日志脱敏和观察器异常隔离。
- Phase 14 可观测性专项测试：`4 passed`。
- Agent 非数据库回归：`145 passed`；Internal DB Agent 回归：`5 passed`；Phase 1～14 合计：`150 passed`。
- 固定 `agent-test` 容器执行全部 Agent pytest；Python `compileall`、Compose 配置检查和 `git diff --check` 通过。

### 当前边界

本阶段只建立内部结构化事件和日志钩子，真实 LLM、HTTP Agent API、SSE 推送和生产日志采集仍待后续接入；不会因为日志失败改变 Agent 业务结果。

---

# Phase 15：最终代码检查

完成后检查以下内容。

## Architecture

- [x] Workflow 和 ReAct 职责分离
- [x] 没有独立 Information Planner
- [x] State 结构化
- [x] Tool 与 Graph 解耦
- [x] Validator 与 LLM 解耦

## Reliability

- [x] MAX_INFO_ATTEMPTS 生效
- [x] MAX_REACT_ROUNDS 生效
- [x] MAX_VALIDATION_ROUNDS 生效
- [x] unavailable 可以正常降级
- [x] failed 可以正常降级
- [x] UNKNOWN 不触发 Reviser
- [x] FAIL 触发 Reviser

## Hallucination Control

- [x] 开放时间缺失不会虚构
- [x] 天气缺失不会虚构
- [x] 路线数据缺失不会虚构
- [x] 预算明确属于估算
- [x] Final Generator 不新增 State 中不存在的事实

## User Output

- [x] 用户看不到未验证 Itinerary
- [x] 用户看不到 Tool Raw Response
- [x] 用户看不到 ReAct 内部决策
- [x] 用户看不到 Validator 中间结果
- [x] 用户只看到 Final Response

## Phase 15 执行记录（2026-09-19）

### 检查结果

- Architecture：Workflow 与 ReAct 分工明确，没有独立 Information Planner；State、Tool Layer、Graph 和 Validator 的边界符合架构文档。
- Reliability：信息需求、ReAct 和 Validator 都有最大轮次/尝试次数；`unavailable`、`failed`、`UNKNOWN` 和 `FAIL` 的降级或修订路径均有测试覆盖。
- Hallucination Control：开放时间、天气、路线缺失不会被补写；预算明确标记为估算；Final Generator 只从结构化 State 组织事实。
- User Output：用户输出只经过 Final Response Generator，不暴露未验证行程、Tool 原始响应、ReAct 决策或 Validator 中间模型。

### 回归与工程检查

- 固定测试容器补齐 `alembic.ini` 和 `alembic/` 迁移目录后，服务端全量测试：`169 passed`。
- Agent Phase 1～15 相关回归：`150 passed`；迁移、认证、健康检查、CRUD 等服务端测试也全部通过。
- `pip check`：`No broken requirements found.`
- Python `compileall`、开发/服务端 Compose 配置检查和 `git diff --check` 通过。

### 当前边界

当前计划中的 Agent V1 Phase 0～15 已完成。真实 LLM、HTTP Agent API、SSE 事件流和真实高德网络端到端测试仍属于后续接入工作，不在本阶段范围内。

---

# 推荐实际开发顺序

不要让 Codex 一次实现全部 Phase。

建议按照以下批次执行：

```text
Batch 1
Phase 0
Phase 1
Phase 2
```

完成后先检查：

```text
项目集成
+
State
+
Requirement Analyzer
```

然后：

```text
Batch 2
Phase 3
Phase 4
```

检查：

```text
Tools
+
Normalizer
+
InformationStatus
```

然后：

```text
Batch 3
Phase 5
Phase 6
```

此时应该已经可以完成：

```text
Requirement
→ ReAct
→ Tool
→ Final Answer
```

简单 Agent 闭环。

然后：

```text
Batch 4
Phase 7
Phase 8
Phase 9
```

加入：

```text
Itinerary
+
Validator
+
Reviser
```

最后：

```text
Batch 5
Phase 10
Phase 11
Phase 12
Phase 13
Phase 14
Phase 15
```

完成整个 Travel Agent V1。

---

# Codex 执行原则

每次执行一个 Batch 时：

1. 先阅读 `Agent架构.md`。
2. 再阅读本文档。
3. 检查现有项目代码。
4. 优先复用现有模块。
5. 不修改与当前 Batch 无关的代码。
6. 不提前实现后续 Phase。
7. 每个 Phase 完成后补充必要测试。
8. 测试通过后再进入下一 Phase。
9. 如果 Specification 与现有工程存在无法直接兼容的问题，先说明冲突，不要擅自改变核心架构。
10. 不增加 Web Search、RAG 或其他未确认功能。
