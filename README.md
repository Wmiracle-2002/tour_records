# 足迹（Footmarks）

个人旅行记录 Android App。支持纯本地 Demo，也可在个人中心登录本地 FastAPI 服务端同步文字旅行记录。

## 当前状态

- Android `versionName`：`1.0.0`
- 当前工作分支：`develop`
- 当前开发里程碑：阶段 11～15、Agent Phase 1～15 和接入 API Task 1～9 已合并；文字记录与云端照片同步代码已完成，真实 COS 和手机真机业务回归待验收
- 构建环境：JDK 17、Android SDK 34、Gradle 8.4
- 最低系统：Android 7.0（API 24）

## 已实现

- 底部导航：记录、智能规划、个人中心
- 旅行时间线：按旅行开始日期倒序展示 Trip 卡片及内部景点、美食记录
- 添加流程：新建旅行时录入城市和起止日期，旅行卡片内的 `+` 可继续添加子记录
- 记录页统计：实时显示去过的城市数和出行次数
- 记录 CRUD：添加、列表查询、详情查询、编辑、删除确认
- 记录列表显示真实城市名称
- 输入校验：名称、备注、人民币花费范围和最多 9 张照片
- 记录字段：城市、类型、名称、日期、评分、人民币花费、备注、照片路径
- 地区选择：离线内置 2023 年 3429 条省/市/区县数据，支持省份筛选、中文名称全局搜索和层级路径展示
- 本地存储：Room 3，采用 `City → Trip → Record` 三层关系；云端记录另保存服务端 ID
- Trip 数据层：旅行起止日期、子记录日期范围校验、DAO/Repository CRUD 和级联删除
- 数据库升级：Room 1 → 2 → 3 迁移保留旧旅行、子记录和照片路径，旧记录的服务端 ID 为空
- 自动化验证：服务端全量回归、8 个 Android JVM 测试与 API 34 模拟器 34 个仪器测试通过
- 权限：仅增加 `INTERNET`；Photo Picker 无需相册、存储或相机权限，Debug 版本允许本机 HTTP
- 图片选择与展示：系统照片选择器、1080px 长边与 JPEG 质量 80 压缩、App 内部存储、Coil 预览
- 图片生命周期：最多 9 张；编辑时清理移除的副本，删除记录时清理全部内部照片
- 云端照片：服务端通过 COS 保存原图，支持上传、查询、编辑时删除和删除记录时联动清理
- 智能规划：欢迎消息、消息展示区、可保留草稿的多行输入框，已接入受认证的 Agent API；发送后立即清空已发送内容，请求期间新输入的草稿不会被上一条成功或失败响应覆盖；聊天消息支持长按选择复制，并区分显示 502/503/504 服务错误
- 个人中心：本地用户说明、城市数、出行次数、人民币总花费和应用版本
- 可选本机服务端模式：共享账号登录、Access Token 过期刷新、文字旅行记录增删改查、手动刷新远端变更；Room 缓存用于浏览，云端写入先成功后更新缓存
- 会话凭据保存在 App 私有偏好设置中，并从系统云备份及设备迁移中排除；原有本地旅行数据仍按应用备份设置处理

## 当前限制

- 服务端 Agent 已完成 Phase 1～15，并已部署受认证的 HTTPS Agent API；Android 智能规划页已接入该接口。服务器真实 LLM 冒烟、天气/历史/POI/预算/路线/三日行程六类场景均已通过；手机 P0 请求链路和 P1 五类基础问答均已完成实测。真实 COS 凭据验证仍待完善。
- 登录云端前要求本机没有未同步的旧旅行，以免把两套数据混在同一时间线；旧本地数据不会被自动上传或删除。云端模式支持新增、编辑和删除照片，但需要服务端 `.env` 配置 COS SecretId、SecretKey。
- 服务端不可用时可以浏览已缓存的云端记录；云端模式的新增、编辑、删除和刷新会报错，不自动改为本地写入。两台真实设备和 API 24 网络回归尚待补测。
- 最低版本配置为 API 24；本机只有 API 34 镜像，API 24 设备回归需在镜像可下载后补跑。

## 项目结构

```text
app/src/main/java/com/miracle/footmarks/
├── data/
│   ├── local/
│   │   ├── dao/             # CityDao、TripDao、RecordDao
│   │   ├── entity/          # CityEntity、TripEntity、RecordEntity
│   │   ├── util/            # PhotoManager
│   │   ├── Converters.kt
│   │   └── FootmarksDatabase.kt
│   ├── remote/              # Retrofit API、Token 会话
│   └── repository/          # 本地 Repository、云端缓存与协调层
├── di/                      # Hilt 数据库模块
├── ui/
│   ├── navigation/          # 底部导航与页面路由
│   ├── screen/
│   │   ├── records/         # 记录列表
│   │   ├── addrecord/       # 添加记录和城市选择
│   │   ├── recorddetail/    # 记录详情与删除
│   │   ├── editrecord/      # 编辑记录
│   │   ├── smartplanning/   # 智能规划对话框架
│   │   └── profile/         # 本地用户与旅行统计
│   └── theme/
├── MainActivity.kt
└── FootmarksApplication.kt
```

## 数据模型

当前 Room 数据库版本为 3，包含三张表：

```text
CityEntity 1 ─── * TripEntity 1 ─── * RecordEntity
```

`TripEntity` 通过 `cityId` 关联城市并保存旅行起止日期；`RecordEntity` 通过 `tripId` 关联旅行，包含 `ATTRACTION`/`FOOD` 类型、名称、实际游览日期、可选评分、可选花费、备注和逗号分隔的内部照片路径。删除记录时 Repository 会清理对应照片。

服务端采用 `User → Trip → Record → RecordImage`，照片表只预留元数据；文字记录在服务端 SQLite 保存。Android 的 `serverId` 只映射来自服务端的旅行与子记录，旧本地行保持为空。

## 构建与安装

Android Studio 不是必需的，可以使用 VSCode 和命令行工具开发。必须安装 JDK 17 和 Android SDK。

```powershell
# 构建 Debug APK（模拟器默认访问宿主机 10.0.2.2:8000）
.\gradlew.bat assembleDebug

# 真机调试可指定可达的 HTTPS 地址
.\gradlew.bat assembleDebug -PfootmarksApiBaseUrl=https://your-server.example/

# 安装到已连接设备
adb install -r app\build\outputs\apk\debug\app-debug.apk

# 启动应用
adb shell am start -n com.miracle.footmarks/.MainActivity
```

Debug APK 输出到 `app/build/outputs/apk/debug/app-debug.apk`。

## 服务端开发（阶段 11～13）

需要 Python 3.12。在 `server` 目录执行：

```powershell
py -3.12 -m pip install -r requirements-dev.txt
$env:FOOTMARKS_TOKEN_SECRET = Read-Host 'Token Secret（至少32字符）'
py -3.12 -m alembic upgrade head
$env:FOOTMARKS_INITIAL_PASSWORD = Read-Host '初始密码（至少12字符）'
py -3.12 -m app.bootstrap
Remove-Item Env:FOOTMARKS_INITIAL_PASSWORD
py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览 `http://127.0.0.1:8000/api/v1/health` 应得到 `{"status":"ok","service":"footmarks-api"}`。另一个终端在 `server` 目录运行 `py -3.12 -m pytest -q` 回归。也可以使用固定的开发测试容器：首次在仓库根目录执行 `docker compose -f server/compose.dev.yaml up -d --build agent-test`，之后执行 `docker compose -f server/compose.dev.yaml exec agent-test pytest -q`。源码通过目录挂载到容器，代码修改后直接重新执行测试即可；只有 `requirements.txt` 或 `requirements-dev.txt` 变化时才需要重新构建。共享账号默认用户名为 `shared`，初始化仅允许一次。Token Secret 需至少 32 字符，必须妥善保管；上面的交互输入不会将密码写入命令历史。

Docker 开发模式在 `server/.env` 配置 `FOOTMARKS_TOKEN_SECRET`，然后在仓库根目录执行 `docker compose --env-file server/.env -f server/compose.yaml up --build`。另开终端输入 `$env:FOOTMARKS_INITIAL_PASSWORD = Read-Host '初始密码'`，再执行 `docker compose --env-file server/.env -f server/compose.yaml exec -e FOOTMARKS_INITIAL_PASSWORD api python -m app.bootstrap`，完成后清除该环境变量。账号只初始化一次。容器仅绑定本机 127.0.0.1，数据持久化于 `server/data`。不要把密码或密钥提交到仓库，环境变量示例见 `server/.env.example`。

高德能力由后端通过 Web 服务 API 调用，不使用 Android SDK。申请高德 Web 服务 API Key 后，编辑服务器上的 `server/.env`，填入 `FOOTMARKS_AMAP_WEB_KEY=你的Key`，然后重新构建或重启服务端容器。Key 只保存在服务器环境变量中，不要写入代码、APK 或提交到 Git。天气接口使用城市 `adcode`，POI、地理编码、距离和路线查询也由后端适配器统一调用。

真实 Agent 还需要在服务器 `server/.env` 配置 `FOOTMARKS_LLM_BASE_URL`、`FOOTMARKS_LLM_API_KEY`、`FOOTMARKS_LLM_MODEL`、`FOOTMARKS_LLM_TIMEOUT_SECONDS` 和 `FOOTMARKS_LLM_MAX_RETRIES`。`FOOTMARKS_LLM_BASE_URL` 必须是供应商提供的 OpenAI 兼容接口地址，并包含 `http://` 或 `https://` 协议；修改后需要重建或重启 API 容器。不要把这些值写入代码、APK 或提交到 Git。

Agent 同步请求还受两个预算控制：`FOOTMARKS_AGENT_TOTAL_TIMEOUT_SECONDS` 默认 120 秒，限制整条请求；`FOOTMARKS_AGENT_STAGE_TIMEOUT_SECONDS` 默认 60 秒，限制 Requirement Analyzer、ReAct Decision、Itinerary Generator 和 Reviser 各自累计耗时。阶段预算会覆盖当前 LLM HTTP 请求的读取超时，预算耗尽后 API 返回 HTTP 504。需要调整时只修改服务器 `server/.env`，不要删除其他已有配置。

请求链路的时间约定为：Agent 默认 120 秒总预算，Nginx 和 Android 默认 150 秒；LLM 单次请求使用阶段剩余预算，客户端断开会触发服务端取消后续阶段。AMap 超时属于可降级 Tool 错误，日志错误码为 `amap_timeout`，能继续回答的请求保持 HTTP 200；LLM 或 Agent 预算超时返回 504，LLM 上游错误返回 502，LLM 未配置返回 503。

业务 API 提供 `POST/GET /api/v1/trips`、`GET/PATCH/DELETE /api/v1/trips/{id}`、`POST /api/v1/trips/{id}/records`、`GET/PATCH/DELETE /api/v1/records/{id}` 和 `GET /api/v1/stats`。`POST /api/v1/auth/login` 接收用户名与密码，返回 Access Token/Refresh Token；`POST /api/v1/auth/refresh` 接收 `refresh_token`，`GET /api/v1/auth/me` 查询当前用户。业务请求带 `Authorization: Bearer <access_token>`。日期使用 ISO `YYYY-MM-DD`，金额为人民币元。

模拟器先启动服务端，再安装 Debug APK，在“个人中心 → 共享账号”输入用户名和密码，点“登录并同步”。切回记录页查看云端旅行；其他设备改动后，在个人中心点“刷新共享记录”。真机需要能访问服务端的地址，建议使用 HTTPS；默认 `10.0.2.2` 只适用于 Android 模拟器。Release 默认指向不可用占位地址，需要构建时指定 HTTPS。服务端模式的本机缓存保存文字记录和远端图片元数据，原图由 COS 保存。

## 快速回归

1. 在“记录”页点击右下角 `+`，选择城市、旅行起止日期并填写第一条景点记录。
2. 确认页面显示 1 个城市、1 次出行，且记录位于对应旅行卡片中。
3. 点击旅行卡片内的 `+` 添加第二条景点或美食记录。
4. 在详情页编辑名称、评分或花费，保存后确认变化。
5. 选择照片后保存，重启 App 确认仍能显示；编辑移除照片后确认预览消失。
6. 在详情页删除记录，确认列表中不再显示。
7. 关闭并重新启动 App，确认未删除的记录仍存在。

完整步骤和已知限制见 [测试指南.md](./测试指南.md)。

## 文档导航

- [需求分析.md](./需求分析.md)：产品目标、已确认决策和当前实现差距
- [客户端开发计划.md](./客户端开发计划.md)：Android 本地阶段任务与回归
- [服务端开发计划.md](./服务端开发计划.md)：服务端阶段任务与回归
- [开发日志.md](./开发日志.md)：按日期记录已完成工作和验证结果
- [测试指南.md](./测试指南.md)：构建、安装和 CRUD 手工回归步骤
- [CRUD功能完成总结.md](./CRUD功能完成总结.md)：本次 CRUD 里程碑范围
- [城市数据源.md](./城市数据源.md)：2023 年行政区划来源、条目数量、转换规则和许可证

## Agent 开发进度

Agent Phase 1～15 的 State、Requirement Analyzer、Tool Layer、ReAct Collector、基础 Workflow、Itinerary Generator、Validator、Local Reviser、最终响应生成器、LangGraph 主流程、异常边界测试、端到端场景测试、结构化可观测性和最终代码检查已经完成。Graph 已接入普通请求和行程规划的条件分支，以及 Validator/Reviser 回路。

Phase 13 已完成 10 个可控端到端场景，Phase 14 增加结构化事件日志，Phase 15 完成架构、可靠性、反幻觉和用户输出检查；服务端全量回归 211 项通过。接入 API Task 1～9 的服务端实现、HTTPS 部署和六类真实 LLM 场景已完成。

Agent 稳定性 P0 已完成：FastAPI、Nginx、Runtime、LangGraph、LLM 和 Tool 日志现在可以用同一个 `request_id` 关联；阶段事件包含开始、结束、耗时和状态，覆盖需求分析、ReAct、Tool/归一化、行程生成、校验、修订和最终回答。API 会通过 `X-Request-ID` 返回本次请求标识，服务器可用它对照 Nginx access log 与 API 容器日志。P0 Agent 回归为 204/204，服务端全量回归 229/229；服务器代码和 Nginx 配置已部署，公网健康检查通过，手机历史查询和 Token 刷新链路实测通过。下一步按 P1 验收五类基础问答。

Agent 稳定性 P1 已完成五类基础问答真机验收。P2-1 至 P2-5 已完成：ReAct 默认最多执行 4 轮，已进入终态的信息 Tool 不再暴露给下一轮决策；Agent 具备总预算、阶段预算和客户端断开后的协作式停止；P2 定向服务端回归 75/75、Android 单元测试 31/31 通过。提交 `0f7e72b` 已部署，公网健康检查通过，下一步进行真机回归。

P2 真机回归后的修复已完成并部署：天气需求保留“中秋”等原始日期表达，并结合服务器当前日期解析公历日期；天气预报按目标日期选择，不再默认展示第一天。行程规划在 POI 等关键信息完成、仅距离等可选信息不可用时仍会进入 Itinerary Generator。Android 会保留上一条请求期间输入的新草稿，并减少智能规划、个人中心和输入法区域重复消费的系统留白。服务端提交 `c219a98` 已部署，公网健康检查通过。

Agent 参数排查日志已加入本地代码：`tool_started` 记录 LLM 原始工具参数，`tool_completed` 记录实际执行参数；高德请求日志记录接口路径、完整业务参数和返回的 `status`、`infocode`、`info`，通过同一个 `request_id` 串联。高德 API Key 不写入日志。部署此版本后，可在服务器运行 `sudo docker compose logs -f --tail=100 api`，按请求 ID 查看 `tool_started`、`tool_completed`、`amap_request`、`amap_response` 事件。

Agent 最小化改进方案 A 步已在本地完成：需求模型新增独立的距离意图与测距方式；行程数据模型可表达“第 N 天＋上午/下午/晚上或三餐”，同时暂时兼容旧的 HH:MM 字段；路线导航查询不再触发高德路线工具，而是返回不提供导航的提示。粗粒度行程的生成与展示、实际测距和天气改造属于后续步骤，当前版本尚未部署。A 步 Agent 回归 257/257、服务端全量回归 282/282 通过。

Agent 最小化改进方案 B 步已在本地完成：当前 Agent 的 POI 工具只接受已确认城市、用途（景点/餐饮/指定地点）与必要的地点名；服务端固定 `citylimit=true`、`page=1`、`offset=10`、`extensions=base`，并过滤错城、错类、无效坐标和重复 POI。城市名用服务端自带的 2023 行政区名称索引预检，包括县级市；该索引不作为高德 adcode 来源。运行时不再向 Agent 暴露周边搜索或 POI 详情。此版本尚未部署；B 步服务端全量回归 300/300 通过。

Agent 最小化改进方案 C 步已在本地完成：距离问答先在指定城市分别取得唯一的起终点 POI，再向高德测距接口发送已校验坐标；默认回答直线距离，明确要求驾车/短距离步行时才使用对应模式。天气问答先用高德行政区接口核对城市或区县的 adcode，再调用实况或预报接口，按返回的实际日期选取预报。服务端自行换算“今天、今晚、明天、后天、从现在到明天”，并拦截把未来日期误判为实时天气的结果；缺失、歧义、预报范围外或高德响应异常时明确说明，避免用当天实况代替目标日期。当前农历节日仍依赖需求分析结果给出公历日期，无法确定时会要求提供具体日期。本步尚未部署，已用模拟 Android 消息和高德响应做回归；服务端全量测试 335/335 通过，真实高德与真机效果待联调。

Agent 最小化改进方案 D 步已在本地完成：行程改为按“第 N 天”或已知公历日期展示，每天列出早餐、上午、午餐、下午、晚餐、晚上六个时段；没有可靠候选的时段明确留空。生成器只接受已收集 POI 的 ID/名称，生成器与校验器都会核对景点与餐饮类别及同日重复，生成器还检查日期连续性；粗粒度行程不生成精确时刻或导航路线。预算问答直接使用本地人民币粗估，规划有明确天数时也预先计算预算；已声明的信息收集齐后直接进入行程生成，减少 ReAct 决策。估算超出预算上限时给出说明。行程 LLM 超时或格式不合格时，服务端可用已验证候选生成稀疏行程，避开要求排除的历史地点。服务端全量回归 356/356 通过；当前版本尚未部署，实际 POI 质量及手机展示待联调。

Agent 最小化改进方案 E 步已完成：使用 FastAPI 测试客户端发送与 Android 相同格式的认证聊天请求，覆盖历史、地点推荐、距离、天气、预算和一日规划，并检查回答、请求 ID、阶段耗时及高德请求参数；另覆盖无历史、无 POI、无目标日期预报、缺少预算天数和无规划候选时不编造事实。规划会分别获取景点和餐饮候选。真实高德 Web API 联调确认南京行政区编码为 `320100`，景点和餐饮搜索分别接受 9、10 个有效 POI，“中山陵”可唯一匹配“中山陵景区”，到夫子庙的直线测距为 7248 米，天气返回 4 天预报。为适配真实 `extensions=base` 响应，POI 缺少 `adcode` 时改用精确城市名核对；无有效城市名仍拒绝。

2026-09-26 针对真机日志修复了两项问题并部署服务端：推荐美食时按用户消息硬校验推荐类别，由后端固定查询餐饮 POI，不再让第二次 LLM 调用生成景点关键词；“中山陵到夫子庙有多远”即使被模型误标为路线意图，也改走两端 POI 搜索和 `/v3/distance`，不再调用 `/v3/geocode/geo`。服务器原有 `.env` 未覆盖，仅更新 `FOOTMARKS_LLM_MODEL`；本地全量回归 373 项通过。容器内假 LLM/假高德冒烟测试和公网健康接口通过，真实新模型与 Android 真机回答仍待验收。

同日修复“南京现在天气怎么样”被要求填写日期的问题：需求分析会把单独询问“现在/当前/此刻/目前/实时”的消息硬校正为实时天气，并清除模型误填的起止日期；实况直接使用高德 `extensions=base`，无需将“现在”换算成日期。“今天全天/明天/从现在到明天”仍按预报处理。服务端已部署，本地全量回归 379 项通过，服务器容器内用假 LLM/假高德验证了现在走 `base`、明天走 `all`；真实模型和手机回复尚待复测。

同日修复一日游回答中三餐全为空、费用明细显示英文的问题：当模型遗漏午餐或晚餐时，服务端从已验证的餐饮候选补齐；没有可确认的早餐推荐时仍留空。预算明细使用中文，门票未估算时明确写“景点门票未计入”。本地服务端全量回归 391 项通过，服务器容器冒烟测试及公网 HTTPS 健康接口通过；真实模型与手机显示仍待复测。

Agent 剩余稳定性项目的本轮验证见 [Agent稳定性测试报告.md](Agent稳定性测试报告.md)：认证 API 模拟问答和二日/三日的四组规划用例通过，服务端全量回归 395 项通过；真实模型批量验收与手机弱网场景仍待完成。智能规划中本人消息气泡的右下角已改为与其他三个角相同的圆角。可安装本轮 Debug APK `app/build/outputs/apk/debug/app-debug.apk` 检查外观；该包使用正式 HTTPS API 地址。

新增旅行的城市选择器现只展示地级目的地、四个直辖市及没有地级上级的省直管县级市，共 358 个选项；区县名称仍可用于搜索上级城市，例如输入“昆山”会显示“苏州市”。已有区县记录不迁移，Agent 的天气/地点查询也不受旅行选择器粒度影响。短期会话与长期偏好记忆的开发方案见 [Agent记忆系统方案.md](Agent记忆系统方案.md)。
记忆系统 v1 产品规则已确认：按账号保存完整对话列表，支持新建、打开和删除；每轮只使用当前会话最近 8 轮作上下文。长期偏好只在明确要求记住时写入，独立于聊天删除；自动提取候选留待后续阶段。当前尚未实现记忆功能。

## 下一步

1. 新模型额度可用后，用真实 LLM 和 Android 手机复测五类问答与一日、三日规划；重点记录响应时间、候选质量和失败时的 request_id。
2. 在真实手机上安装最新 HTTPS APK，检查输入法上方输入框位置、等待回复期间的新草稿保留，以及智能规划和个人中心标题位置。
3. 下载条件恢复后补跑 API 24 最低版本回归。
4. 补充大量记录的页面滚动压力测试。
5. 在第二台真实设备和 API 24 上补跑文字记录同步、弱网/断网与大量数据回归。

## 许可证

待定。
