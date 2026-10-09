# Agent 评测指标修订 v2

本文件说明独立评测报告器的口径。报告器不修改业务、模型配置、题库、原判分器、原结果及历史报告，也不调用模型。本轮同时进行的模型切换与业务修复见[修复与模型复评计划](Agent修复与模型复评计划.md)。

## 指标按模块组织

整体以 **Task Success Rate（TSR）/ goal achievement** 为主：最终回答是否完成用户目标，事实是否与业务数据库、工具快照、行程状态、记忆证据相符，并满足禁止条件。需求字段正确、工具参数合法、HTTP/SSE结束均不能单独证明目标成功。对查询任务核对答案与数据；对写入任务核对持久状态；对规划任务同时核对最终展示与行程状态；对追问/拒绝任务核对是否为正确且安全的处理。

| 模块 | 常见指标 | 计算/标注方式及当前状态 |
| --- | --- | --- |
| 需求意图 | Intent Accuracy | 与gold意图相符的消息数/有意图标注的消息数；当前使用显式`requirement_fields.value.intent` |
| 需求槽位 | Slot F1（完整gold后） | 完整标注槽位名和值、等价规则及多余字段，匹配计TP、额外计FP、遗漏计FN，F1=2TP/(2TP+FP+FN)；当前标注不完整，只计算显式槽位Slot Exact Accuracy，F1为N/A |
| 工具使用 | Tool Call Accuracy / F1 | 标注参考工具、参数及允许的等价流程；Accuracy按完整流程匹配，F1按选定等价参考流程一对一匹配调用计TP/FP/FN。当前无参考标注，两项未评测；报告器仅实现Accuracy入口，F1尚未实现 |
| 整体及各业务类别 | Task Success Rate | 成功任务数/预期任务数；按最终答案、业务状态和禁止条件裁决，多步任务全部消息成功才通过，缺测计失败，未复核保留pending及上下界 |
| 规划 | TSR、约束满足率、人工合理性 | 核对城市、日期、时段、类别等标注约束；当前约束满足率按整个`itinerary_constraints`规则包全满足计1（含记忆任务规划），不是逐时段覆盖率；合理性另由人工标注，当前N/A |
| 记忆 | Memory Fact F1、Recall@K | 标注gold事实和答案事实，按事实匹配计TP/FP/FN；检索Recall@K=前K条命中的相关记忆数/全部相关记忆数，需固定K并标注相关性。当前缺标注，均N/A；memory TSR另列 |
| 知识库/RAG | Context Precision / Recall、Faithfulness | 标注排序检索结果相关性、参考答案事实及每条答案事实的上下文支持；分别评估检索排序精度、参考事实覆盖、受支持事实/答案事实。当前缺标注，均N/A；Answer Relevancy也未单独评测 |
| 稳定性 | empirical all-3 / pass^3 | 分别按自动候选、最终成功标签统计三轮全过；n=k=3且成功标签确定时对应pass^3算式，其他限制见下文，不叫pass@k |
| 运行可靠性 | 完整终止率、安全降级率 | 单个终止事件位于最后且final_event/request_id一致才计完整终止；安全降级只统计显式safe_tool_failure任务，自动代理与人工确认分列，额度拒绝不混入 |
| 性能/成本 | P50/P95 Latency、Tokens/task、Calls/task | 延迟用最近秩分位数；完整多步任务累计实际usage和LLM HTTP calls，工具calls另列；缺usage或消息不补0，性能与最终质量分开 |

不为凑指标将BLEU/ROUGE强套到工具执行、结构化规划或记忆任务；只有评测目标确实是参考文本重合时才考虑使用。参数合法只证明调用格式/取值符合约束，不能当作工具选对、参数符合用户目标或Tool Call Accuracy/F1。指标缺参考或标注时明确写N/A（未评测），不填0或推定通过。

需求理解指标读取最终需求模型，包含确定性后处理，评估的是完整需求理解模块；不声称这些分数单独代表原始LLM能力。工具调用需区分LLM选择和固定程序执行，不能把固定路径正确率当作模型自主选工具能力。

需求理解的槽位规则：`city`只把末尾“市”视为等价，其他字段严格相等；gold明确为null表示无值，模型null/省略均匹配，输出非空值判错。gold未出现的字段属于未标注，既不加分也不当false positive；因此此处只能称 **显式标注槽位的Slot Exact Accuracy**，不能声称完整槽位F1或全需求正确率。没有提取结果、缺测消息即使gold为null也计不匹配。Intent Accuracy可能高于整个需求字段规则全过率，二者分母和粒度不同。

工具参考格式是每个message step可选的`reference_tool_paths`：外层是允许的等价流程，内层是有序调用列表，每个调用为`{"tool_name":"...","arguments":{...}}`。严格比对完整参数对象，遗漏、错参、多调用或错误顺序均不能通过；允许不调用工具时可标注空流程`[[]]`。这是参考完整轨迹匹配率这一明确的二元Tool Call Accuracy口径，不是Ragas部分参数得分实现。该接口供未来**新冻结题库**使用，本次不改现有cases.json。

## 成功、候选与pending

每个message step的目标与禁止条件分别使用`goal_status`和`forbidden_status`。没有独立人工复核则pending；没有禁止条件时仅该项为pass。有任一fail则该步骤fail，均pass才pass，否则pending。一个任务的所有计分消息都pass才成功，有fail则失败，否则pending。非message步骤不计分，但沿用原题库步骤索引。

假设任务数N、确认成功S、确认失败F、待审P：最终TSR只有P=0时给定点值；未审时展示下界S/N、上界(S+P)/N。它们表示待裁决的可能范围，**不是统计置信区间**；下界0不表示正确率0。缺测仍在预期分母，按失败处理。正常normal与故障fault任务始终分列，不用故障任务抬高正常质量。

自动硬规则候选率要求该任务所有消息的全部必需检查已覆盖且pass，空checks不能真空通过；它只表示“候选自动合格”。过程规则失败也不能直接当作最终目标失败：用户目标可能经等价路径完成，或内部字段有误但答案与状态仍正确，需以独立目标裁决为准。反之，自动pass遇到目标/禁止条件人工fail时最终必须fail。原grade.human_status没有可追溯的独立证据入口，v2不直接消费它作为确认成功。

独立复核JSON用`results_sha256`绑定对应原始结果的**文件字节哈希**，防止将相似答案或旧批次裁决套用到新请求。示例结构（占位内容不能作为实际通过证据）：

```json
{
  "results_sha256": "对应results.json的SHA-256",
  "reviews": [
    {
      "case_id": "H01", "repeat": 1, "step": 1,
      "goal_status": "pending", "forbidden_status": "pending",
      "reason": "待人工核对",
      "answer_evidence": "待填写实际答案引用",
      "state_evidence": "待填写数据库/工具/行程/记忆引用"
    }
  ]
}
```

任何非pending裁决必须填写reason、answer_evidence、state_evidence。字段非空校验只能保证证据可记录，不能自动验证人工裁决真实性。禁止行为未确认不能自动通过；现有keywords/checks不足以替代语义和逐事实复核。

## all-3与τ-bench的关系

[τ-bench论文](https://arxiv.org/abs/2406.12045)使用对话终态与标注目标状态比较，并明确指出规则奖励可能未完整覆盖策略违规。论文的pass^k表示同一任务k次独立同分布试验**全部成功**的概率，跨任务取平均；n次试验、c次成功的估计式是`C(c,k)/C(n,k)`。当n=k=3且真实成功标签已确定时，算式退化为“3次都成功记1，否则0”，与实测三轮全过比例数值一致。此项目温度0、固定对话与快照、仅三次重复，且目标裁决未完成，所以报告优先写 **empirical all-3**。自动硬规则all-3不是最终成功的pass^3，更不能外推到更大k或等同τ-bench完整实验。

[Ragas官方Agent指标](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/agents/)将目标达成与工具调用分开：目标以参考结果核对终态；工具指标需要参考调用及参数，可选择严格或灵活顺序。v2沿用这种区分，不增加Ragas或LLM裁判依赖。指标定义参考行业常见名称，自动硬规则子项仅用于定位失败原因，不另造整体“智能得分”。

## 独立运行与来源追踪

在项目根目录，用已冻结的**同一批次**results.json、manifest.json、cases.json、fixtures.json生成新报告：

```powershell
$env:PYTHONPATH='server;server/evaluation'
$env:PYTHONDONTWRITEBYTECODE='1'
& server/.venv/Scripts/python.exe -B server/evaluation/metrics_v2.py <证据目录> --output <全新报告目录>
# 快照另存时显式提供，仍必须匹配manifest哈希：
& server/.venv/Scripts/python.exe -B server/evaluation/metrics_v2.py <证据目录> --cases <冻结cases.json> --fixtures <冻结fixtures.json> --reviews <独立reviews.json> --output <另一新目录>
```

仅输出metrics_v2.json、metrics_v2.md；有同名输出就拒绝覆盖。不会改results.json中的grade、原报告或人工审阅文件。输入哈希不符、重复结果键、未知任务/步骤、suite冲突、重复或缺少计划轮次、空任务等以invalid/非零退出拒绝计算；缺测结果则保留分母并计失败。

导出时重算当前grading.py的硬规则，不信任results里缓存的automatic_status；过程诊断也保留各子规则。记录原manifest的source_sha256、resource_sha256、模型/轨道/commit、原判分器哈希，以及本次输入、metrics_v2.py、grading.py、validate_cases.py哈希。原运行源码哈希不意味着当前共享工作区仍与之相同。题库/快照在manifest中有哈希时必须匹配；旧格式未提供哈希时只记录本次输入哈希，不补造历史认证。

直接调用`build_report`用于离线结构核对，其validity为unverified_in_memory；没有fixtures时proxy_basis为stored_checks_only，只能复核旧checks聚合，不能称正式同口径复算。通过export完成输入校验才标valid，来源限制仍须看provenance。

## 本次已有证据核对（未新增模型调用）

旧基线`.deploy/agent-full-20261008/formal-results`已使用恢复的原始快照完成v2导出，报告位于[baseline-metrics-v2](../.deploy/deepseek-20261009/baseline-metrics-v2/metrics_v2.md)，JSON记录`validity=valid`、`proxy_basis=recomputed_current_grading`。下表旧基线列已与该有效报告核对；已有四条试跑`.deploy/agent-review-20261009/results`仍为此前`build_report`内存结构核对，沿用原checks，不能混称已完成正式复算。未覆盖旧结果及报告。

| 指标 | 旧正式基线 | 已有四条试跑 |
| --- | --- | --- |
| 消息覆盖 | 141/141 | 4/4 |
| 正常任务自动候选 | 71/114（62.3%） | 4/4（100%，仅所选4题） |
| 正常任务最终TSR | N/A，114 pending，上下界0～100% | N/A，4 pending，上下界0～100% |
| 自动empirical all-3 | 22/38（57.9%） | N/A，只有1轮 |
| 显式意图标注Accuracy | 105/105 | 3/3 |
| 显式槽位Exact Accuracy | 142/156 | 7/7 |
| 行程约束包全满足 | 8/24（含记忆任务规划） | 3/3 |
| 完整终止 | 141/141 | 4/4 |
| tokens/task P50 / P95 | 2947 / 11130 | 6216 / 8823 |
| LLM calls/task P50 / P95 | 1 / 4 | 2 / 3 |

**快照哈希问题已解决。** 原始快照从`formal-source-final.tar.gz`提取至`.deploy/deepseek-20261009/original-snapshots/{cases,fixtures}.json`，已重新核对其字节SHA-256分别为`aa62ff2617e989f5b485b040200c0ebc3f217784e69573cb13b5b0c551dd1d77`、`3214b2a6d204e9fe9e6c3bb6fc723a4d6e19b9349ac183cb8e936bac2e87e01f`，精确匹配旧manifest及有效v2报告的inputs_sha256。

此前结果目录里的副本哈希不同，是因为`run_full.py`对源码题库/快照的原始文件字节计算manifest哈希，随后用`save`保存解析后的JSON对象；再次序列化会改变格式与文件字节，保存的copy不是原始字节拷贝。原始sourcepack中的文件与manifest一致，因此不能将该副本差异解释为原始快照损坏或尚未解决的来源问题。此次使用提取的原文件完成严格校验，没有放宽哈希检查或修改manifest。

四条目录本身未附cases/fixtures，但现在可显式使用上述原始快照复算；本节四条数值仍标记为此前stored_checks_only核对，未在本次文档更新中重新导出。四条manifest模型仍为`qwen3.7-flash-2026-07-15`，不是DeepSeek成绩。两批规模/场景不同，不能据4/4与71/114计算版本提升；有效导出也不代表人工目标复核完成，旧基线最终TSR仍为pending。

## RED→GREEN及验证

初次功能RED：15 failed，均因v2报告器尚未实现。补充三轮最终裁决用例得到1 failed / 19 passed（缺observed_all_3_success）；补充模块与任务效率用例得到2 failed / 20 passed（缺modules和tokens_per_task）。实现后，v2 23个用例和原evaluation 25个用例合计 **48 passed**。覆盖字段合法但目标待审、禁止行为pending/失败、目标失败、过程失败但目标成功、多步缺测、重复键、suite/order错误、选择子集及非message索引、空checks、缺usage、工具错参及等价流程、重复终止、快照哈希错误、复核哈希错误、只读原输入和不覆盖输出、槽位null/城市等价、完整多步任务累计效率，以及真实CLI子进程读取另存冻结快照、生成两个报告和拒绝覆盖输出。

验证命令（每次换唯一basetemp）：

```powershell
$env:PYTHONPATH='server;server/evaluation'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
& server/.venv/Scripts/python.exe -B -m pytest server/evaluation/test_metrics_v2.py server/evaluation/test_full.py server/evaluation/test_pilot.py -q -p no:cacheprovider --basetemp='.pytest-metrics-v2-final-20261009-e12b'
# 实际输出：48 passed in 1.11s
```

本机Python 3.14/Windows曾使pytest的0700临时目录拒绝访问；新测试仅为其自身文件用例创建唯一0777临时目录并清理。已关闭pytest缓存与pyc写入。只运行无模型的evaluation相关回归，没有占用主agent的业务/模型评测。

同时改变模型和修复代码，只能观察**联合变更**后的表现，不能归因于模型或某个修复单独贡献。需要单因结论时应固定其他条件做对照；正式新旧对比必须使用相同题库/快照和相同本次判分器哈希分别在新目录重算，原grading及原报告保持不动。没有完成这些步骤前不报告提升幅度。
