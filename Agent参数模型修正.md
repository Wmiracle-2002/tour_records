# Agent 参数模型修正

更新时间：2026-09-24  
优先级：P1 前置阶段，先于路线、开放时间和完整行程质量改造  
状态：设计已确认，待按本文实施

## 1. 目标

解决 Agent 当前“外层 JSON 合法，但 Tool 参数不符合实际签名”的问题。

当前 `ReActDecision.tool_call.arguments` 是 `dict[str, Any]`，LLM 只看到 Tool 名称和一段文字描述，看不到准确的字段、类型、必填关系和调用示例。因此会出现以下问题：

- 天气 Tool 收到 `date`、`date_expression` 等不支持的字段，调用在到达高德之前就失败；
- 城市、地点、景点 ID 等字段名称混用；
- 路线 Tool 缺少 `origin` 或 `destination`，或者把城市名称和 POI 名称放错字段；
- 历史记录、预算 Tool 收到不属于自身的参数；
- 参数校验异常被统一转换为 `Tool execution failed`，无法判断是 LLM 参数错误还是上游服务错误；
- 同类参数错误可能被重复尝试，浪费 LLM 调用次数。

本阶段的成功标准：任何 Tool 在真正执行前都必须经过对应的参数模型校验；可安全修正的字段自动修正，仍不符合规范时让 LLM 根据结构化错误重试一次，第二次仍失败则受控降级，不能产生模糊的通用错误。

## 2. 已确认的处理策略

采用“安全字段自动修正，仍不合规则让 LLM 重试一次”的策略。

### 2.1 可以自动修正的内容

只允许明确、无歧义的修正：

1. 字段别名转换。

   例如：

   ```json
   {"location": "南京"}
   ```

   在天气 Tool 中转换为：

   ```json
   {"city": "南京"}
   ```

2. 从 `TravelRequirement` 补充确定的默认值。

   例如天气参数缺少 `city`，但需求分析已经得到 `destination="南京"`，可以补充 `city="南京"`。

3. 只做契约允许的简单类型转换。

   例如把可确认的数字字符串转换为整数或浮点数。不能把含糊的自然语言直接猜成数字。

4. 删除明确标记为“上下文字段”的字段。

   例如天气请求中的 `date`、`date_expression`、`start_date`、`end_date` 不属于高德天气接口参数，但日期信息会由 `TravelRequirement` 和 Collector 负责筛选，因此可以记录为已处理的上下文字段，不转发给 Tool。

### 2.2 不允许自动猜测的内容

以下情况必须进入参数错误重试：

- 缺少必填字段，且无法从需求中唯一补充；
- 一个字段同时出现两个不同值的别名；
- 城市、地点、POI ID 无法判断；
- 出行方式、历史记录类型等枚举值不在允许范围内；
- 数字、日期、坐标或列表格式无法可靠转换；
- 未知字段不是已登记的上下文字段；
- 参数之间互相矛盾。

不能静默丢弃任意未知字段。只有 Tool 契约中明确列出的上下文字段可以被忽略，其他未知字段必须报错并反馈给 LLM。

## 3. Tool 参数契约

### 3.1 每个 Tool 必须有输入模型

在 Tool 注册信息中增加以下内容：

- `name`：Tool 名称；
- `description`：用途和适用场景；
- `input_model`：对应的 Pydantic 参数模型；
- `aliases`：允许的字段别名；
- `context_fields`：允许接收但不转发给实际接口的上下文字段；
- `examples`：至少一个正确调用示例和必要的错误示例。

输入模型默认使用 `extra="forbid"`，保证未知字段不会直接进入真实 Tool。

### 3.2 第一批参数模型

需要覆盖当前所有 Agent Tool：

| Tool | 参数模型需要明确的内容 |
|---|---|
| `get_travel_summary` | 不接受任何参数 |
| `search_trip_history` | `city`、`category`、`start_date`、`end_date` |
| `search_records` | `trip_id`、`city`、`category`、`min_rating`、`max_rating`、`min_cost`、`max_cost` |
| `get_trip_detail` | 必填 `trip_id`，且必须为正整数 |
| `estimate_budget` | `destination`、`duration_days`、`travelers`、`level` |
| `keyword_search` | 必填 `keywords`，可选 `city`、`types`、`page`、`offset` |
| `around_search` | 必填 `location`，可选 `keywords`、`types`、`radius`、`page`、`offset` |
| `poi_detail` | 必填 `poi_id` |
| `weather` | 必填 `city`，可选 `forecast`；日期只作为上下文，不传给高德 |
| `distance` | 必填 `origins`、`destination`，可选 `distance_type` |
| `driving_route` | 必填 `origin`、`destination`，可选 `city`、`strategy`、`waypoints` |
| `transit_route` | 必填 `origin`、`destination`、`city`，可选 `cityd`、`strategy`、`waypoints` |
| `walking_route` | 必填 `origin`、`destination`，可选 `city`、`waypoints` |
| `cycling_route` | 必填 `origin`、`destination`，可选 `city`、`waypoints` |

已有的 `SearchTripHistoryInput`、`SearchRecordsInput`、`GetTripDetailInput` 和 `EstimateBudgetInput` 应作为正式 Tool 契约复用或统一整理，避免同一 Tool 在不同位置有两套字段规则。

## 4. 提供给 LLM 的格式

`ToolDescriptor` 不再只包含名称和一句描述，至少增加：

```json
{
  "name": "weather",
  "description": "查询指定城市的天气；用户说某个节日或日期时仍使用 city，日期由系统上下文处理",
  "parameters": {
    "type": "object",
    "properties": {
      "city": {"type": "string", "description": "城市名称或高德城市编码"},
      "forecast": {"type": "boolean", "default": false}
    },
    "required": ["city"],
    "additionalProperties": false
  },
  "examples": [
    {
      "tool_call": {
        "name": "weather",
        "arguments": {"city": "南京", "forecast": true}
      }
    }
  ]
}
```

Prompt 必须明确：

- 只能使用当前 `available_tools` 中的 Tool；
- `arguments` 必须严格匹配对应 Tool 的参数 Schema；
- 不要把用户日期、解释文字或内部上下文字段放入 Tool 参数，除非 Schema 明确允许；
- 不要把城市名称、POI 名称、POI ID 混用；
- 缺少必填参数时不要猜测，返回当前 Tool 调用并等待系统反馈或选择其他可用 Tool；
- `reason` 只写简短操作说明，不输出隐藏推理过程。

每个容易出错的 Tool 都要有一个正确示例和一个边界示例。示例必须与实际输入模型和实际 handler 签名保持一致，不能只修改 Prompt 而不修改模型。

## 5. 参数处理流程

统一流程如下：

```text
LLM ReActDecision
        |
        v
读取 ToolSpec
        |
        v
字段别名和上下文默认值修正
        |
        +---- 修正后通过输入模型 ----> 执行 Tool
        |
        +---- 仍不通过 -----------> 生成结构化参数错误反馈
                                      |
                                      v
                                LLM 重试一次
                                      |
                       +--------------+--------------+
                       |                             |
                    通过                         再次失败
                       |                             |
                    执行 Tool                  标记为 failed
                                                   受控降级
```

### 5.1 参数错误反馈模型

建议增加内部模型 `ToolArgumentError`，至少包含：

- `tool_name`；
- `error_code`；
- `invalid_fields`；
- `missing_fields`；
- `expected_schema_summary`；
- `retryable`；
- `attempt`。

反馈给 LLM 时只提供字段名、类型和修正要求，不提供 API Key、完整请求内容或敏感参数值。

### 5.2 重试限制

- 每次逻辑 Tool 调用最多进行一次参数修正重试；
- 参数错误重试与上游网络重试分开计数；
- 第二次参数仍非法时，不再调用上游接口；
- 不得因为参数错误无限增加 ReAct 轮次；
- 最终回答必须说明具体 Tool 信息不可用及原因，例如“天气查询参数未通过校验”，不能统一显示“Tool execution failed”。

## 6. 错误分类和日志

当前 `ToolLayer` 将所有普通异常都转成 `tool_execution_failed`，需要拆分为：

- `invalid_tool_arguments`：调用前参数模型校验失败；
- `tool_not_found`：Tool 名称不存在；
- `tool_unavailable`：依赖服务未配置或暂时不可用；
- `tool_timeout`：上游请求超时；
- `tool_provider_error`：上游返回业务错误；
- `invalid_tool_response`：返回结果无法归一化；
- `tool_execution_error`：Tool 内部未预期异常。

日志只记录：

- `request_id`；
- `tool_name`；
- `error_code`；
- 参数校验失败的字段名；
- 参数修正次数；
- Tool 执行耗时和状态。

禁止记录 API Key、完整参数值、完整 Prompt、原始模型响应和隐藏推理过程。

## 7. 实施步骤

### Step 1：建立 ToolSpec 和输入模型

- 整理所有 Tool 的 Pydantic 输入模型；
- 为字段补充类型、约束和中文说明；
- 统一 `extra="forbid"`；
- 让 Tool Registry 保存输入模型、别名、上下文字段和示例；
- 保持已有 Tool 的业务行为不变。

验收：每个已注册 Tool 都能生成 JSON Schema，错误字段不会进入 handler。

### Step 2：扩展 ReAct 上下文和 Prompt

- 扩展 `ToolDescriptor`，向 LLM 提供 JSON Schema 和示例；
- 增加天气、路线、历史、预算四类最容易出错的 Prompt 示例；
- 增加参数不确定时的行为约束；
- 保持不输出隐藏推理过程。

验收：LLM 决策测试能够断言收到的 Tool Schema、必填字段和示例。

### Step 3：实现安全修正和输入校验

- 将当前 `_normalize_tool_arguments` 改为基于 ToolSpec 的统一处理器；
- 支持显式别名、需求上下文默认值和有限类型转换；
- 对未知字段执行白名单处理；
- 参数不通过时不调用真实 Tool。

验收：天气带日期字段、路线缺参数、历史字段别名、预算数字字符串等边界用例均有明确结果。

### Step 4：增加一次参数重试

- 在 Agent State 中保存最近一次参数错误反馈；
- 下一轮 ReAct Context 携带结构化错误，而不是只返回笼统错误；
- 增加单次参数重试计数；
- 第二次失败后进入受控降级。

验收：首次错误、第二次修正成功、连续两次错误三个场景都能结束，不出现死循环。

### Step 5：完善错误日志和回归测试

- 拆分错误码；
- 日志记录错误类型和字段名；
- 保证参数值和密钥不进入日志；
- 运行 Agent 全量回归、服务端 API 回归和真实服务器基础问答。

验收：日志能够区分参数错误、上游错误和归一化错误；原有历史、天气、POI、预算、路线查询仍然可用。

## 8. 测试清单

必须覆盖以下边界：

1. 天气参数包含 `date`、`date_expression` 时，日期被当作上下文处理，不产生 Python `unexpected keyword` 错误。
2. 天气缺少 `city`，但 `destination` 唯一时可以补充；两者都缺少时进入参数重试。
3. 路线缺少 `origin` 或 `destination` 时不访问高德接口。
4. 路线使用 `from`、`to` 等别名时，只有在 ToolSpec 明确登记后才允许转换。
5. `get_travel_summary` 收到任意参数时，返回参数错误而不是模糊的执行错误。
6. 历史查询的 `city`、`category`、日期字段类型错误时，返回字段级错误。
7. 预算的 `duration_days`、`travelers` 为数字字符串时按约定转换；负数、零和无法转换的文本被拒绝。
8. 未知字段不能被静默转发给 handler。
9. 参数错误最多触发一次 LLM 重试。
10. 第二次仍失败时，最终回答明确说明参数校验失败，且不再调用上游 Tool。
11. 日志不包含 API Key、完整 Prompt、原始模型响应和敏感参数值。
12. 现有正常 Tool 调用、空结果、上游错误、超时和归一化错误测试全部通过。

## 9. 本阶段边界

本文优先解决“Tool 参数格式和调用契约不可靠”的问题。

以下内容放到参数契约稳定后单独处理：

- 行程规划必须强制查询路线；
- POI 搜索与 POI 详情的独立信息状态；
- 开放时间缺失时是否阻止展示完整行程；
- 生成行程后按相邻 POI 补查路线；
- 行程规划的长任务、流式进度和 Android 展示协议。

这些问题依赖稳定的 Tool 参数模型，否则无法判断失败究竟来自业务流程还是参数格式。

## 10. 完成标准

本阶段完成后，以下行为必须成立：

- LLM 生成的外层 JSON 和 Tool 参数都经过模型校验；
- Tool 参数错误不再以笼统的 `Tool execution failed` 掩盖；
- 安全字段可以自动修正；
- 不安全或含糊字段会反馈给 LLM，并最多重试一次；
- 参数仍不合规时不会调用上游服务，也不会无限循环；
- 日志可以准确定位参数校验失败的 Tool 和字段；
- 真实天气、历史、景点、预算和路线问答回归通过。
