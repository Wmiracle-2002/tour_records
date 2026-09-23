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

- 状态：已完成，等待服务器和手机端实测验收。
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
- 遗留验收：需要从手机发送一条已登录的 Agent 请求，确认 Nginx access log、API 日志中的请求 ID 和最终 HTTP 状态码可以对应起来。
- 日志修复部署：提交 `a0a1627` 已部署；发送下一条 Agent 请求后应能在 API 容器日志中看到业务层请求、LLM 和阶段事件。

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

### P2：控制整条请求的耗时和错误边界

目标：让请求在各层超时前结束，并让超时原因可判断。

需要检查和统一：

- Android OkHttp 的连接、读取和整个请求超时。
- Nginx 的 `proxy_read_timeout`、`proxy_send_timeout` 和 `send_timeout`。
- 服务端 LLM Provider 的单次请求超时。
- AMap Tool 的请求超时。
- ReAct 最大轮数和信息项最大尝试次数。
- LLM 超时不重复消耗整条移动端请求预算。
- 429、5xx、网络错误和超时分别使用明确的重试策略。

排查时使用以下对应关系：

| 现象或状态码 | 优先检查位置 |
|---|---|
| Android `unexpected end of stream` | Android、Nginx 是否提前关闭连接 |
| Nginx 499 | Android 客户端先断开，通常是客户端超时 |
| Nginx 504 | Nginx 等待后端超时 |
| API 504 | LLM Provider 单次调用超时 |
| API 502 | LLM 上游错误、结构化结果错误或 Agent 业务校验失败 |
| API 503 | LLM 配置缺失 |
| API 200 但 Android 报错 | Android 解析、连接复用或 APK 版本问题 |

验收标准：

- 任意失败都能从日志判断是客户端、Nginx、API、LLM 还是 Tool。
- 正常问答在 Android 的请求预算内返回。
- 超时后 API 能返回明确的 504，避免连接被无提示地关闭。

### P3：稳定完整行程规划

目标：在基础问答稳定后，再处理高耗时的规划链路。

实施顺序：

1. 一日游规划
2. 二日游规划
3. 三日游规划
4. 带预算、历史避让、天气和路线约束的规划

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
- 规划过程进度展示
- SSE 或流式响应
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
