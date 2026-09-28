# 足迹（Footmarks）

足迹是个人旅行记录与智能规划 App。Android 端可离线记录旅行；登录共享账号后，FastAPI 服务端保存旅行、照片元数据、Agent 会话和偏好。Agent 可回答旅行历史、地点、美食、天气、距离、预算问题，并生成按天与时段安排的行程。

## 当前能力

- **旅行记录**：按城市与日期建立旅行，添加景点/美食子记录，支持增删改查、照片及城市数/出行次数统计。本地使用 Room；登录后由服务端 SQLite 保存文字记录，腾讯云 COS 保存云端原图。
- **智能规划**：LangGraph 编排需求分析、信息收集、行程生成、校验与修订；服务端以严格参数模型调用高德 Web 服务和内部旅行记录工具。回答以已验证的 POI 和实际记录为依据，不提供导航路线。
- **会话记忆**：会话列表、历史消息、结构化当前话题、限额近期上下文、70% 阈值分块摘要、原文与工具结果回查，以及由用户明确要求保存的长期偏好。
- **响应与排查**：保留 JSON 聊天接口；SSE 聊天接口先推送阶段进度，再按段发送最终校验过的回答。请求 ID 贯穿 HTTP 与 Agent 阶段日志。

完整范围、数据流、接口和限制见 [项目功能说明](docs/项目功能说明.md)。个人旅行知识库属于 [Phase 17 计划](docs/Agent开发计划.md)，尚未实现。

## 本地开发

Android Studio 不是必需的。安装 JDK 17、Android SDK 34 后，可用 VSCode 和命令行构建：

```powershell
.\gradlew.bat assembleDebug -PfootmarksApiBaseUrl=https://your-server.example/
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

默认 Debug 地址 `10.0.2.2:8000` 仅供 Android 模拟器访问本机服务端；真机必须在构建时指定手机可访问的 API 地址。服务端使用 Python 3.12 和 SQLite，可在 `server` 目录安装 `requirements-dev.txt`、按 `server/.env.example` 配置环境变量，运行 Alembic 迁移后启动 `uvicorn app.main:app`。Docker 部署配置见 `server/compose.yaml`。不要提交 `.env`、Token 密钥、LLM/高德/COS 凭据。

## 验证状态

2026-09-28：智能计划使用 SSE 展示执行阶段；多日行程的逐日校验与预览已部署，最终完整答案仍经过整份行程校验和修订。短问答由工具直接生成，可能一次显示完整文字。已修复“福州长乐”推荐范围和失败后再次发送闪退，服务器长乐区查询已通过高德实测。真机流式体验、弱网和最低 Android API 24 仍待验收。详细结果见 [开发日志](docs/开发日志.md) 与 [测试指南](docs/测试指南.md)。

Android 客户端收到已校验的行程预览或最终正文后，会在同一条消息中渐进显示文字，形成打字机效果。生成第一天前仍需等待模型和工具；这不是未经校验的模型 token 直接输出。

## 文档

- [项目功能说明](docs/项目功能说明.md)：当前功能、架构、数据与 API、边界
- [简历项目介绍](docs/简历项目介绍.md)：Agent 项目描述和可直接使用的简历条目
- [Agent 架构](docs/Agent架构.md)、[Agent 记忆系统方案](docs/Agent记忆系统方案.md)、[Agent 开发计划](docs/Agent开发计划.md)
- [客户端开发计划](docs/客户端开发计划.md)、[服务端开发计划](docs/服务端开发计划.md)、[开发日志](docs/开发日志.md)
- [测试指南](docs/测试指南.md)、[城市数据源](docs/城市数据源.md)、[文档索引](docs/README.md)

## 许可证

待定。
