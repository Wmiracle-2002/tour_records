# FastAPI Middleware 开发计划

状态：方案，尚未实施。本方案指 **FastAPI 的 HTTP Middleware**：在 `create_app()` 内用 `@application.middleware("http")` 注册函数，通过 `Request`、`call_next`、`Response` 处理每个请求。目标是让每一次 HTTP 请求都能用同一个 ID 串起 Nginx、FastAPI 和 Agent 日志，并能分辨 FastAPI 处理耗时与 Agent 各阶段耗时。Nginx 配置只是后续联调项目，不是 middleware 的实现位置。

## 现状与问题

- `server/nginx/footmarks.conf` 已用 `$request_id` 记录访问并转发 `X-Request-ID`，但还没有记录代理总耗时和上游耗时。
- `server/app/main.py` 尚未注册 `@application.middleware("http")`。404 与 422 由 FastAPI 全局异常处理器转换为统一错误结构。
- `server/app/api/agent.py` 仅在进入聊天路由后读取或生成请求 ID、设置响应头、计算耗时；认证失败的 401、参数错误的 422、其他 API 请求都绕过了这套记录。
- Agent 的 `observability.py` 已用 `ContextVar` 传递 ID；LLM、高德和工具阶段有各自的业务耗时与状态日志。它们提供的细节应保留。

## 职责边界

| 层 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| Nginx | 生成入口请求 ID、转发 ID、记录网关状态与耗时 | 推断 Agent 失败阶段 |
| FastAPI HTTP Middleware | 在 `call_next` 前后为所有 API 请求确定 ID、传递上下文、回写响应头、记录处理耗时与 HTTP 状态 | 读取请求正文、解析业务参数、重试 LLM/高德 |
| FastAPI 参数模型与依赖 | 请求字段的类型、长度、格式校验；鉴权与资源归属 | HTTP 访问日志 |
| 全局异常处理器 | 保持现有 404/422 错误契约，处理未捕获异常的通用 500 响应 | 更改 Agent 业务错误含义 |
| Agent 业务层 | 意图、工具参数校验，阶段/工具/LLM 耗时和失败原因 | 重复生成 HTTP 请求 ID |

**关键取舍：**只加一层 FastAPI 请求观测 middleware。它可以统一校验请求 ID 等跨接口的 HTTP 元数据；业务参数继续由 Pydantic 模型、鉴权依赖与工具模型校验，422 由已有 `RequestValidationError` 处理器记录。把所有业务参数塞进 middleware 既看不到业务语义，也可能影响下游读取请求体。现有 Agent 工具参数日志按原有约定保留，middleware 本身不记录正文、完整 URL 查询串、Token、Cookie 或 API Key。

## FastAPI 中如何接入

在 `server/app/main.py` 的 `create_app()` 中注册一个 HTTP middleware，核心流程如下（伪代码，具体异常与日志字段以测试确定）：

```python
@application.middleware("http")
async def trace_request(request: Request, call_next):
    request_id = get_or_create_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    started_at = monotonic()
    with request_context(request_id):
        try:
            response = await call_next(request)
        except Exception:
            # 记录异常类型与耗时，继续抛出，交由 FastAPI 的 500 处理器响应
            raise
    response.headers["X-Request-ID"] = request_id
    # 记录响应状态、处理耗时及 request_id
    return response
```

这里的 `call_next(request)` 代表进入鉴权依赖、参数模型、路由和现有异常处理器；返回后可统一加响应头并记录状态。`RequestValidationError` 等具体错误仍在 FastAPI 异常处理器里转换为现有 JSON 格式。未捕获的异常另由 500 处理器构造响应，使用 `request.state.request_id` 回写响应头；middleware 不吞异常。

当前接口没有流式响应，因此先采用这套官方 HTTP Middleware 写法。它记录的是 `call_next` 返回响应对象前的处理耗时，**不等于响应体传输完毕或 `yield` 依赖清理后的耗时**；Nginx 的总耗时另作对照。如果将来增加流式输出，再评估是否需要底层 ASGI middleware。FastAPI 这层基于 Starlette 的 `BaseHTTPMiddleware`，存在 `ContextVar` 从路由向外回传的限制；ID 由 middleware 先设置并向下传递，外层读取统一用 `request.state`，同时用测试核对当前线程池链路。参考：[FastAPI Middleware 官方教程](https://fastapi.tiangolo.com/tutorial/middleware/)、[FastAPI 异常处理](https://fastapi.tiangolo.com/tutorial/handling-errors/)、[Starlette Middleware 限制](https://www.starlette.io/middleware/#limitations)。

## 目标日志与 ID 契约

每次请求先输出一条 `http_request_started`（ID、方法），结束时输出一条结构化完成日志，至少包含 `event=http_request_completed`、`request_id`、`method`、匹配到的路由模板（未匹配时固定写 `unmatched`）、`status_code`、`duration_ms`、`outcome`。开始日志便于定位尚未返回的长请求。异常时另记异常类型；堆栈只在服务端异常日志中出现，不回传用户。不要把完整异常文本直接用于公共访问日志，因为其中可能带业务内容。422 的字段路径可由现有校验异常处理器附带 ID 记录，具体字段值仍由参数模型和 Agent 工具日志按各自规则处理。

1. Nginx 到 API：优先使用代理覆盖后的 `X-Request-ID`；本地直连、测试或缺失时由 API 生成 ID。输入 ID 只接受长度不超过 64 的安全字符（字母、数字、`-`、`_`、`.`）；非法 ID 用新 ID 替代，避免日志换行和无限长字段。
2. FastAPI 到调用链：ID 放进 `request.state`，并复用现有 `ContextVar` 传入 Agent/线程池执行路径；请求结束后复位，不能串到下一次请求。将现有 ID 上下文定义移到通用核心模块，Agent 观察器引用同一个上下文，不保留两套 ID。
3. API 到 Android：所有响应都返回 `X-Request-ID`，包括 200、401、404、422、Agent 502/504 和未捕获异常的 500。未捕获异常要由全局 500 处理器从 `request.state` 取 ID，middleware 记录后仍向外抛异常，不吞错。验证断开/取消时能记录已知状态，不能误记为正常完成。
4. `AgentChatResponse.request_id` 在正常实时运行时与响应头一致。已有去重命中会返回第一次处理的消息体，因此其中的 `request_id` 可能是原始处理 ID；**本次 HTTP 调试以响应头为准**。此计划不改变消息去重协议。
5. FastAPI 处理耗时从进入 middleware 到 `call_next` 返回并构造响应前计算；Agent 阶段耗时继续由 Agent 自己统计。它不包含响应体完整传输，不能直接等同于 Nginx `$request_time`。

先用测试确认 middleware 设置的 `ContextVar` 在当前 `run_in_threadpool` 路径可见，再改 Agent 路由，避免日志 ID 断链。不新增日志平台、追踪服务或配置开关。

## 实施顺序与每步验收

### 1. 固定当前契约

补 FastAPI 测试：已授权聊天、未授权聊天、请求体验证失败、未知路由、现有 Agent 502/504。记录当前响应体和状态码，尤其 422 的 `error.details`、聊天消息去重返回。验收：用例在修改前通过；新增的全局 ID/日志断言在修改前失败。

### 2. 全局请求 ID 与总耗时

在 `create_app()` 中用 `@application.middleware("http")` 加入唯一的 FastAPI HTTP middleware 和通用请求上下文，所有响应写 `X-Request-ID`；开始与完成日志各一条、结构固定。验收：200/401/404/422/502/504/500 都有 ID；同一请求仅一条开始日志和一条完成日志；非法或过长的入站 ID 被替换；并发请求 ID 不串线；线程池读取到当前 ID；响应结束后上下文清除。用 `raise_server_exceptions=False` 测 500。

### 3. 整合 Agent 与错误处理

Agent 路由读取全局 ID，删掉局部生成 ID 和重复 HTTP 总耗时日志，保留 Agent 阶段、工具、LLM 细节及其失败分类；现有 404/422 结构不变。统一 500 处理器返回固定错误信息及请求 ID，不泄露堆栈。验收：同一 ID 出现在 HTTP 完成日志、Agent 阶段日志、LLM/高德日志及响应头；认证、参数和业务错误仍保持原状态码及字段；消息去重行为不变。

### 4. 网关接线与部署

在 `server/nginx/footmarks.conf` 的 access log 增加 `$request_time`、`$upstream_response_time` 和 `$upstream_status`；审视当前 `$request` 日志项，改用不含查询串的 method/path 字段以免 URL 参数进入访问日志。先运行 `nginx -t`，再热重载；部署 API 时保留服务器 `.env`、数据库与图片数据。

验收：从手机或模拟 Android 请求中取 `X-Request-ID`，同一 ID 可查到 Nginx、API 完成日志、Agent 阶段和工具调用；分别对比 Nginx 总耗时、上游耗时、API 总耗时和慢阶段。跑全量 `server/tests` 回归，并验证 HTTPS 健康接口和一条真实聊天。无需数据库迁移。

## 验收时重点回答的问题

- 401/422 是在进入 Agent 前失败，还是 Agent 内部失败？日志能以状态码与阶段缺席区分。
- 504 是 API 自己的总预算触发、LLM 阶段超时，还是 Nginx 等待上游超时？结合三层耗时和最后一个 Agent 事件定位。
- 一次重试是否生成了新的 HTTP ID？是；若命中消息去重，响应体可引用原始执行 ID。
- 批量并发、长时间规划、异常和断开连接时，是否出现缺失完成日志、错误状态或 ID 串线？这些都列为发布前阻断项。
