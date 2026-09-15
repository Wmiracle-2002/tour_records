# 足迹（Footmarks）

个人旅行记录 Android App。当前为本地 Demo，已经实现景点/美食记录的创建、列表查看、详情查看、编辑和删除。

## 当前状态

- Android `versionName`：`1.0.0`
- 开发分支：`feat/demo`
- 当前开发里程碑：阶段 1～9，Demo 所有无需后端的产品功能
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
- 本地存储：Room 2，采用 `City → Trip → Record` 三层关系
- Trip 数据层：旅行起止日期、子记录日期范围校验、DAO/Repository CRUD 和级联删除
- 数据库升级：Room 1 → 2 迁移会把每条旧记录保留为一条单日旅行
- 自动化验证：4 个 JVM 校验测试及 API 34 模拟器上的 22 个仪器测试通过
- 图片选择与展示：系统照片选择器、1080px 长边与 JPEG 质量 80 压缩、App 内部存储、Coil 预览
- 图片生命周期：最多 9 张；编辑时清理移除的副本，删除记录时清理全部内部照片
- 智能规划框架：欢迎消息、消息展示区、可保留草稿的多行输入框，以及发送时的“暂未开放，待完善”提示
- 个人中心：本地用户说明、城市数、出行次数、人民币总花费和应用版本

## 当前限制

- 智能规划尚未连接服务端 Agent；登录、跨设备同步和服务端照片存储等待后端阶段。

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
│   └── repository/          # 行政区划、City、Trip、Record Repository
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

当前 Room 数据库版本为 2，包含三张表：

```text
CityEntity 1 ─── * TripEntity 1 ─── * RecordEntity
```

`TripEntity` 通过 `cityId` 关联城市并保存旅行起止日期；`RecordEntity` 通过 `tripId` 关联旅行，包含 `ATTRACTION`/`FOOD` 类型、名称、实际游览日期、可选评分、可选花费、备注和逗号分隔的内部照片路径。删除记录时 Repository 会清理对应照片。

## 构建与安装

Android Studio 不是必需的，可以使用 VSCode 和命令行工具开发。必须安装 JDK 17 和 Android SDK。

```powershell
# 构建 Debug APK
.\gradlew.bat assembleDebug

# 安装到已连接设备
adb install -r app\build\outputs\apk\debug\app-debug.apk

# 启动应用
adb shell am start -n com.miracle.footmarks/.MainActivity
```

Debug APK 输出到 `app/build/outputs/apk/debug/app-debug.apk`。

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
- [开发计划.md](./开发计划.md)：分阶段任务、状态和每阶段验证方式
- [开发日志.md](./开发日志.md)：按日期记录已完成工作和验证结果
- [测试指南.md](./测试指南.md)：构建、安装和 CRUD 手工回归步骤
- [CRUD功能完成总结.md](./CRUD功能完成总结.md)：本次 CRUD 里程碑范围
- [城市数据源.md](./城市数据源.md)：2023 年行政区划来源、条目数量、转换规则和许可证

## 下一步

1. 执行 API 24 与 API 34 发布前回归并收口文档。
2. 本地功能验收后准备服务端架构。

## 许可证

待定。
