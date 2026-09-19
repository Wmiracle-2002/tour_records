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

# Phase 3：建立统一 Tool Layer

## 目标

让 ReAct 不直接依赖数据库实现或 AMap MCP 返回格式。

统一：

```text
Agent
 ↓
Tool Layer
 ↓
Internal DB / Budget / AMap MCP
```

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

# Phase 3C：AMap MCP Adapter

## Step 3.6：接入 AMap MCP

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

Agent Node 不直接处理 MCP 协议细节。

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

# Phase 15：最终代码检查

完成后检查以下内容。

## Architecture

- [ ] Workflow 和 ReAct 职责分离
- [ ] 没有独立 Information Planner
- [ ] State 结构化
- [ ] Tool 与 Graph 解耦
- [ ] Validator 与 LLM 解耦

## Reliability

- [ ] MAX_INFO_ATTEMPTS 生效
- [ ] MAX_REACT_ROUNDS 生效
- [ ] MAX_VALIDATION_ROUNDS 生效
- [ ] unavailable 可以正常降级
- [ ] failed 可以正常降级
- [ ] UNKNOWN 不触发 Reviser
- [ ] FAIL 触发 Reviser

## Hallucination Control

- [ ] 开放时间缺失不会虚构
- [ ] 天气缺失不会虚构
- [ ] 路线数据缺失不会虚构
- [ ] 预算明确属于估算
- [ ] Final Generator 不新增 State 中不存在的事实

## User Output

- [ ] 用户看不到未验证 Itinerary
- [ ] 用户看不到 Tool Raw Response
- [ ] 用户看不到 ReAct 内部决策
- [ ] 用户看不到 Validator 中间结果
- [ ] 用户只看到 Final Response

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

1. 先阅读 `Travel Agent V1 - Agent Architecture Specification`。
2. 再阅读本文档。
3. 检查现有项目代码。
4. 优先复用现有模块。
5. 不修改与当前 Batch 无关的代码。
6. 不提前实现后续 Phase。
7. 每个 Phase 完成后补充必要测试。
8. 测试通过后再进入下一 Phase。
9. 如果 Specification 与现有工程存在无法直接兼容的问题，先说明冲突，不要擅自改变核心架构。
10. 不增加 Web Search、RAG 或其他未确认功能。