# Agent 评测样例

方案见 [Agent评测方案](../../docs/Agent评测方案.md)。本目录提供题库、完整性校验、小额试跑、40场景全量运行器及基于证据的规则判分。执行进度见 [全量评测执行记录](../../docs/Agent全量评测执行记录.md)。

从项目根目录执行（无需真实 Key、无需启动服务端）：

```powershell
& .\server\.venv\Scripts\python.exe server/evaluation/validate_cases.py
```

`fixtures.json` 中的账号名是逻辑引用，POI ID、天气、距离是合成标准数据，不要导入生产环境。真实评测时记录工具返回并使用独立轨道，不能把合成值视为线上事实。

`cases.json` 的步骤类型：`message` 为正常用户提问，`new_conversation` 为准备步骤；`setup` 引用账号、偏好、收藏、预置消息和故障配置。`required` 是全部必须满足的条件，`forbidden` 是不得出现的行为。字段 `rule` 指定后续判分器的规则语义；`evidence` 指定应核对的证据。相同规则的 `value` 是该题具体标准。

`results-template.csv` 为 A 轨三次重复的空白结果表，不含伪造成绩。`message` 步骤有一行，准备步骤没有结果行。真实结果另存到被Git忽略的目录，不回填或覆盖这份空白模板。

## 全量运行

在已经配置真实模型的环境中执行。运行器在导入应用前切换独立SQLite及随机认证密钥；只替换高德网络传输，保留业务参数校验、过滤和工具归一化。每场景/重复新建Alice/Bob账号，按setup装载收藏、偏好、26条长会话原文及故障，正常登录后通过回环HTTP发送SSE消息。登录准备使用不同回环源IP模拟独立家庭，不关闭实际限流；登录时间不计入Agent耗时。

```powershell
$env:PYTHONPATH='server;server/evaluation'
& .\server\.venv\Scripts\python.exe -m pytest server/evaluation/test_full.py server/evaluation/test_pilot.py -q -p no:cacheprovider
& .\server\.venv\Scripts\python.exe server/evaluation/run_full.py --offline-check --output .test-run-agent-evaluation/full-offline-unique
& .\server\.venv\Scripts\python.exe server/evaluation/run_full.py --phase trial --output .test-run-agent-evaluation/trial-unique
& .\server\.venv\Scripts\python.exe server/evaluation/run_full.py --phase formal --output .test-run-agent-evaluation/formal-unique
& .\server\.venv\Scripts\python.exe server/evaluation/report_full.py .test-run-agent-evaluation/formal-unique
```

每个输出目录必须不存在。Windows需本机已安装服务端依赖、配置LLM，Linux可在现有容器内设置源码PYTHONPATH后执行。本轮实际评测在服务器进行，以上不是让用户再重复付费运行。

- trial：47条消息；formal：141条正式消息，另有独立H01预热。预热不参与成绩，计入批次账本。顺序按种子20261008固定打乱，单并发，不在中途修改业务代码。
- 批次Token上限分别400,000和1,200,000，覆盖所有临时账号、失败、压缩与重试；每次模型请求预留输入UTF-8字节数+最大输出。余额不足以预留时中止，保留缺测分母，不能新建批次绕过该上限。
- `manifest.json`保存模型、参数、源码/题库/快照/评测程序哈希及运行范围；未提交源码以Git基线加文件哈希识别。
- `results.json`保存每条原始回答、SSE事件、最终Graph状态、解析需求、模型结构化输出、工具参数及完整结果、数据库证据、用量和初判。`usage.json`为全批账本，含预热；`summary.json`为逐步汇总。
- `report_full.py`生成`report-metrics.json`、`review.md`、`review.csv`。人工结论、规划0～2分、可验证事实数及无依据事实数需真实填写。自动通过不是最终正确率；关键词检查只是初筛，语义/禁止行为仍需复核。
- trial判分规则修正可用`--regrade`生成单独`regraded-results.json`，保留原始结果与新判分哈希；正式批次拒绝用此选项更改冻结评分。
- 工具指标按每消息的工具名+kind/place_name/category分组取首次；参数纠错事件表示首次不合法。程序查询与LLM决策分列；在形成工具调用前失败的消息另列，不能以实际发到高德的调用都是合法就声称全链路100%。

该模式是A轨真实模型与固定合成工具数据，耗时不包含公网、Nginx和手机渲染。正式统计未提供缺失值的指标要标记待补证据，不填0或100%。

## 六场景小额试跑

`run_pilot.py` 从当前环境读取真实 LLM 配置，在导入应用前将数据库与认证配置切换到独立目录。只使用预置账号、合成工具数据，不访问真实旅行记录或 COS；启动仅监听回环地址的 HTTP 服务，正常登录后发送 SSE 请求。保留最终回答、结构化需求、工具结果、阶段事件、首段正文/完成耗时及实际或保守用量。每次运行必须使用不存在的新输出目录。

先离线检查，不调用模型：

```powershell
& .\server\.venv\Scripts\python.exe server/evaluation/run_pilot.py --offline-check --output .test-run-agent-evaluation/offline-unique
& .\server\.venv\Scripts\python.exe -m pytest server/evaluation/test_pilot.py -q -p no:cacheprovider
```

真实调用在已配置 LLM 环境中运行，消耗上游额度：

```powershell
& .\server\.venv\Scripts\python.exe server/evaluation/run_pilot.py --output .test-run-agent-evaluation/pilot-unique
```

固定跑 H01、R02、W01、D01、P01、M01，一次共七条消息。独立测试账号账本上限 30,000 token（包含保守计费）；不足以预留下一次调用时可能提前拒绝。首次非 `completed` 响应后停止，保留已完成结果，未经排查不自动重跑。当前输出均标 `needs_review`，不能把七条返回 200 直接算作任务成功率。只在评测环境运行，避免与实际服务竞争资源。耗时是服务器回环 HTTP 的 A 轨结果，不包含 Nginx、公网或手机动画。

可用 `--cases H02 H03` 等参数选择 Alice 的纯消息场景；需要额外预置、切换账号或故障注入的场景会被拒绝，不会伪装成已支持。manifest 同时保存源码文件哈希，区分尚未提交的修复版本。额度预留会覆盖输入估算和最大输出，剩余额度高于零仍可能提前拒绝；补测必须保留原始失败，独立建库并记录累计实际用量。

2026-10-08 明确历史回答口径：H01 只列城市；地点问题按城市列 ATTRACTION，美食问题按城市列 FOOD；明确同时询问两者时分开列出。此次补充改变了题库哈希，初次试跑保留当时的原始题库与 manifest，不能据此倒改旧成绩。

## 零Token分阶段评测

新增 `offline_cases.json`（冻结的人工参考标注）、`offline_evaluation.py`（真实组件离线执行）、`offline_archive.py`（旧LLM日志只读重评分）。说明、命令和限制见 [分阶段结果](../../docs/Agent零Token分阶段评测结果-2026-10-09.md)。实际入口检索与显式类别底层检索分开统计；空gold单独判定，不计作满分Recall。脚本阻断网络和真实LLM方法，输出目录须为新目录。

新增 `region_cases.json` 和 `region_evaluation.py`，按笔记ID与原文起点评测具体区域片段；运行：`python server/evaluation/region_evaluation.py --output .deploy/regions-new`（PYTHONPATH包含server与server/evaluation）。合成地域契约样例不等同于整体Agent准确率。

2026-10-09新增`knowledge_constraints_cases.json`（v3）：保留原`offline_cases.json`，仅按用户确认修订KR11历史攻略的类别不限范围，并从既有类别提供kind。运行`python server/evaluation/offline_evaluation.py --dataset server/evaluation/knowledge_constraints_cases.json --output .deploy/knowledge-constraints-new`。新口径修复前后对照及限制见[硬条件与历史攻略修正](../../docs/知识库硬条件与历史攻略修正-2026-10-09.md)。
