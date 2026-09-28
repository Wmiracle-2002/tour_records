# Agent 参数模型修正

更新时间：2026-09-24  
优先级：P1 前置阶段，先于路线、开放时间和完整行程质量改造  
状态：代码实现完成；真实 LLM/高德联网验证待环境实测

## 1. 目标与原则

解决 Agent 外层 JSON 合法、Tool 参数却与实际签名不符的问题。当前 `ReActDecision.tool_call.arguments` 是 `dict[str, Any]`；只靠 Prompt 无法阻止未知字段、错类型和错工具真正执行。

**硬约束优先于软约束**：先统一 Agent 对外字段、定义唯一输入模型，并在执行前校验；JSON Schema 和示例从同一模型提供给 LLM，作为降低错误率的辅助信息。Prompt 不能充当最终校验。

成功标准：每个向 LLM 暴露的 Tool 都有准确契约；未通过校验的参数绝不到达 handler 或高德；确定性的上下文可安全补充，仍非法时仅让 LLM 重试同一 Tool 一次，失败后给出可定位的降级结果。

## 2. 字段语义统一

**相同含义使用相同 JSON 键；不同含义即使原先同名，也要明确区分。**统一范围是 Agent 的需求、决策上下文和 Tool 输入，不要求同时改 Android 公共 API、数据库字段或高德原始响应。服务商格式只在适配器边界处理。

| 含义 | Agent 对外键 | 使用边界 |
|---|---|---|
| 行政城市或高德城市编码 | `city` | 历史筛选、天气、POI 搜索、预算目的城市 |
| 经纬度 `经度,纬度` | `coordinates` | 周边搜索、逆地理编码；必须按坐标规则校验 |
| 路线起点、终点 | `origin`、`destination` | 可为明确地点或坐标；不能把仅有的城市当成具体景点 |
| 景点唯一标识 | `poi_id` | POI 详情；不能拿景点名称替代 |
| 旅行或筛选日期区间 | `start_date`、`end_date` | ISO 日期；相对日期先在需求层解析或保留未确定状态 |
| 历史记录类别 | `category` | 与高德 POI 类型筛选 `types` 是不同概念 |

现有高德 `around_search.location` 和 `reverse_geocode.location` 指**坐标**，并不是 `weather.city` 的同义词；把 `location="南京"` 自动改为 `city="南京"` 是错误做法。Agent 统一用 `coordinates`，高德适配器内部再映射为 `location`。`poi_detail.poi_id` 到高德请求的 `id` 也仅在适配器转换。

现有 `TravelRequirement.destination` 表示旅行目的地，可能是城市或地点；它与路线 Tool 的 `destination`（具体终点）不能无条件互相复制。实施时先明确需求层的城市字段，只有已确认是城市时才补 Tool 的 `city`。若目的地含糊，留待重试或澄清，不做字符串猜测。预算 Tool 的现有 `destination` 若表示目的城市，同步改为 Agent 对外 `city`，由预算适配器映射给当前实现；不要在一个 Tool 的公开 Schema 里同时提供两个键。

## 3. 唯一 Tool 契约与硬校验

Tool 注册信息包含 `name`、`description`、`input_model`、归属的 `information_need`、正确示例。输入模型是唯一事实来源，供执行前校验和生成 LLM 所见 JSON Schema。不要再维护另一份手写字段列表、别名表或允许忽略字段表。Schema 要表达必填、类型、枚举、范围、格式及 `additionalProperties: false`；校验发生在 handler 之前，不能只依赖 handler 内部的 Pydantic 模型。

第一批覆盖当前可供 Agent 使用的 Tool：

| Tool | Agent 对外参数与关键硬约束 |
|---|---|
| `get_travel_summary` | 空对象；任何字段均报错 |
| `search_trip_history` | `city`、`category`、`start_date`、`end_date`；日期范围有序 |
| `search_records` | `trip_id`、`city`、`category`、`min_rating`、`max_rating`、`min_cost`、`max_cost`；范围有序，金额非负 |
| `get_trip_detail` | 必填正整数 `trip_id` |
| `estimate_budget` | `city`、必填正整数 `duration_days`、`travelers`，以及 `accommodation_level`、`food_level`、`transport_mode`、`pois`；当前代码没有 `level` 字段 |
| `keyword_search` | 必填非空 `keywords`，可选 `city`、`types`、正整数 `page`、`offset` |
| `around_search` | 必填 `coordinates`，可选 `keywords`、`types`、正整数 `radius`、`page`、`offset` |
| `poi_detail` | 必填非空 `poi_id` |
| `weather` | 必填 `city`，可选布尔 `forecast`；日期不属于此 Tool 参数 |
| `distance` | 必填非空起点列表 `origins`、终点 `destination`，可选 `distance_type`（只允许当前代码支持的值）；起终点可为明确地点名或坐标，当前高德客户端会先解析地点名 |
| `driving_route`、`walking_route`、`cycling_route` | 必填 `origin`、`destination`；其余参数按对应方式实际支持情况建模 |
| `transit_route` | 必填 `origin`、`destination`、`city`；可选 `cityd` 等仅在实际支持时暴露 |

`geocode`、`reverse_geocode` 已在高德工具注册，但当前 Collector 没有它们的 `information_need` 映射。Step 1 必须二选一：给它们定义输入模型和明确的信息需求、结果归一化路径，或暂时不向 LLM 暴露。不能出现“可选工具”与“能被 Collector 正常执行的工具”不一致。

实施时逐项对照真实 handler：路线各方式的 `strategy`、`extensions`、`waypoints` 等只在已验证支持的方式中暴露；不能从统一 `route()` 签名推断每种方式都支持。已有内部输入模型应复用或改成共享的正式契约，避免一处严格、一处宽松。

校验至少包括：未知键拒绝、必填、严格类型（不依赖 Pydantic 默认强制转换）、非空文本、数值范围、枚举、坐标格式及经纬度范围、日期格式与先后、评分/费用上下界的交叉校验。`city` 不接受坐标，`coordinates` 不接受城市名称；路线和距离端点允许明确地点名或合法坐标，不能要求它们一定是坐标。可选字段缺省值由模型定义。JSON Schema 表达不了的跨字段规则，由同一模型的验证器在执行前强制执行。

工具名称与信息需求的关系由注册信息确定，不接受 LLM 覆盖。当前 `call.information_need or TOOL_INFORMATION_NEEDS.get(call.name)` 允许模型把工具结果写入错误的信息槽；改为服务端确定。`critical` 也由业务状态确定，不信任模型直接指定。需要同步调整 `ToolCall` 结构并拒绝未知控制字段，避免让模型继续输出这两个值。

## 4. 确定性修正与一次重试

保留已确认的“安全字段自动修正，然后仍不合规则让 LLM 重试一次”，但**不做通用别名猜测或未知字段静默删除**：

1. 在 Agent 对外只发布一种规范键名；历史别名若没有兼容需求，就删除现有 `_TOOL_ARGUMENT_ALIASES`，不再把 `query`、`keyword`、`location` 等都当作模型可用写法。若已有必须兼容的持久化旧调用，兼容逻辑只在该输入边界按版本处理，绝不放进 LLM Schema。
2. 仅从已校验的需求状态补充能唯一确定的缺失值。例如需求中明确 `city="南京"` 时可补天气的 `city`。不能把含糊的旅行目的地、城市或 POI 名称猜成路线终点、坐标或 POI ID。
3. 只允许无损且明文规定的文本清理，例如首尾空白；数字字符串原则上报类型错误，让 LLM 输出正确的 JSON 数值。若某个非 LLM 入口必须兼容数字字符串，应在该入口处理并单独测试。
4. 用户的“中秋天气”日期属于需求与天气能力判断：先解析实际日期，再判断高德预报覆盖范围。若日期未确定或超出范围，返回明确的不可查询结果，不能降级为“今天的天气”。LLM 把 `date` / `date_expression` 塞进 `weather.arguments` 时属于未知键错误，不能悄悄丢掉，否则可能答非所问。

处理顺序：

```text
LLM ToolCall -> 查注册契约/确定信息需求 -> 有依据的上下文补值
             -> 输入模型校验 -> 通过才调用 Tool/服务商适配器
             -> 失败时反馈字段级错误 -> 同一 Tool 最多重试一次
             -> 再失败则该需求受控降级，不调用上游、不无限循环
```

由于外层 `ReActDecision` 的 `arguments: dict[str, Any]` 无法单独保证不同工具各自的动态参数 Schema，**执行前校验是不可省的硬边界**；向 LLM 提供 Schema 和示例只用于减少重试。若后续改为每个 Tool 的判别联合类型，也仍保留执行边界校验。

重试反馈包含 `tool_name`、`error_code`、`invalid_fields`、`missing_fields`、期望类型/允许范围、`attempt`；只反馈字段规则，不输出密钥、完整参数或原始模型响应。参数重试与网络重试分开计数；只因参数错误触发，超时、提供方错误和结果归一化错误不得进入参数修正循环。重试须固定原 Tool 和信息需求，不能借机切换工具或修改 `critical`。

## 5. 错误分类与观测

目前 `ToolLayer` 把普通异常统一变成 `tool_execution_failed`。要区分：`invalid_tool_arguments`、`tool_not_found`、`tool_unavailable`、`tool_timeout`、`tool_provider_error`、`invalid_tool_response`、`tool_execution_error`。参数错误应在调用 handler 前产生；第二次失败时回答具体哪类信息未能获得，不显示笼统的 `Tool execution failed`。

日志记录 `request_id`、工具名、错误码、失败字段名、重试次数、耗时和状态。不要记录 API Key、完整参数、完整 Prompt、原始 LLM 响应或隐藏推理。

## 6. 实施步骤与逐步验收

### Step 1：字段字典和 Tool 契约

- 按第 2、3 节整理输入模型及服务商适配器；现有预算 `destination`/错误文档 `level` 与真实实现对齐。
- 注册信息、运行时模型和生成的 JSON Schema 使用同一来源；只暴露已接上信息需求与归一化的工具。
- 去掉 Agent 面向 LLM 的多套别名，保留必要的提供方字段映射。

验收：逐一核对所有已暴露 Tool 的 Schema、handler、信息需求和归一化路径；未知键和语义错误字段均在执行前拒绝。

### Step 2：向 LLM 提供准确 Schema

- `ToolDescriptor` 从输入模型生成参数 JSON Schema；为易错工具提供与模型一致的简短正反示例。
- Prompt 说明字段含义、只选当前可用工具、不能猜测缺失值；`reason` 只写操作说明。

验收：决策测试核对必填、类型、枚举、`additionalProperties: false` 与示例；不允许手写 Schema 漂移。

### Step 3：执行前校验与确定性补值

- 在 `ToolLayer` 或紧贴其前的单一边界校验 ToolCall；由注册信息确定信息需求。
- 只补能从需求中唯一确认的值，其他未知键、错类型、错含义一律反馈错误。

验收：参数错误时 handler/高德调用次数为零；合法输入仍执行一次。

### Step 4：同一工具重试一次

- 保存最近参数错误的结构化反馈；限定一次 LLM 修正，第二次失败受控结束。
- 不把上游超时、网络错误或结果错误算作参数错误。

验收：首次错误后修正成功、连续两次错误、上游失败三种路径都终止，轮次有明确上界。

### Step 5：日志及回归

- 细分错误码与脱敏日志，执行 Agent、服务端 API 的相关回归和真实问答验证。

验收：日志能定位工具与字段，且不泄露敏感值；历史、天气、POI、预算和路线的正常查询仍可用。

## 7. 边界测试清单

1. `city="南京"` 通过天气和城市筛选；`coordinates="南京"`、`city="118.78,32.04"` 都在调用前失败。`around_search` 的规范键为 `coordinates`，适配器才映射为高德 `location`。
2. `weather.arguments` 出现 `date` / `date_expression` 被拒绝并重试；用户问超出预报范围的中秋天气时，不误报今日天气。
3. `get_travel_summary` 带任意键、`get_trip_detail.trip_id<=0`、空 `poi_id` 或空 `keywords` 均拒绝。
4. 路线缺起终点、把不明确的城市当终点、公交缺 `city` 均不访问高德。
5. 预算使用不存在的 `level`、把字符串 `"3"` 当作 `duration_days`、人数为零或负数均拒绝；合法 `accommodation_level`、`food_level`、`transport_mode` 可执行。
6. 日期倒序、评分或费用上下界倒序、负费用、无效坐标、无效 `distance_type` 均反馈字段级错误。
7. LLM 提供 `information_need`、`critical` 或未知别名不能改变系统路由；`geocode` / `reverse_geocode` 要么契约及归一化完整，要么不向 LLM 暴露。
8. 参数修正只重试同一 Tool 一次；两次失败后不执行上游；网络失败不进入参数重试。
9. Schema 与运行时模型一致，正常结果、空结果、超时、提供方错误、结果归一化错误的既有回归通过；日志不含密钥或完整参数。

## 8. 本阶段边界

本阶段只解决 Tool 参数和执行契约。强制查路线、POI 搜索与详情的独立信息状态、开放时间缺失时的行程展示策略、规划后的路线补查、长任务与 Android 流式展示另行处理。参数契约稳定后，才能准确区分业务流程失败与参数失败。

## 9. 实施记录

### 2026-09-24：Step 1–5 完成

- 统一 Agent 字段：城市使用 `city`，坐标使用 `coordinates`，POI 详情使用 `poi_id`；预算参数与真实处理逻辑对齐。高德原生字段只在适配器中转换。
- 为已暴露工具建立严格输入模型；注册信息同时提供信息需求、运行 Schema 和示例。未知字段、缺失字段、错误类型、非法坐标/日期范围/数值范围等在 handler 执行前拒绝。
- 从输入模型生成传给 LLM 的 JSON Schema；决策结构拒绝额外控制字段，信息需求和 critical 状态由服务端确定。没有完整信息需求与归一化链路的 `geocode`、`reverse_geocode` 不向 LLM 暴露。
- 只从需求结构补充可唯一确定的参数；移除通用别名映射。参数校验失败时只允许同一工具重试一次，第二次仍失败会终止对应信息需求；不触发高德调用。
- 区分参数、未注册工具、超时、提供方错误和执行错误；参数重试日志只记录字段名，不记录参数值、Prompt 或密钥。
- 增加 API 级消息注入测试：直接提交与 Android 相同的 `POST /api/v1/agent/chat` 消息，验证消息进入需求分析客户端并验证工具 Schema 被传入决策客户端，不启动 Android。
- 全量服务端回归：在 `server` 目录运行 `python -m pytest -q -p no:cacheprovider`，结果 **274 passed**。唯一提示是 Starlette 测试客户端依赖弃用警告。

该自动化消息测试使用记录型 LLM 替身和本地工具响应，不访问真实 LLM/高德服务；它验证 Android 请求到 Agent 分析/决策边界的数据链路，不替代部署后对真实供应商参数兼容性的联网验证。
