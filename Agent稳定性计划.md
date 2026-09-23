# Agent 稳定性计划

更新时间：2026-09-23

## 1. 首要目标

先保证用户发送消息后能够稳定得到问答结果，再逐步恢复和完善完整的行程规划能力。

第一阶段的问答范围包括：

- 历史旅行记录查询
- 天气查询
- 景点推荐
- 预算估算
- 路线和距离查询

完整的行程规划会单独验收，因为它包含更多次 LLM 调用、Tool 调用、行程校验和可能的行程修订，耗时和失败概率都更高。

## 2. 执行原则

1. 每次只完成一个稳定性阶段，不同时修改多个无关模块。
2. 每个阶段先定义可观察的验收标准，再修改代码。
3. 每个阶段完成后运行对应回归测试，再进行服务器或手机测试。
4. 先根据请求日志定位故障阶段，再修改超时、重试或业务逻辑。
5. 日志只记录阶段、耗时、状态和错误类型，不记录 API Key、完整 Prompt、原始模型响应或隐藏推理过程。
6. 发生错误时保留用户输入，允许用户重新发送。
7. 服务端、Nginx 和 Android 的超时必须统一规划，不能只调整其中一层。

## 3. 优先级安排

优先级定义：

- **P0**：阻塞排查和验收的基础能力，必须先完成。
- **P1**：首要用户路径，先保证普通问答稳定返回。
- **P2**：规划链路的耗时、重试和错误边界，避免移动端等待或重复消耗资源。
- **P3**：完整行程规划的内容质量和长任务交互。
- **P4**：基础能力稳定后的体验和扩展能力。

### P0：补齐请求级可观测性

目标：能够明确回答“这一次请求在哪一层、哪个阶段失败”。

当前日志已经记录部分 LLM 阶段和总耗时，但 LLM 日志没有统一的 `request_id`，并发请求时无法准确关联。因此先补齐以下信息：

- 在 FastAPI 请求开始时生成或记录 `request_id`。
- 将 `request_id` 传入 Agent Runtime、LangGraph、LLM Client 和 Tool 事件。
- 记录以下阶段的开始、结束和耗时：
  - Android 请求到达 API
  - Requirement Analyzer
  - 每一轮 ReAct Decision
  - Tool 执行和结果归一化
  - Itinerary Generator
  - Validator
  - Reviser
  - Final Response
- 为请求记录最终状态：成功、LLM 超时、LLM 上游错误、Tool 失败、结果校验失败。
- 保留 Nginx 状态码与 API 状态码的对应关系。

验收标准：

- 一次请求可以通过同一个 `request_id` 串起 Android、Nginx、FastAPI、LLM 和 Tool 日志。
- 可以区分 499、502、503、504 和 Android 网络断流。
- 不需要查看 Prompt 或密钥即可确定失败阶段。

#### P0 执行记录（2026-09-23）

- 状态：已完成，服务器和手机端实测通过。
- API 请求入口生成 `request_id`，并通过请求上下文传递到 Runtime、LangGraph 和 LLM 日志。
- 新增结构化阶段事件：`stage_started`、`stage_completed`，包含 `stage_name`、`stage_duration_ms` 和 `stage_status`。
- 已覆盖 Requirement Analyzer、每轮 ReAct Decision、Tool 生命周期、Itinerary Generator、Validator、Reviser 和 Final Response。
- Tool 的完成耗时继续覆盖执行和结果归一化过程；日志只记录状态、阶段、耗时和错误码，不记录 Prompt、密钥或原始模型结果。
- API 开始、成功、LLM 失败和业务校验失败日志都包含同一个请求 ID。
- 应用显式启用 INFO 级别日志，确保 API 请求、LLM 完成事件和结构化 Agent 阶段事件进入容器日志，而不只显示 Uvicorn 访问日志。
- 已增加请求上下文恢复、API 日志关联、LLM 日志关联、阶段边界和运行时传播测试。
- 本地 Agent 回归：204 passed，1 warning。warning 为现有依赖的弃用提示。
- 服务端全量回归：229 passed，1 warning；从仓库根目录执行，避免读取 `server/.env` 中的真实 COS 凭据。
- 本机普通权限运行带 `tmp_path` 的测试会被 pytest 临时目录权限阻断；使用提升权限后 Runtime/API 回归 16 passed。
- 服务器部署验收：已完成代码包校验、容器重建、Nginx 语法检查和热重载；公网健康接口返回 200，Nginx access log 已记录 `request_id`。
- 日志修复部署：提交 `a0a1627` 已部署；API 容器已经可以看到业务层请求、LLM 和结构化阶段事件。
- 手机实测：历史查询请求经过 401、Token 刷新和 200 重试；Nginx 最终请求 ID 与 API 业务日志一致，未出现超时或 502。

### P1：稳定基础问答

目标：先让非行程规划类问题稳定返回答案。

按以下顺序逐项验证：

1. 历史记录查询
2. 天气查询
3. 景点推荐
4. 预算估算
5. 路线和距离查询

每类问答都要验证：

- 正常查询能够返回答案。
- 没有数据时能够返回明确说明。
- Tool 不可用或返回空数据时能够降级，不产生无意义的 502。
- Tool 返回异常结构时，Normalizer 能返回受控错误。
- Android 能显示服务端返回的答案或明确错误。
- 用户输入在失败后仍然可以重新发送。

验收标准：

- 五类问答在服务器和手机上连续测试通过。
- 服务端返回成功时，Android 不出现 `unexpected end of stream`。
- 认证过期时，401、Token 刷新和原请求重试流程正常。

#### P1 手工验收步骤

前置条件：

1. 服务器 API 容器正在运行，公网健康检查返回 200。
2. Android 安装指向 `https://www.cq-footmark.online/` 的 Debug APK。
3. 在“个人中心”登录共享账号，并进入“智能规划”。
4. 测试期间同时查看服务器日志：

```bash
cd /opt/footmarks/server
sudo docker compose logs -f --tail=0 api
```

另开一个 SSH 窗口查看 Nginx：

```bash
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

按以下顺序发送消息，每条消息等待上一条结束后再发送：

| 编号 | Android 输入 | 重点观察 | 通过条件 |
|---|---|---|---|
| 1 | `我之前去过哪些地方？` | `search_trip_history` | 返回非空历史回答，HTTP 200 |
| 2 | `北京明天天气怎么样？` | `weather` | 返回天气或明确的天气数据不可用提示，不出现无意义 502 |
| 3 | `推荐北京适合亲子游的景点` | `keyword_search` | 返回景点推荐或明确的空结果说明 |
| 4 | `去北京三天大概要花多少钱？` | `estimate_budget` | 返回人民币估算或明确的预算工具不可用提示 |
| 5 | `从天安门到故宫怎么走？` | `distance`、路线 Tool | 返回路线/距离信息或明确的路线数据不可用提示 |

每条消息都检查：

- 用户消息出现在列表中，发送期间不能重复提交。
- 成功时显示非空 Agent 回复，输入框保持为空。
- 失败时显示明确错误，原草稿可以恢复并重新发送。
- API 容器日志中的 `request_id` 在同一次请求的阶段事件中保持一致。
- Nginx 最终状态与 API 结果一致；不要把扫描器产生的 404 当成 Agent 失败。

补充两项边界验收：

1. 在没有对应历史记录的城市上提问，例如 `我去过哈尔滨哪些地方？`，应显示没有记录或空结果说明。
2. 临时断开手机网络后发送一条消息，确认页面保留草稿；恢复网络后重新发送，确认请求可以成功。

P1 通过标准：五类正常问答连续通过；至少完成一次无数据和断网重试；成功响应不出现 `unexpected end of stream`；服务端日志没有未解释的 502、503 或 504。Tool 异常结构归一化属于服务端自动化回归，不需要通过手机制造异常，可在本地执行：

```powershell
$env:PYTHONPATH = 'server'
.\.venv\Scripts\python.exe -m pytest server/tests -q
```

#### P1 执行结果（2026-09-23）

- P1 已完成真实手机验收：历史、天气、景点、预算和路线五类基础问答均返回有效结果。
- 历史查询已验证城市范围：查询没有记录的哈尔滨时，结构化需求提取 `destination=哈尔滨`，历史 Tool 返回空结果，最终明确提示没有去过该城市。
- 路线查询已验证地点范围：中山陵到夫子庙使用南京同一行政区的 POI 坐标，距离结果正常。
- P1 代码、测试和服务器版本已同步到 `fix/agent`；P2 继续处理规划链路耗时、重复调用和客户端断开。

### P2：控制规划链路的耗时和错误边界

目标：让规划请求在客户端预算内结束，失败时停止无意义的重复调用，并让超时原因可判断。

2026-09-23 的真实服务器日志显示：一条规划请求耗时约 208 秒后客户端断开并产生 Nginx `499`，另一条规划请求耗时约 145 秒后返回 `200`。其中 ReAct 决策单次耗时达到约 52 秒和 67 秒，Tool 和 Validator 只有毫秒级耗时。因此 P2 先处理调用次数、取消和错误边界，再继续扩展规划内容。

当前进度：P2-1 至 P2-5 已完成。ReAct Collector 的默认最大轮数从 8 轮收紧为 4 轮，达到上限后不再发起新的决策或 Tool 调用；已经进入 `completed`、`unavailable` 或 `failed` 终态的信息 Tool 不再暴露给下一轮 ReAct；新增整条请求和各 LLM 阶段预算，预算会覆盖当前 HTTP 请求的读取超时并在耗尽后停止后续阶段；API 会监测客户端断开并通过线程安全取消信号阻止后续 Agent 阶段；AMap、API、Nginx 和 Android 的超时语义已经统一。手机四类回归进一步发现并修复了两个边界：天气查询按目标日期选择预报，无法解析或超出预报范围时不回退到当天；规划达到 ReAct 上限时，只要 POI 等关键信息已完成，就允许忽略距离等可选信息进入行程生成，而不是返回“没有完整行程”。修复提交 `c219a98` 已部署，服务器本机和公网健康检查均通过。

执行顺序：

1. **限制 ReAct 轮数**：为规划设置明确的最大轮数，达到上限后返回受控结果，不继续消耗 LLM 请求。
2. **停止重复失败 Tool**：同一个 Tool 进入终态失败后，不再由 ReAct 反复请求；记录失败原因并使用降级信息继续或结束。
3. **增加阶段预算**：分别限制 Requirement Analyzer、ReAct Decision、Itinerary Generator 和 Reviser 的单次耗时与总耗时，重试不能突破整条请求预算。
4. **处理客户端断开**：Nginx 返回 499 或请求上下文取消后，Agent 应停止后续 LLM 和 Tool 调用，避免客户端已经退出后服务器继续运行几分钟。
5. **统一各层超时和状态映射**：Android、Nginx、API、LLM Provider 和 AMap 的超时要能对应到明确的 502、503 或 504。

如果同步规划在完成以上控制后仍然超过 Android 请求预算，再进入 P3 的异步任务或流式进度方案。

需要检查和统一：

- Android OkHttp 的连接、读取和整个请求超时。
- Nginx 的 `proxy_read_timeout`、`proxy_send_timeout` 和 `send_timeout`。
- 服务端 LLM Provider 的单次请求超时。
- AMap Tool 的请求超时。
- ReAct 最大轮数和信息项最大尝试次数，并确保失败 Tool 不被重复调用。
- LLM 超时不重复消耗整条移动端请求预算。
- 429、5xx、网络错误和超时分别使用明确的重试策略。

排查时使用以下对应关系：

| 现象或状态码 | 优先检查位置 |
|---|---|
| Android `SocketTimeoutException` | Android 请求预算与 API 504 是否一致 |
| Android `unexpected end of stream` | Android、Nginx 是否提前关闭连接 |
| Nginx 499 | Android 客户端先断开，通常是客户端超时 |
| Nginx 504 | Nginx 等待后端超时 |
| API 504 | LLM Provider 单次调用超时，或 Agent 总/阶段预算耗尽 |
| API 502 | LLM 上游错误、结构化结果错误或 Agent 业务校验失败 |
| API 503 | LLM 配置缺失 |
| API 200 且 Tool 日志为 `amap_timeout` | AMap 请求超时，回答继续降级并提示数据不可用 |
| API 200 但 Android 报错 | Android 解析、连接复用或 APK 版本问题 |

验收标准：

- 任意失败都能从日志判断是客户端、Nginx、API、LLM 还是 Tool。
- 正常问答在 Android 的请求预算内返回。
- 达到 ReAct 上限、Tool 终态失败或客户端断开后，不再继续无意义的 LLM 调用。
- 超时后 API 能返回明确的 504，避免连接被无提示地关闭。

### P3：稳定完整行程规划

目标：在基础问答稳定后，再处理高耗时的规划链路。

实施顺序：

1. 如果同步规划仍超过 Android 请求预算，先实现异步任务或流式进度。
2. 一日游规划
3. 二日游规划
4. 三日游规划
5. 带预算、历史避让、天气和路线约束的规划

规划链路需要单独验证：

- Requirement Analyzer 输出有效的日期和旅行需求。
- ReAct Collector 能获得足够的 POI 和相关 Tool 数据。
- Itinerary Generator 返回至少一天、日期和时间格式正确的行程。
- 空行程、未知 POI、日期不连续和时间格式错误能够触发受控重试。
- Validator 能检查营业时间、移动时间、时间冲突、每日负荷和预算。
- Reviser 只修改 Validator 指出的问题。
- 最终回答只使用经过校验的行程。

验收标准：

- 一日游连续测试通过后，再扩大到多日游。
- 规划失败时返回明确错误，不出现空回答或连接断流。
- 日志可以区分生成耗时、校验耗时和修订耗时。

### P4：体验和扩展能力

基础问答和行程规划稳定后，再开发：

- 多轮上下文记忆
- 更开放的旅行问答
- 更复杂的 Tool 编排
- 供应商切换和模型降级

## 4. 一次请求的标准链路

```text
Android 输入消息
  -> SmartPlanningViewModel
  -> CloudSession，添加 Access Token
  -> Retrofit / OkHttp HTTPS
  -> Nginx TLS 反向代理
  -> FastAPI /api/v1/agent/chat
  -> AgentRuntime
  -> LangGraph
     -> Requirement Analyzer LLM
     -> ReAct Decision LLM
     -> Tool 执行和结果归一化
     -> 信息状态更新，必要时继续 ReAct
     -> Itinerary Generator LLM（仅行程规划）
     -> Validator（本地程序）
     -> Reviser LLM（校验失败时）
     -> Final Response（本地程序）
  -> FastAPI JSON
  -> Nginx
  -> Android 显示答案
```

基础问答通常在 Final Response 前结束，不经过 Itinerary Generator、Validator 和 Reviser。因此基础问答应该先于完整行程规划验收。

## 5. 服务器日志检查方法

测试单个请求时，同时查看 API 和 Nginx 日志：

```bash
sudo docker compose logs -f --tail=0 api
```

```bash
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

正常的 Agent 请求应依次出现类似事件：

```text
Agent request started request_id=<同一个ID>
stage_started stage_name=requirement_analyzer
LLM completed request_id=<同一个ID> stage=TravelRequirement
stage_completed stage_name=requirement_analyzer stage_duration_ms=<耗时>
tool_started
tool_completed
LLM completed request_id=<同一个ID> stage=ReActDecision
LLM completed request_id=<同一个ID> stage=Itinerary
validation_started
validation_completed
final_response_ready
Agent request completed request_id=<同一个ID>
POST /api/v1/agent/chat 200
```

出现 `LLM timeout stage=Itinerary` 时，只能说明行程生成阶段的单次 LLM 调用超时；整条请求的 `duration_ms` 还包含前面的需求分析、ReAct 决策和 Tool 调用，不能把它们当成同一个耗时。

## 6. 每个阶段的开发闭环

每次开发都按以下顺序执行：

1. 明确本阶段要解决的一个问题。
2. 增加能够复现问题的测试或日志检查。
3. 修改最小范围的代码。
4. 执行本阶段回归测试。
5. 在服务器重建并验证容器状态。
6. 用手机发送一个可复现请求。
7. 记录实现效果、测试结果和遗留问题。
8. 更新 `README.md`、开发日志和本计划。

在 P0 和 P1 验收完成前，不进入新的行程规划扩展功能。
