# 足迹（Footmarks）

> 一个简洁优雅的个人旅行记录 Android App

---

## 项目简介

足迹（Footmarks）是一款专为旅行爱好者设计的记录工具，帮助你记录每一次旅行的美好时光。

**当前版本**：0.1.0-dev（开发中）

**开发阶段**：阶段 0 - 项目初始化 ⏳

---

## 核心功能（规划）

### ✅ 已完成
- 无（项目刚启动）

### 🚧 开发中
- [ ] 项目初始化与依赖配置

### 📋 计划中
- [ ] 城市旅行记录管理
- [ ] 景点与美食记录
- [ ] 照片上传与压缩存储
- [ ] 足迹地图展示
- [ ] 时间线浏览
- [ ] 智能旅行规划（AI Agent，远期）

---

## 技术栈

### Android 端
- **语言**：Kotlin
- **UI 框架**：Jetpack Compose + Material 3
- **架构模式**：MVVM（ViewModel + StateFlow）
- **本地存储**：Room（SQLite ORM）
- **图片加载**：Coil
- **图片压缩**：Android BitmapFactory
- **路由导航**：Navigation Compose
- **照片选择**：Photo Picker（Android 13+）

### 后端（远期规划）
- **框架**：FastAPI（Python）
- **数据库**：PostgreSQL
- **AI Agent**：LangGraph / 工作流型框架
- **LLM**：Claude API（或国产模型）

---

## 开发环境要求

- **Android Studio**：Hedgehog (2023.1.1) 或更高版本
- **JDK**：17 或更高版本
- **Android SDK**：
  - Minimum SDK: 24 (Android 7.0)
  - Target SDK: 34 (Android 14)
  - Compile SDK: 34
- **Kotlin**：1.9.0+
- **Gradle**：8.0+

---

## 项目结构（规划）

```
app/
├── src/main/
│   ├── java/com/miracle/footmarks/
│   │   ├── data/              # 数据层
│   │   │   ├── entity/        # Room Entity
│   │   │   ├── dao/           # Room DAO
│   │   │   ├── repository/    # Repository 接口与实现
│   │   │   └── database/      # AppDatabase
│   │   ├── ui/                # UI 层
│   │   │   ├── screen/        # 各页面 Composable
│   │   │   ├── viewmodel/     # ViewModel
│   │   │   ├── component/     # 可复用组件
│   │   │   └── theme/         # Material 3 主题
│   │   ├── navigation/        # 路由导航
│   │   ├── utils/             # 工具类
│   │   └── App.kt             # Application 类
│   ├── assets/
│   │   └── cities.json        # 城市数据
│   └── res/                   # 资源文件
└── build.gradle.kts
```

---

## 数据模型

采用两层嵌套模型：

```
City（城市）
  └─ Trip（旅行记录）
      └─ Record（子记录：景点/美食）
```

### 数据库表结构

#### City（城市表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Long | 主键 |
| provinceCode | String | 省级行政区划代码 |
| cityCode | String | 市级行政区划代码 |
| cityName | String | 城市名称 |
| createdAt | Long | 创建时间戳 |

#### Trip（旅行记录表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Long | 主键 |
| cityId | Long | 外键 → City.id |
| startDate | Long | 开始日期时间戳 |
| endDate | Long | 结束日期时间戳 |
| createdAt | Long | 创建时间戳 |

#### Record（子记录表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Long | 主键 |
| tripId | Long | 外键 → Trip.id |
| name | String | 景点/美食名称 |
| type | Enum | SPOT（景点）/ FOOD（美食） |
| date | Long | 具体日期时间戳 |
| rating | Int? | 评分 1-5 星（可选） |
| cost | Float? | 花费人民币（可选） |
| note | String? | 备注 |
| photos | String | 照片路径 JSON 数组 |
| createdAt | Long | 创建时间戳 |

---

## 安装与运行

### 克隆项目
```bash
git clone <repository-url>
cd tour_records
```

### 使用 Android Studio
1. 打开 Android Studio
2. 选择 `File` → `Open`
3. 选择项目根目录
4. 等待 Gradle 同步完成
5. 连接 Android 设备或启动模拟器
6. 点击运行按钮（▶️）

### 命令行构建
```bash
./gradlew assembleDebug
```

---

## 开发进度

详见 [开发计划.md](./开发计划.md)

**当前阶段**：阶段 0 - 项目初始化

**完成度**：0/16 阶段

---

## 城市数据源

- **来源**：国家统计局 2023 年县及县以上行政区划代码
- **数据量**：约 3000+ 城市（含地级市、县级市、自治州）
- **更新频率**：按需更新（行政区划变更较少）

---

## 照片存储规则

- **压缩参数**：长边约 1080px，JPEG 质量 80
- **存储位置**：App internal storage（`photos/{tripId}/{recordId}/{timestamp}.jpg`）
- **数量限制**：每条记录最多 9 张
- **删除规则**：删除记录时同步删除对应照片文件

---

## 路线图

### Demo 版本（v0.1.0）
- [x] 项目初始化
- [ ] 本地数据存储（Room）
- [ ] 城市记录管理
- [ ] 景点与美食记录
- [ ] 照片功能
- [ ] 足迹与时间线视图
- [ ] 智能规划占位界面

### v0.2.0（计划）
- [ ] UI 优化与动画
- [ ] 搜索功能
- [ ] 数据导出

### v1.0.0（远期）
- [ ] 用户认证
- [ ] 服务端同步
- [ ] AI 旅行规划
- [ ] 多设备同步

---

## 许可证

待定

---

## 联系方式

开发者：Miracle

---

## 更新日志

### [0.1.0-dev] - 2026-09-14
- 项目启动
- 完成需求分析
- 制定开发计划
