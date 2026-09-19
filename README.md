# 足迹（Footmarks）

个人旅行记录 Android App。支持纯本地 Demo，也可在个人中心登录本地 FastAPI 服务端同步文字旅行记录。

## 当前状态

- Android `versionName`：`1.0.0`
- 当前工作分支：`feat/demo`
- 当前开发里程碑：阶段 11～13 已完成，阶段 15 的文字记录同步已实现并通过本机联调；Agent Phase 1～15 和接入 API Task 1～9 的服务端验收已完成，等待手机真机手工验收
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
- 智能规划：欢迎消息、消息展示区、可保留草稿的多行输入框，已接入受认证的 Agent API；发送后立即清空输入框，失败时恢复草稿供重试，并显示加载、成功和失败状态
- 个人中心：本地用户说明、城市数、出行次数、人民币总花费和应用版本
- 可选本机服务端模式：共享账号登录、Access Token 过期刷新、文字旅行记录增删改查、手动刷新远端变更；Room 缓存用于浏览，云端写入先成功后更新缓存
- 会话凭据保存在 App 私有偏好设置中，并从系统云备份及设备迁移中排除；原有本地旅行数据仍按应用备份设置处理

## 当前限制

- 服务端 Agent 已完成 Phase 1～15，并已部署受认证的 HTTPS Agent API；Android 智能规划页已接入该接口。服务器真实 LLM 冒烟、天气/历史/POI/预算/路线/三日行程六类场景均已通过。手机真机手工验收、COS 原图上传与远程图片加载仍待完善。
- 登录云端前要求本机没有未同步的旧旅行，以免把两套数据混在同一时间线；旧本地数据不会被自动上传或删除。云端模式暂不支持新增照片，已有纯本地 Demo 继续支持照片。
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

业务 API 提供 `POST/GET /api/v1/trips`、`GET/PATCH/DELETE /api/v1/trips/{id}`、`POST /api/v1/trips/{id}/records`、`GET/PATCH/DELETE /api/v1/records/{id}` 和 `GET /api/v1/stats`。`POST /api/v1/auth/login` 接收用户名与密码，返回 Access Token/Refresh Token；`POST /api/v1/auth/refresh` 接收 `refresh_token`，`GET /api/v1/auth/me` 查询当前用户。业务请求带 `Authorization: Bearer <access_token>`。日期使用 ISO `YYYY-MM-DD`，金额为人民币元。

模拟器先启动服务端，再安装 Debug APK，在“个人中心 → 共享账号”输入用户名和密码，点“登录并同步”。切回记录页查看云端旅行；其他设备改动后，在个人中心点“刷新共享记录”。真机需要能访问服务端的地址，建议使用 HTTPS；默认 `10.0.2.2` 只适用于 Android 模拟器。Release 默认指向不可用占位地址，需要构建时指定 HTTPS。服务端模式的本机缓存仅用于文字记录，原图能力等待 COS 阶段。

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

## 下一步

1. 在真实手机上安装 HTTPS APK，完成登录、天气请求、三日行程请求、失败重试和重复发送检查。
2. 下载条件恢复后补跑 API 24 最低版本回归。
3. 补充大量记录的页面滚动压力测试。
4. 在第二台真实设备和 API 24 上补跑文字记录同步、弱网/断网与大量数据回归。

## 许可证

待定。
