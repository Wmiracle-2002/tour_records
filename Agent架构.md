# Travel Agent V1 - Agent Architecture Specification

## 1. 目标

实现一个基于 **LangGraph** 的旅行规划 Agent。

系统采用：

> Workflow + ReAct Agent

混合架构。

其中：

- Workflow 负责整体业务流程和节点跳转。
- ReAct Agent 根据当前用户需求、已有信息以及可用工具，动态决定下一步需要获取什么信息。
- 所有业务数据写入结构化 State。
- LLM 负责需求理解、信息获取决策、行程生成和局部修改。
- 可确定性计算的行程校验由程序 Validator 完成。
- 只有最终经过校验后的结果允许生成用户可见回答。
- V1 不接入 Web Search。

---

## 2. 整体流程

```text
User
 ↓
Requirement Analyzer
 ↓
ReAct Information Collector
 ↕
 ├── Internal DB Tools
 ├── estimate_budget
 └── AMap MCP
 ↓
Structured Itinerary Generator
 ↓
Itinerary Validator
 ↓
 ├── PASS / UNKNOWN
 │        ↓
 │   Final Response Generator
 │        ↓
 │       END
 │
 └── FAIL
          ↓
     Local Itinerary Reviser
          ↓
       Validator
```

对于非 `trip_planning` 类型请求，不强制经过 Itinerary Generator 和 Validator。

例如：

- `weather_query`
- `route_query`
- `history_query`
- `budget_query`
- `poi_recommendation`
- `general_query`

在 ReAct 信息收集完成后，可以直接进入 Final Response Generator。

---

# 3. Requirement Analyzer

Requirement Analyzer 负责：

1. 判断用户主要任务类型。
2. 提取旅行相关参数。
3. 提取用户偏好。
4. 提取硬性约束。

Requirement Analyzer **不负责**：

- 决定调用哪些 Tool。
- 规划 Tool 调用顺序。
- 判断是否需要天气、路线、历史等信息。

这些工作交给后续 ReAct Agent。

建议结构：

```python
class TravelRequirement(BaseModel):
    intent: Literal[
        "trip_planning",
        "poi_recommendation",
        "route_query",
        "weather_query",
        "budget_query",
        "history_query",
        "general_query",
    ]

    origin: str | None = None
    destination: str | None = None

    start_date: str | None = None
    end_date: str | None = None
    duration_days: int | None = None

    travelers: int | None = None
    budget: float | None = None

    preferences: list[str] = []
    constraints: list[str] = []
```

其中：

- `preferences`：尽量满足的软偏好。
- `constraints`：必须满足的硬性条件。

例如：

```json
{
  "intent": "trip_planning",
  "origin": "上海",
  "destination": "南京",
  "start_date": "2026-10-01",
  "duration_days": 3,
  "travelers": 2,
  "budget": 3000,
  "preferences": [
    "历史文化",
    "当地美食"
  ],
  "constraints": [
    "避免以前去过的景点"
  ]
}
```

---

# 4. ReAct Information Collector

ReAct Collector 根据：

```text
TravelRequirement
+
InformationStatus
+
CollectedInfo
+
Available Tools
```

决定下一步：

```text
调用 Tool
OR
停止信息收集
```

不设置独立 Information Planner。

信息规划能力直接由 ReAct Agent 完成。

典型过程：

```text
需求分析
 ↓
发现需要历史记录
 ↓
search_trip_history
 ↓
更新 State
 ↓
发现需要候选 POI
 ↓
AMap POI Search
 ↓
更新 State
 ↓
发现需要路线
 ↓
AMap Route
 ↓
更新 State
 ↓
发现需要预算
 ↓
estimate_budget
 ↓
信息充分
 ↓
不再产生 Tool Call
```

---

# 5. Internal Tools

V1 内部数据库 Tool：

```text
get_travel_summary
search_trip_history
search_records
get_trip_detail
```

## 5.1 get_travel_summary

获取用户整体旅行统计和旅行画像。

例如：

- `trip_count`
- `city_count`
- `total_spending`
- `avg_rating`

## 5.2 search_trip_history

按照城市、日期等条件查询历史旅行。

## 5.3 search_records

查询旅行中的细粒度记录，例如：

- 景点
- 餐厅
- 酒店
- 消费
- 评分
- 笔记

## 5.4 get_trip_detail

根据 `trip_id` 获取完整旅行详情。

---

# 6. Internal Computation Tool

V1 提供：

```text
estimate_budget
```

根据以下信息估算旅行预算：

- 城市
- 天数
- 人数
- 住宿档次
- 饮食档次
- 交通方式
- POI

预算结果属于估算范围。

如果没有可靠实时价格数据，不允许声称预算是实时精确价格。

---

# 7. AMap MCP

V1 使用高德地图 MCP 作为地理信息基础设施。

主要使用：

- 关键词搜索
- 周边搜索
- POI 详情
- 地理编码
- 逆地理编码
- 天气查询
- 距离测量
- 驾车路径规划
- 公交路径规划
- 步行路径规划
- 骑行路径规划

V1 不集成 Web Search。

---

# 8. Structured State

业务信息必须写入结构化 State。

`messages` 主要用于：

- LLM 上下文
- Tool Calling
- ReAct Observation

结构化 State 用于：

- 保存用户需求
- 保存已经获取的信息
- 保存信息获取状态
- 保存结构化行程
- 保存 Validator 结果
- 保存最终结果

核心原则：

> messages 管 Agent 的交互过程，Structured State 管 Agent 已经知道的业务事实。

建议：

```python
class TravelAgentState(TypedDict):
    messages: Annotated[list, add_messages]

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

# 9. Information Status

需要显式记录每类信息当前状态。

```python
class InfoRequirement(BaseModel):
    status: Literal[
        "pending",
        "completed",
        "unavailable",
        "failed",
    ]

    critical: bool = False
    attempts: int = 0
    reason: str | None = None
```

例如：

```python
class InformationStatus(BaseModel):
    history: InfoRequirement | None = None
    pois: InfoRequirement | None = None
    weather: InfoRequirement | None = None
    routes: InfoRequirement | None = None
    distances: InfoRequirement | None = None
    budget: InfoRequirement | None = None
```

状态含义：

| Status | Meaning |
|---|---|
| `pending` | 尚未完成获取 |
| `completed` | 成功获取 |
| `unavailable` | Tool 正常工作，但没有找到相关信息 |
| `failed` | Tool 调用异常，经过重试仍无法获得 |

`unavailable` 和 `failed` 都属于终止状态，避免 ReAct 无限重复查询。

---

# 10. Tool 重试机制

对于同一个 Information Need：

如果连续获取失败或返回空结果：

```text
attempts += 1
```

最大尝试次数：

```python
MAX_INFO_ATTEMPTS = 3
```

达到 3 次后：

正常调用但无结果：

```text
status = unavailable
```

调用异常：

```text
status = failed
```

随后停止继续获取该项信息。

注意：

重试次数针对的是 **Information Need**，而不是单纯针对 Tool 名称。

例如：

```text
route(A → B)
```

属于一个具体的信息需求。

---

# 11. Critical Information

Information Need 可以设置：

```python
critical: bool
```

用于区分核心信息和可降级信息。

例如用户询问：

```text
南京明天天气怎么样？
```

则：

```text
weather.critical = True
```

如果 weather 无法获得，应明确说明无法获得该核心信息。

但对于：

```text
帮我规划南京三日游
```

天气可以属于：

```text
weather.critical = False
```

如果无法获得天气，允许继续规划。

最终结果必须明确告知用户：

> 未获取到对应日期的可靠天气信息，因此本次行程未考虑天气因素。

---

# 12. ReAct 退出机制

ReAct Collector 使用三层退出控制。

## 12.1 LLM 不产生 Tool Call

表示 Agent 主观认为信息已经足够。

## 12.2 Information Status

检查 Required Information 是否已经进入终止状态：

```text
completed
unavailable
failed
```

如果仍存在：

```text
pending
```

则继续 ReAct。

## 12.3 最大 ReAct 轮次

设置：

```python
MAX_REACT_ROUNDS = 8
```

达到最大轮次后强制停止。

该值后续根据实际测试调整。

---

# 13. Collected Info

Tool 原始结果不能直接长期存入 State。

必须经过：

```text
Raw Tool Result
 ↓
Normalizer
 ↓
Business Model
 ↓
CollectedInfo
```

例如：

```python
class CollectedInfo(BaseModel):
    history: TravelHistoryInfo | None = None

    pois: list[POIInfo] = []

    weather: WeatherInfo | None = None

    routes: list[RouteInfo] = []

    distances: list[DistanceInfo] = []

    budget: BudgetInfo | None = None
```

---

# 14. POI Model

示例：

```python
class POIInfo(BaseModel):
    poi_id: str
    name: str

    address: str | None = None
    location: str

    category: str | None = None

    opening_hours: str | None = None
```

如果无法获得可靠开放时间：

```python
opening_hours = None
```

禁止由 LLM 根据记忆补充开放时间。

---

# 15. Route Model

示例：

```python
class RouteInfo(BaseModel):
    origin_id: str
    destination_id: str

    mode: Literal[
        "walking",
        "driving",
        "transit",
        "cycling",
    ]

    distance_meters: int
    duration_minutes: int
```

Validator 使用这些结构化数据进行确定性检查。

---

# 16. Structured Itinerary Generator

对于：

```text
intent == trip_planning
```

信息收集完成后进入 Structured Itinerary Generator。

该节点由 LLM 实现。

输入：

```text
TravelRequirement
+
CollectedInfo
```

输出必须是结构化数据。

禁止直接生成最终用户回答。

例如：

```python
class ItineraryItem(BaseModel):
    poi_id: str
    poi_name: str

    start_time: str
    end_time: str

    activity_type: str

    estimated_cost: float | None = None


class ItineraryDay(BaseModel):
    date: str
    items: list[ItineraryItem]


class Itinerary(BaseModel):
    days: list[ItineraryDay]
```

该结果属于内部 Agent 数据。

未经 Validator 检查，不允许展示给用户。

---

# 17. Itinerary Validator

Validator 尽可能使用确定性程序逻辑，而不是让 LLM 自由判断。

V1 主要检查：

1. `opening_hours`
2. `travel_time`
3. `time_conflict`
4. `daily_load`
5. `hard_constraints`
6. `budget`

---

# 18. Opening Hours Validation

如果有可靠开放时间：

```text
planned_time
VS
opening_hours
```

进行检查。

例如：

```text
计划：08:00
开放：09:00

→ FAIL
```

如果没有可靠开放时间：

```text
opening_hours = None
```

则：

```text
UNKNOWN
```

不能：

- 判定为 PASS。
- 判定为 FAIL。
- 让 LLM 虚构开放时间。

最终必须向用户说明该信息没有完成验证。

---

# 19. Travel Time Validation

例如：

```text
A结束：
11:30

A → B：
45 min

B开始：
11:45
```

实际最早：

```text
12:15
```

因此：

```text
FAIL
```

Validator 返回具体问题。

---

# 20. Time Conflict Validation

检查：

- 同一天活动是否时间重叠。
- 活动之间是否预留足够移动时间。

---

# 21. Hard Constraint Validation

硬约束必须尽量通过程序判断。

例如：

```text
不要去以前去过的景点
```

可以检查：

```text
planned_poi_ids
∩
visited_poi_ids
```

如果不为空：

```text
FAIL
```

Preference 不作为硬性 Validator 条件。

例如：

```text
喜欢文艺一点
```

属于软偏好，不应直接导致 Validator FAIL。

---

# 22. Validation Result

建议：

```python
class ValidationIssue(BaseModel):
    type: Literal[
        "opening_hours",
        "travel_time",
        "time_conflict",
        "daily_load",
        "constraint",
        "budget",
    ]

    status: Literal[
        "fail",
        "unknown",
    ]

    day: int | None = None

    related_poi_ids: list[str] = []

    message: str

    suggested_action: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = []
```

其中：

```text
FAIL
→ 需要修改行程

UNKNOWN
→ 不触发行程修改
→ 最终告知用户
```

---

# 23. Local Itinerary Reviser

Validator 出现 FAIL 时进入 Reviser。

Reviser 由 LLM 实现。

输入：

```text
Current Itinerary
+
Validation Issues
+
TravelRequirement
+
Relevant CollectedInfo
```

核心原则：

> 只修改 Validator 指出的相关部分。

例如：

```text
Day 1 FAIL
Day 2 PASS
Day 3 PASS
```

禁止无理由重新生成 Day 2 和 Day 3。

如果：

```text
A → B → C
```

只有：

```text
B → C
```

存在时间问题，则优先修改 B / C 的：

- 时间
- 顺序
- 地点

避免重新规划整个行程。

---

# 24. Validation Loop

流程：

```text
Generator
 ↓
Validator
 ↓
FAIL
 ↓
Local Reviser
 ↓
Validator
```

设置：

```python
MAX_VALIDATION_ROUNDS = 2
```

避免无限：

```text
生成
→ 修改
→ 检查
→ 修改
→ 检查
...
```

达到最大次数后停止继续修改，并将仍无法解决的问题交给 Final Response Generator 明确告知用户。

---

# 25. Final Response Generator

只有该节点负责生成用户可见文本。

输入：

```text
TravelRequirement
+
CollectedInfo
+
Validated Itinerary
+
ValidationResult
```

对于非行程请求：

```text
TravelRequirement
+
CollectedInfo
```

即可生成最终回答。

Final Generator 负责：

- 组织自然语言。
- 展示行程。
- 展示路线信息。
- 展示天气信息。
- 展示预算。
- 展示注意事项。
- 展示未能验证的信息。

Final Generator 不允许新增事实数据。

尤其禁止自行补充：

- 开放时间
- 天气
- 路线时间
- 距离
- 门票
- 价格
- 地址
- 历史旅行记录

这些事实必须来自 Structured State。

---

# 26. 信息缺失降级原则

系统必须遵守：

> 不知道 ≠ 失败，也不允许虚构。

例如：

```text
opening_hours unavailable
```

则最终回答应明确说明：

> 暂未获取到该景点可靠的开放时间，本行程未完成该项开放时间校验，建议出发前确认当天开放安排。

天气无法获取：

> 暂未获取到对应日期的可靠天气信息，因此本次行程未将天气因素纳入安排。

历史数据为空：

> 未查询到相关历史旅行记录，因此本次行程未基于历史游览记录进行去重。

---

# 27. 用户可见内容原则

以下内容属于内部数据，不直接展示：

- Requirement Analyzer Output
- InformationStatus
- Tool Raw Result
- ReAct 内部决策
- Structured Itinerary Draft
- Validation Intermediate Result
- Reviser Intermediate Result

用户只看到：

```text
Final Response Generator
```

生成的最终结果。

禁止向用户暴露内部 ReAct 推理过程。

---

# 28. State 字段所有权

| State Field | Writer | Reader |
|---|---|---|
| `messages` | Agent / Tools | ReAct |
| `requirement` | Requirement Analyzer | ReAct / Generator / Validator |
| `information_status` | ReAct / Tool Handler | ReAct / Workflow |
| `collected_info` | Tool Handler | ReAct / Generator / Validator |
| `itinerary` | Generator / Reviser | Validator / Final Generator |
| `validation` | Validator | Reviser / Final Generator |
| `react_round` | Workflow | Workflow |
| `validation_round` | Workflow | Workflow |
| `final_response` | Final Generator | User |

各节点原则上只修改自己负责的 State 字段。

---

# 29. V1 核心设计原则

实现过程中必须遵守：

1. Workflow 管流程，ReAct 管动态决策和 Tool 调用。
2. 不实现独立 Information Planner。
3. Requirement Analyzer 只负责理解需求。
4. Tool 数据必须进入 Structured State。
5. 不依赖 ToolMessage 作为长期业务数据存储。
6. Raw Tool Response 必须经过 Normalizer。
7. ReAct 有最大轮次限制。
8. 单个 Information Need 最大尝试 3 次。
9. Tool 无结果不允许无限重试。
10. `unavailable` 和 `failed` 都属于终止状态。
11. 核心信息失败与非核心信息失败需要区分。
12. LLM 负责生成行程。
13. Validator 优先使用确定性程序逻辑。
14. Validator 不允许依赖 LLM 猜测事实。
15. 缺失可靠数据时使用 UNKNOWN。
16. UNKNOWN 不触发行程修改。
17. FAIL 才触发 Local Reviser。
18. Reviser 只修改存在问题的局部行程。
19. 未校验的行程不能展示给用户。
20. Final Generator 是唯一生成最终用户可见回答的节点。
21. Final Generator 不允许虚构 State 中不存在的事实信息。
22. V1 不集成 Web Search。

---

# 30. V1 Agent Graph

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
  │   Normalize Result
  │     ↓
  │   Update Structured State
  │     ↓
  │   ReAct Collector
  │
  └── NO
        ↓
 Information Complete?
   ├── NO → ReAct Collector
   │
   └── YES
          ↓
      Intent Type?
       /        \
trip_planning   other
     ↓            ↓
Structured     Final Response
Itinerary       Generator
Generator          ↓
     ↓             END
Validator
     ↓
 ┌── FAIL ──────────────┐
 │                      ↓
 │               Local Reviser
 │                      ↓
 │                  Validator
 │
 └── PASS / UNKNOWN
            ↓
     Final Response Generator
            ↓
           END
```

---

# 31. 实现顺序

按照以下顺序实现：

```text
State Models
↓
Requirement Analyzer
↓
ReAct Collector
↓
Tool Integration Interface
↓
Tool Result Normalizer
↓
Structured Itinerary Generator
↓
Validator
↓
Local Reviser
↓
Final Response Generator
↓
LangGraph Wiring
```

---

# 32. 工程约束

实现时保持模块解耦。

AMap MCP、数据库 Tool 和预算 Tool 应通过统一 Tool 层接入，不要将具体外部 Tool 实现逻辑直接耦合进 LangGraph Node。

Validator 应设计为可扩展结构，后续可以继续增加新的 Validation Rule。

当前阶段以完成 Agent 主流程和模块边界为目标。

不要额外增加以下未确定功能：

- Web Search
- RAG
- 旅行攻略知识库
- 其他未在本文档中定义的 Agent Node
- 其他未经确认的 Tool

如果现有项目代码结构与本文档存在冲突，应优先保持现有工程兼容性，并按照本文档中的职责边界进行实现。