# AGENTS.md — M-GBA 项目守则

本文件约束所有参与 M-GBA 的人类与 AI Agent。开始任何设计、编码、重构或文档工作前，必须完整阅读本文件以及：

1. `docs/设计文件/核心原则.md`
2. `docs/设计文件/架构设计.md`
3. `docs/计划文件/MVP计划.md`

若三份文档与本文件冲突，以本文件和“核心原则”为准。不得静默选择另一种项目解释。

## 1. 项目不可漂移的核心

M-GBA 的研究对象是生命状态的自下而上跨尺度生成：

```text
L0 基因/转录调控
  → L1 分子/蛋白状态
  → L2 细胞个体行为
  → L3 组织、环境场与动态拓扑
  → L4 有机体宏观表型
```

必须同时遵守：

- 五层纵向递进是项目核心。
- 多智能体只是 L2 的细胞表达方式及 L2/L3 的工程问题。
- STEN 只是 L3 的语义通信和可塑拓扑子系统。
- GNN、LLM、强化学习和分布式框架都是可选实现，不是项目定义。
- MVP 可以简化每层内部模型，但不得删除层级或隐藏层间转换。
- 所有主生成流只能在相邻层之间发生，禁止跳层读取“上帝参数”。
- L4 首先是宏观表型观察者，只能通过低频环境/约束反馈影响下层，不能直接指定 L2 动作。

任何把项目重新表述为“多智能体平台”“LLM Agent 框架”或“动态图通信系统”的变更均属于架构漂移，必须停止并向用户说明。

## 2. 新能力准入门槛

看到一个新模型、论文、框架或功能时，不得直接加入主干。实施前必须明确回答：

1. 它属于 L0–L4 的哪一层，还是跨层基础设施？
2. 它替换或增强哪个现有简单基线？
3. 它回答什么研究问题或修复什么已复现的问题？
4. 用什么指标、数据和对照组判断它有效？
5. 失败时能否移除而不破坏其他层和实验协议？
6. 用户能否理解并在论文或答辩中解释它的原理、假设和局限？

如果答案不完整，将其记录为候选想法，不实施。不要以“以后可能有用”为理由增加代码。

## 3. 层级实现规则

### L0 Genome / Transcriptome

- 必须表达调控、表达状态和可审计扰动，不能只是 Agent 角色或提示词配置。
- 抽象基因必须标记为抽象变量，不得冒充真实 DNA。
- L0 只向 L1 输出 `TranscriptState` 等正式契约。

### L1 Molecular / Protein

- 必须承担 L0 到 L2 的真实转换职责，L2 不得绕过它直接读取基因值。
- 占位映射、有限状态、嵌入和动力学模型必须明确区分。
- 粗粒度模型不得表述为全原子或真实蛋白动力学。

### L2 Cell

- Cell 行为必须由 L1 状态和 L3 局部环境共同产生。
- 规则模型始终保留为基线；不得为了使用 LLM 而删除规则基线。
- LLM 只能作为 `CellPolicy` 的一种实现，不能改变五层协议。

### L3 Tissue / STEN

- 负责局部通信、空间邻域、环境场、群体结构和组织拓扑。
- STEN 变更必须报告其对跨尺度表型的影响，不能只报告 Token 或吞吐。
- Agent 只能提出拓扑意图；系统约束负责授权与提交。

### L4 Organism / Phenotype

- 宏观指标只能从 L3 状态聚合产生。
- 禁止把预期答案直接写入 L4 指标或 L2 目标函数。
- 中央 LLM 可用于轨迹解释、实验辅助和低频干预，不得成为微观行为导演。

## 4. 科学表述边界

除非有预注册判据、多个随机种子、对照实验和层级消融支持，否则禁止声称：

- 系统产生了“数字生命”；
- 宏观行为属于“涌现”；
- 架构解决或天然免疫 GNN 过平滑；
- 系统能从表型逆向编译真实 DNA；
- 模型具有临床、生物设计或疗效预测能力；
- 某个节点规模或自愈比例已经成立。

使用以下分级术语：

1. `contract demonstrator`：只验证接口和跨层路径；
2. `reference model`：可复现的简单基线；
3. `group dynamics`：局部交互形成群体模式；
4. `emergence candidate`：满足初步判据但尚未充分验证；
5. `validated result`：通过冻结协议、统计和消融的结果。

当前 `ReferenceCrossScaleRunner` 属于第 1 级。

## 5. 开工前流程

任何非平凡变更都先给出简短计划：

1. 变更目标与成功条件；
2. 所属层级和允许依赖；
3. 保留的基线；
4. 验证命令与预期 artifact；
5. 是否改变论文主张或科学边界。

如果需求存在多种解释，先列出差异。不得用实现方便替代用户的项目意图。

## 6. 编码与架构约束

- 优先最小、可替换、可测试的实现。
- 一次只升级一个层级；其他层使用稳定参考模型。
- 不为单次使用创建通用框架。
- 核心模型不得依赖 UI、Notebook 或下载缓存。
- 各层通过正式 DTO/Protocol 交互，不导入相邻层的内部实现。
- 实验观察代码可以读取全部层，但不得改变运行状态。
- 所有随机性来自显式种子；配置、模型版本和代码版本进入 manifest。
- 原始实验 artifact 追加保存，不手工修改结果。
- 模型、数据集或重量级依赖的下载必须有明确用途、磁盘预算和用户授权。
- 保留 `ReferenceCrossScaleRunner` 或其等价简单基线；复杂模型不得覆盖唯一基线。

## 7. 测试门禁

修改后按影响范围验证：

- 层内修改：运行该层单元测试。
- 层间契约：运行完整 L0→L4 trace 测试。
- L0/L1/L2/L3 模型修改：运行 L0 扰动传播测试。
- STEN 修改：同时运行 STEN 不变量测试和跨尺度测试。
- 实验协议修改：验证相同 manifest 的参考模型摘要稳定。
- 旧 CAR-M 迁移：添加旧 artifact 与新适配器的契约对照。

最低本地门禁：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\mgba.exe run --config configs/multiscale_demo.json
.\.venv\Scripts\mgba.exe sten-smoke --config configs/demo.json
```

覆盖率硬门禁（独立门禁，不替代上述快速门禁；coverage 追踪开销使全套测试约需 15–20 分钟）：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m coverage run -m unittest discover -s tests
.\.venv\Scripts\python.exe -B -m coverage report --fail-under=80
```

`source` 由 pyproject `[tool.coverage.run]` 提供；coverage 经 `pip install -e .[dev]` 装入开发环境，wheel 运行时零依赖身份不变。计量范围仅 `src/mgba` 核心包（scripts/、web/、services/ 不计）。

不得通过降低断言、删除基线或把失败结果硬编码为预期值来“修复”测试。

随机性主张的统计规范见 `docs/设计文件/统计规范.md`：“确定性重放”与“统计重复”为永久分离的两类证据，禁止把重放矩阵包装成统计证据。

## 8. 文档与决策同步

以下变更必须同步更新文档：

- 改变五层职责或层间协议：更新“核心原则”和“架构设计”。
- 改变里程碑、实验或 Definition of Done：更新“MVP计划”。
- 改变可行性前提或科学主张：更新“可行性评估”。
- 改变命令、目录或当前状态：更新 `README.md`。

重大架构决定应记录“为什么做、替代方案、证据、如何回退”。不要只记录最终选型。

## 9. AI Agent 的责任边界

AI Agent 可以帮助实现、测试、调研、重构和生成实验脚本，但必须：

- 明确区分用户提出的研究思想与 Agent 建议的实现细节；
- 不因热点、工具可用性或编码便利擅自改变研究核心；
- 不生成用户无法合理解释的关键科学主张；
- 对占位模型、推测和未经核验的文献显式标注；
- 发现原计划会破坏五层主线时立即停止并指出冲突；
- 优先帮助用户理解和验证，而不是单纯扩大代码量。

代码规模、模型数量和功能数量都不是进度指标。可信的跨层证据才是。

## 10. 当前项目状态

### 10.0 毕设收口期约束（2026-09-15 生效，最高优先级）

本项目已进入**本科毕业设计收口期**，目标从"扩展能力"转为"交付学位论文"。本节优先级高于第 10 节其余条款与任何计划文件；与其他条款冲突时以本节为准。执行 Agent 每次开工前必须先读本节。

生效背景（所有者 2026-09-15 确认）：已退出中国国际大学生创新大赛；本项目用作**软件工程专业**本科毕业论文；论文主张为软件工程方向（分层契约架构 + 证据治理机制），生物学部分降级为应用域与验证案例。完整推进计划见 `docs/计划文件/毕设推进计划-2026-09-15.md`。

**冻结项（未经所有者书面批准，一律不得执行）：**

1. **ADR 编号冻结在 0050。** 白名单例外仅两项：ADR-0051（目标表征分辨率消融）、ADR-0052（外部盲测协议）。两者均为可选项，默认不启动。
2. **不得新增层级。** 五层结构（L0–L4）为最终形态。
3. **不得新增实验族。** 现有实验族即为论文素材的全集。
4. **不得新增 CLI 子命令。**
5. **不得为"更好看"而改动任何既有 artifact、冻结配置、测试断言或预注册判据。** `FAILED` / `failed` / `criteria_not_met` / `未锚定` 在毕设语境下是**论文的核心论证材料**，不是待修复缺陷——论文命题正是"证据治理机制能够拦截不成立的科学主张"，改掉它们等于抽掉论文的实证。
6. **不得重启已关闭路线**：KD 可学性（ADR-0039/0040/0046）、OE 外推（ADR-0049）、跨背景通路外推（ADR-0047 No-Go，含不得解封 Arc H1、不运行 GEARS/scGPT/biolord）、旧空间 target 复用（ADR-0044 已消费禁用）。
7. **不得继续投入空间锚定链**：Wu/Jackson 为乳腺癌生态图谱，与 CAR-M 干预问题错配，场指标 30/30 出界属数据错配而非调参问题。除非新数据授权真正落地并另立 ADR。
8. **不得继续投入比赛相关产出**（PPT、叙事提纲、网站运营）。`web/` 与 `services/lab-api/` 代码本身保留，重新定位为"系统的 Web 交付层"，是论文实现章节的工程量素材。

**允许并鼓励的工作：**

- 工程收口：一键复现脚本、统计口径复核、架构图与 UML、同类软件对比基准、文档精简
- 数据溯源增强：`data/registry.json` 的 license/source 结构化字段与 `mgba data-check` 校验规则扩展
- artifact 结构补齐：为 `artifacts/carm-spatial-calibration/` 补 `manifest.json` 说明其 ADR-0044 降级身份（**不改写历史数值**）
- 论文写作相关的一切文档工作（`docs/毕设/`）
- 仓库开源治理：公开、tag、Release

**判据：** 任何新想法先问一句——"它是否直接进入学位论文的某一章？"不能明确回答的，写进 `docs/计划文件/毕设推进计划-2026-09-15.md` 的可选项或研究生阶段 backlog，不进代码。

### 10.1 历史状态记录


- 核心文档已按五层自下而上主线重写。
- `src/mgba/multiscale.py` 是 L0→L4 契约演示器，不是生物模型。
- `src/mgba/sten.py` 和 `simulation.py` 是 L3 子系统 smoke 实现。
- `src/mgba/layers/l0.py` 已实现六节点确定性离散 GRN；它仍是抽象 reference model，不是真实基因网络。
- `src/mgba/layers/l1.py` 已实现确定性翻译/降解与可关闭局部信号入口；它不是全原子或真实蛋白动力学。
- `src/mgba/layers/l2.py` 已实现五态确定性 Cell 状态机；它只消费本 Cell 的 L1 状态、局部环境和上一状态。
- `src/mgba/layers/l3.py` 已实现固定有向图上的局部资源、压力和信号更新；动态拓扑与 STEN 尚未进入五层主运行链。
- `src/mgba/layers/l4.py` 已实现只消费 `TissueState` 的即时表型、时间窗口摘要和最终结局；这些仍是无量纲 reference 指标。
- `src/mgba/runner.py` 已实现 L0/L4 慢时钟、L1/L2/L3 快时钟、相邻反馈、逐 tick trace、JSON checkpoint 和确定性恢复。
- `src/mgba/experiments.py` 已实现 3-seed 配对扰动/消融矩阵、逐层距离、传播 tick 和 raw/derived artifact。
- `src/mgba/reporting.py` 已实现只从 WP8 manifest 与 raw run 重算 CSV、SVG、静态 HTML 和文件摘要，不信任派生 summary。
- `scripts/mvp_demo.py` 已冻结 full/fallback 演示，中英文报告、wheel 复现说明和 0.1.0 发布清单已完成。
- 60 项测试已验证 L0/L1 稳态、L2 环境依赖/修复/应激/死亡吸收态、L3 局部环境动力学、L4 极端状态/方向性/窗口结局、100 tick 调度、断点恢复、21-run E0–E2 矩阵、修复表达敲低向 L4 传播、报告字节级重建、演示范围，以及 STEN 基本不变量。
- 全新 Python 3.12 venv 已通过无依赖 wheel 安装、60 项测试和 full demo。项目所有者已于 2026-08-19 接受 E0–E2 发布范围并授权首次 Git commit、`v0.1.0` tag 与 GitHub 推送；不借发布名义扩展模型。
- 默认 100 tick reference 轨迹当前结局为 `FAILED`；这是必须保留和解释的负面基线，不得为展示效果静默调参。
- WP8 显示 L2 静态替换在当前模型内产生最大终点差异；这只是定位五态 L2 规则的诊断证据，不证明静态 L2 更真实或更优。
- `v0.1.0` 是 E0–E2 的冻结参考基线；后续变更必须在新提交中演进，不得改写该发布身份。
- `src/mgba/scenarios/carm` 已作为 v0.2 首个真实数据代理锚定场景包接入；核心 L0–L4 DTO/Protocol 和 `ReferenceCrossScaleRunner` 未改变。
- CAR-M profile 由旧 752 个 TCGA-BRCA GAT 预测聚合而来，high/low/normal 为 323/273/156；它们是代理标签预测，不是临床真值，仓库内 profile 不含样本 ID。
- CAR-M L0/L1/L4 沿用参考模型，L2/L3 使用确定性场景适配器；旧患者级 GAT 不在生成热路径中。
- CAR-M 21-run 矩阵显示 0.7/1.0 剂量均传播到 L4，但当前高剂量增加炎症且最终负担代理略升；必须保留为负面基线，不得为展示效果静默调参。
- 当前 69 项测试包含原有 60 项回归和 9 项 CAR-M 数据、场景、群体扰动、checkpoint、矩阵与报告门禁。
- `src/mgba/feedback.py` 已实现可选 L4→L3 稳态反馈控制器（离散 PI + 死区 + back-calculation 反饱和经济通道；无记忆安全屏障压力地板）；它只消费正式 `OrganismState`、只输出 `FeedbackConstraint`，不指定 L2 动作，不读取 L0–L2 内部对象。
- `src/mgba/layers/l3.py` 新增 `ConstraintAwareTissueModel`；无约束时与参考 L3 动力学逐字段等价，有约束时约束进入 L3 source digest 哈希链。静态/参考 L3 模型与 CAR-M 适配器收到非空约束时显式抛错。
- `src/mgba/runner.py` 支持可选 `feedback_policy` 注入；checkpoint 恢复通过重放 `l4_observations` 重建控制器状态，checkpoint schema 与字段集不变；无注入时 0.2.0 基线位级不变。
- `src/mgba/feedback_experiments.py` 与 `mgba feedback-experiment` 已实现 E4 三条件（无/固定/状态反馈）对照矩阵，复用 WP8 配对比较指标与 artifact 协议。
- `scripts/synthetic_feedback_benchmark.py` 生成确定性仿真场景集（4 压力档 ×12 Cell）并运行 E4 基准；所有合成场景当前均为 `FAILED` 负面基线，不得为展示效果静默调参。
- 当前 109 项测试包含原有 83 项回归、23 项反馈边缘/防崩溃与确定性测试和 3 项冻结身份门禁。
- `src/mgba/layers/l2_active_inference.py` 已实现可选主动推理（变分自由能）L2 策略：预期自由能（风险+歧义）最小化、确定性 argmin、无采样；只消费本 Cell 的 L1 状态与局部环境，遵守 `CellModel` 协议；规则状态机未修改且仍是默认。
- `src/mgba/policy_experiments.py` 与 `mgba policy-experiment` 已实现规则 vs 主动推理 L2 策略配对对照，复用 WP8 配对比较指标；矩阵构造器强制两 runner 仅 L2 不同。
- `scripts/synthetic_policy_benchmark.py` 复用反馈基准数据集生成器运行策略对照基准；AIF 当前不优于规则基线（所有合成场景均 `FAILED`），不得为展示效果静默调参。
- 当前 127 项测试包含原有 109 项和 18 项主动推理数值极端/防崩溃/契约/配对矩阵测试。
- `src/mgba/layers/l3_adaptive.py` 已实现可选受治理动态拓扑：应激回避 T1 式边交换、提案→授权→提交治理链、每 tick 交换预算与入度守恒；Agent 只能提出意图，系统约束负责授权与提交；每次提交进入 L3 source digest 哈希链留痕。静态固定图模型未修改且仍是默认。
- `src/mgba/topology_experiments.py` 与 `mgba topology-experiment` 已实现 E5 静态 vs 动态拓扑配对对照，含拓扑稳定性指标；矩阵构造器强制两 runner 仅 L3 不同。
- `scripts/synthetic_topology_benchmark.py` 复用共享数据集生成器运行 E5 基准；冻结阈值下默认场景零提交、合成场景仅 calm 档每 seed 1 次确定性交换，结局仍全部 `FAILED`，不得为展示效果静默调参。
- 当前 142 项测试包含原有 127 项和 15 项动态拓扑极端/守恒/预算/契约/配对矩阵测试。
- `src/mgba/layers/l0_noisy.py` 已实现可选种子化转录噪声 L0：确定性右端位级不变 + 有界乘性噪声，噪声流由 `sha256(seed|cell|time)` 派生（显式种子、checkpoint 精确恢复、哈希链留痕）；确定性 GRN 未修改且仍是默认。`noise_sigma=0` 时基因值与确定性基线逐位一致。
- `src/mgba/e3_statistics.py` 与 `e3_experiments.py` 及 `mgba e3-experiment` 已实现 W14/M9 的 E3 群体统计协议：多种子噪声集合按预注册判据（CV 稳定性、微观驱动解耦、持续性）分级；不同 seed 已形成可统计分布。
- `scripts/synthetic_e3_benchmark.py` 复用共享数据集生成器运行 E3 基准；calm 档出现 2 个预注册判据命中的 emergence_candidate，按 §4 术语不构成已验证涌现，不得越级宣称。
- 当前 158 项测试包含原有 142 项和 16 项噪声/E3 确定性、边界、防崩溃与冻结基线门禁测试。
- `src/mgba/closed_loop_experiments.py` 与 `mgba closed-loop-experiment` 已实现 E4×E3 随机闭环对照（噪声开环 / 噪声闭环 / 确定性闭环三条件），按预注册稳定性判据（变号数、振幅、趋势）分级每 run 的慢时钟稳态序列；构造器强制闭环条件仅差噪声或仅差反馈。
- `scripts/synthetic_closed_loop_benchmark.py` 复用共享数据集生成器运行闭环基准；全部场景当前均为 `deterioration`/`lock`/`indeterminate`，无 `recovery` 或 `oscillation`——诚实负基线，不得为展示效果静默调参。
- 当前 169 项测试包含原有 158 项和 11 项闭环稳定性分级/防崩溃/契约/配对矩阵与冻结基线门禁测试。
- `src/mgba/neural.py` 已实现纯标准库神经基元（sha256 逐元素派生的 Xavier 式种子化矩阵、溢出安全 MLP 前向、入邻均值消息传递）；`src/mgba/layers/l0_neural.py` 与 `src/mgba/layers/l3_gnn.py` 已实现可选冻结权重 L0 MLP 与 L3 GNN 契约演示器（ADR-0017）：权重由显式 seed 派生而非训练，扰动钳制语义与静态拓扑门禁不变，GNN 不进入反馈闭环且不修改拓扑；确定性参考模型未修改且仍是默认。
- `src/mgba/neural_experiments.py` 与 `mgba neural-experiment`（`--layer l0|l3`）已实现参考 vs 神经单层替换配对对照，复用 WP8 配对比较指标；矩阵构造器强制两 runner 仅在 swapped 层不同。
- `scripts/synthetic_neural_benchmark.py` 复用共享数据集生成器运行 L0/L3 两组替换基准（4 场景 × 2 层 × 2 条件 × 3 seed）；神经变体是契约演示器，不宣称神经真实拟合或算力收益。
- 当前 191 项测试包含原有 169 项和 22 项神经基元/L0/L3 变体/配对矩阵/冻结基线门禁测试。
- `src/mgba/calibration.py` 已实现预注册确定性参数搜索核心（ADR-0018）：sha256 逐候选种子扫描 + top-k 坐标细化（重复点去重、参考向量恒为首评点，训练结果不可能差于参考）；核心不 import runner，目标函数注入式。
- `scripts/calibrate_l2_cell.py` 已实现 L2 `CellConfig` 19 标量的标定协议：目标为演示场景 60-tick `mean_homeostasis`，holdout 为四档合成压力场景，判定规则先验固定；冻结参考配置不被修改，标定向量只写入 artifact 并带完整溯源。
- 首次标定（search_digest `99ce6e355b8e0afa…`）：训练 0.2076→0.5927，四档 holdout 全部提升（判定 `generalized`；calm/injury `failed → stable`，severe/collapse 仍 `failed` 保留为负面结果）；多坐标顶到盒边，扩盒属下一轮预注册协议；这是 reference model 类内诊断，不得宣称生物拟合。
- 当前 204 项测试包含原有 191 项和 13 项标定协议/采样/搜索核心/artifact/冻结配置门禁测试。
- `src/mgba/layers/l2_latent.py` 已实现可选连续潜状态"虚拟细胞"L2 策略（ADR-0019）：AIVC 架构类（连续潜状态 + 泄漏 tanh 递推 + 非死亡四相读出）的纯标准库层内实例化；权重由显式 seed 派生而非训练；潜状态每 tick 从正式 `CellState` 确定性重建（无隐藏记忆，checkpoint 不变量不变）；死亡仅由同族硬护栏产生；规则状态机未修改且仍是默认。
- `src/mgba/latent_experiments.py` 与 `mgba latent-experiment` 已实现规则 vs 潜状态 L2 策略配对对照，复用 WP8 配对比较指标；矩阵构造器强制两 runner 仅 L2 不同。
- `scripts/synthetic_latent_benchmark.py` 复用共享数据集生成器运行潜状态对照基准；默认场景跨层效应 ≤1e-12、结局一致，合成基准 24 行全部 `FAILED`——零/负面基线，不得为展示效果静默调参；不宣称虚拟细胞级真实或优于规则基线。
- 当前 221 项测试包含原有 204 项和 17 项潜状态数值极端/防崩溃/契约/无隐藏记忆/配对矩阵测试。
- `src/mgba/autolab.py` 已实现自动实验调度器元层（ADR-0020）：预注册假设注册表 + 冻结"筛选→确认"策略的确定性闭环；核心不 import runner、不进 tick 循环，唯一执行通道是既有正式边界（WP8 式层内静态替换）；预算护栏 + 逐轮决策留痕 + append-only artifact。
- `mgba autolab` 首次会话 4 次评估内自主复现 WP8 结论（L2 最大杠杆点，30→100 tick 稳健）；`mgba autolab-propose` 提供 fail-closed 提案验证通道，提案永不自动执行、跳层提案直接拒绝——这是未来 LLM 假设提出器的唯一入口（Phase 2 需 API 授权，未实施）。元层结论只挂 reference-model 级，不得宣称自主科学发现。
- 当前 239 项测试包含原有 221 项和 18 项 autolab 注册表/策略/预算/提案门禁/真实复现基准测试。
- `data/aivc/` 已建立 AIVC 真实数据/模型对接的分级下载清单（纯调查，全部待授权未下载）：含六抽象节点 ↔ MSigDB Hallmark 语义桥与 Stage 1–3 资源表（scPerturb、Norman 2019、Tahoe-100M 子集、Geneformer、STATE）；本机不训练，下载须逐条满足 §6（用途、磁盘预算、授权）并走 CAR-M 式去标识聚合适配器，只锚定 L0/L1。
- ADR-0021 已固化多数据集存放与多细胞类型约定：原始外部数据永不入库（`data/raw/`）、入库聚合/合成数据必须登记 `data/registry.json`（来源/日期/SHA-256/许可/去标识/代理告知）、计划中资源清单先行；`mgba data-check` 为 fail-closed 门禁（当前 4 条目）。细胞类型只是 L0 层概念（`Genome` 模板 ± 群体 L0 钳制），禁止向 L1–L4 DTO 加类型标签；跨类型交互只经 L3 固定有向边与环境场两通道，L3 不得把类型标签注入 L2。
- `configs/multiscale_coculture_demo.json` 为纯配置两种群共培养场景（信号型 ×6 + 修复型 ×6，零契约变更）；实测类型差异经 L0→L1→L2 链涌现、跨类型影响经 L3 边介导（去跨群边改变 rep 群 L3 signal 轨迹）；stress 0.35 下两种群 tick 4 前全部死亡，与 100 tick `FAILED` 负面基线一致，不得为展示效果静默调参。
- `mgba demo-export` 已按 ADR-0022 升级为 CAR-M 跨尺度研究观察台：baseline/干预双画布同 tick 对照、L3 节点值显示投影、配对 L4、逐细胞 L0→L1→L2→局部 L3 差异与事件审计；交互模式参考旧 `D:\car-m-virtual-cell`，其 ABM/GAT 热路径未迁移。显示坐标/热图不是空间模型，不得据此声称真实组织空间动力学。
- `src/mgba/scenarios/carm/spatial.py` 已按 ADR-0023 实现可选 CAR-M 因果空间 L3：`SpatialTissueState` 显式保存单位方形坐标、12×12 压力/资源/信号场和半径邻域，全部进入 trace/checkpoint/source digest；空间模型无隐藏状态，只替换 L3，固定图 CAR-M 与冻结 21-run 矩阵不变。它是无量纲 reference model，不是物理扩散、空间组学重建或临床模型。
- `src/mgba/carm_spatial_experiments.py` 与 `mgba carm-spatial-experiment` 已实现固定图 vs 空间场同 seed 配对对照，构造器强制仅 L3 不同，并报告位移、边周转、终末场异质性和梯度；artifact 使用独立 append-only schema。
- 首次 CAR-M 空间矩阵 `carm-spatial-0f88408d1e44b25a`（2 条件×3 seed×20 tick）显示空间条件产生 L3=0.059804、L4=0.054401 的终末距离，两条件结局均为 `RECOVERED`；三个 seed 数值完全相同，只是确定性复现门禁，不能报告统计显著性或声称空间模型更真实/疗效更好。下一步优先 L3 内部消融与外部空间聚合统计锚定。
- `src/mgba/carm_spatial_ablation.py` 与 `mgba carm-spatial-ablation` 已按 ADR-0024 实现 movement×field_coupling×spatial_topology 的 2×2×2 确定性 L3 内部机制审计；显式使用单个 scenario seed 作为重放身份，不伪装成统计重复。默认未传机制开关的 ADR-0023 完整空间模型身份不变。
- 首次机制审计 `carm-spatial-ablation-f53f626b9f3fb9eb` 显示：全关与仅移动均为 L3/L4 零效应负对照；当前模型内 L4 描述性主效应为场耦合 0.048720、空间邻域 0.025588、移动 0.000898，全部 9 条件均 `RECOVERED`。只能据此优先锚定场异质性与邻域统计，不得声称真实生物效应。
- 当前 266 项测试包含原有 260 项和 6 项因子配置/负对照/单机制隔离/主效应/单层门禁/artifact 门禁。
- ADR-0025/0028 已把 CAR-M 空间 L3 的外部锚定预注册为两类互补聚合统计：Wu/Swarbrick Visium 三文件锚定局部场异质性，Jackson 乳腺癌 IMC 位置/分群两文件锚定邻域与距离；未被当前冻结指标消费的 mask 在下载前移出最小包。Rights 已核验为 CC BY 4.0 / CC BY 1.0 Generic，五文件共 241,284,013 bytes、本地峰值 ≤2 GB，用户已授权；当前环境无法连接 Zenodo，仍未下载。真实数据不进入生成热路径且只允许校准 L3。
- `src/mgba/spatial_anchors.py` 已按 ADR-0026 实现生成链外的去标识空间锚点聚合契约：source Rights/SHA-256/字节数门禁、Wu 六样本固定摘要 4/2 calibration/holdout、15 个 field 指标、Jackson 9 个 neighborhood 指标且只作 external validation、不可逆 sample alias、write-once target 与 digest/标识泄漏检查。旧 `D:\car-m-virtual-cell` 的本地 TCGA/Tahoe/OmniPath 缓存没有空间真值，旧 ABM 坐标/十通道场只作格式参考，不能进入 external target；当前未下载任何 Wu/Jackson 文件。
- `src/mgba/spatial_anchor_evaluation.py` 与 `mgba carm-spatial-anchor-evaluate` 已按 ADR-0027 实现正式 `SpatialTissueState` → 同构 24 metric → 39 个 calibration/holdout/external-validation 描述性对照；模型 field region 代理固定为到最近 tumor Cell 距离的 0.5 分位 proximal/distal 划分，评估只读、保存完整 raw run，不自动调参。当前仅用合成 target fixture 验证管线，不是外部验证结果。
- `src/mgba/spatial_source_adapters.py` 与 `mgba spatial-source-adapt-field/neighborhood` 已按 ADR-0028 实现生成链外源格式边界：逐输入 path/rights/bytes/SHA-256 复核；Wu 10x MatrixMarket 流式读取 + 三个冻结八基因代理；Jackson 位置/cluster exact join + 未映射标签拒绝。它不 import runner，不改变五层 DTO/Protocol；当前只有合成原始格式 fixture 证据。
- `src/mgba/intervention_experiments.py` 与 `mgba carm-intervention-experiment` 已按 ADR-0029 实现 AIDO 启发但不依赖 AIDO 权重的状态条件序列实验：runner 的可选 schedule 只在 L0 慢时钟生效，进入 manifest 并 checkpoint 精确重放；旧 constant perturbation 与无 schedule 身份不变。首次 5 条件×3 seed×60 tick 矩阵 `state-intervention-0e92bb234ba3a840` 的 short/long timing L4 距离为 0.006580/0.020899；晚期干预减轻 vitality/damage 代价但提高 inflammation，所有条件 `RECOVERED`，三个 seed 数值相同只作重放门禁。
- 当前 298 项测试包含原有 293 项和 5 项序列干预协议、L0 时钟/互斥门禁、状态审计、checkpoint 与 artifact 测试。
- `src/mgba/lab.py` 与 `mgba lab-export` 已按 ADR-0030 实现生成链外比赛数据契约：严格 `LabExperimentRequest`、统一 `LabRunBundle`、小型 catalog、按实验延迟加载 JSON 与 SHA-256 manifest；三套冻结回放覆盖 CAR 剂量、状态条件干预和固定图 vs 空间 L3，同输入可字节重建。真实空间 Target 缺失时固定显示“真实数据 Target 尚未生成”。
- `web/` 已实现并公开发布 Cloudflare/Sites 兼容的中文比赛站（`https://mgba-cross-scale-lab.zluo66977.chatgpt.site`）：首页、双轨实验工作台、逐 Cell L0→L4 检查、传播时间轴、L4 对照、证据页、30 天分享页、响应式阅读和离线 Demo。Worker 仅接受 ADR-0029 严格枚举并代理 `services/lab-api` 的受服务凭证 Python 边界；live runner 默认关闭，失败时明确回退预计算结果，不进入 tick 或修改任何 L0–L4 DTO/Protocol。
- `src/mgba/collective_dynamics.py` 与 `mgba collective-analyze` 已按 ADR-0031 实现生成链外群体动力学观察层：从正式 raw trace 重算 activation-stress reference proxy 的 direction/intensity/polarization、edge alignment、冻结群体状态/转换、外部 cohort、Cell archetype 和 L4 时间关联；不读取 CellAction、不进入 tick、不修改 E3 阶梯。artifact schema 为 `mgba-collective-dynamics-0.1`，write-once 且可字节重建。
- `LabRunBundle.analysis.collective_dynamics` 与 Cell 的可选 `collective_response` 已接入三套回放，顶层 `mgba-lab-run-bundle-0.1` 不变；工作台新增双轨相图、cohort 切换、转换点 L4/事件审计和旧 bundle 降级。live revision 为 `carm-state-conditioned-paired-0.3`，请求 schema 不变且 runner 继续默认关闭。
- 当前 319 项 Python 测试和 13 项前端测试已通过；前端 lint、生产构建和主要路由 smoke 通过。冻结单 tick、100 tick、WP8/CAR-M 基线身份均未改变。
- `src/mgba/autolab_planning.py` 与 `mgba autolab-plan` 已按 ADR-0032 实现 OCellus 启发的 Autolab 计划控制面：人工冻结注册表规范编译 closed-schema DAG，固定工具 Router，schema/DAG→架构/预算→manifest/history/科学表述三层 Verifier；计划与验证器均不 import runner、不含 evaluator、不自动修改失败计划，计划命令固定 `executed: false`。现有 `mgba autolab` 在执行前后强制核验，默认会话仍保持原 `autolab-71df3a1d06a63ce3`、四次评估顺序、L2 leader 与 history digest。
- `src/mgba/clock_sector.py` 已按 ADR-0033 实现生成链外 `ClockSectorObserver`：正式 `SpatialTissueState` + 同 tick 可见 L0 → 六方向×三中位最近邻归一化距离环，输出 `mgba-clock-sector-observation-0.1` write-once artifact；不修改坐标/场/边/Cell、DTO、checkpoint 或 trace。Wu/Jackson Target 到位前不实施表示优选。
- `src/mgba/ocellus_anchors.py` 已按 ADR-0034 实现生成链外 OCellus 离线扰动锚点：严格 source/model/Hallmark 许可与 SHA-256 身份、empirical/predicted 分栏、冻结六节点桥、train/holdout 隔离、train-only centroid、MAE/方向/Spearman、负面结果与精确人审 schedule 候选。当前未下载或加载 OCellus 权重，合成 fixture 只证明契约，候选固定 `executed: false` 且不得绕过 L1。
- 当前 356 项 Python 测试包含原有 319 项和 37 项 Autolab 计划、ClockSector 与 OCellus 锚点测试；冻结单 tick、100 tick、WP8/CAR-M、checkpoint、L0 扰动传播和三条最低 CLI 门禁保持通过。未新增在线 LLM API、OCellus 下载或深度学习依赖。
- 两轮代码评审修复已落地：playbook/live 显示 tick 恢复携带静态组织边（dose-response 与在线 bundle 的 edge_alignment 从静默 null 恢复为 ADR-0031 冻结公式实算值，live revision 升至 `carm-state-conditioned-paired-0.3`，跨语言 run ID 同步更新为 `lab-run-a2c881bf9f696cd2`）；旧 playbook 格式缺 `audit`/`l0_updated` 时工作台显式降级而不再整树崩溃；`collective-analyze` 的 `--config` 覆盖通道按 ADR-0031 §5 移除，阈值只来自冻结默认配置；ADR-0034 通过规则补记 1e-12 浮点护栏；`mgba.lab` playbook 路径接入 `verify_lab_bundle`；删除 ocellus_anchors 未使用别名与 DOM 时代死 CSS；前端 13 项测试通过。
- 四轴工程审查与零行为清理已落地（2026-08-30，算法/架构/规范/覆盖率四轴）：新增无依赖模块 `mgba.hashing`（canonical_json/digest_payload，拆除 experiment⇄layers 潜伏循环依赖）与 `mgba.validation`（数据边界校验单实现，fail-closed 语义统一：大写 digest 与未 trim 文本全域拒绝）；19 份 `_write_json_once` 收敛为 `mgba.experiment.write_json_once`（字节比对 + tmp 原子落盘）；60+ 处跨模块私有名导入经改名消除（compare_runs 等提升为公共名）；cli.py 拆为 37 个 `_register_*` 与 37 个 `_cmd_*`（parser 块与 HEAD 逐字节一致）；runner 模型版本 digest 改为构造时快照、checkpoint/trace 去除双重序列化、collective_dynamics 逐 Cell 序列构造降为 O(C·T)、扰动 profile 摘要复用已算指标。错误路径一致性：classify_metric 空输入抛 ValueError、SemanticMessage/TopologyProposal 补 bool/int 守卫、carm_spatial_ablation 补 E0 tick 完整性检查、l3_gnn 改用 neural.sigmoid。全部 563 项测试、冻结身份门禁、CLI 门禁与 ≥80% 覆盖率硬门禁保持通过；冻结基线、artifact 字节与 digest 链零变更。
- 测试覆盖率硬门禁已落地（仅测试加固，零模型/契约/协议变更）：pyproject 新增 `[tool.coverage]`（`source=["src/mgba"]`、`fail_under=80`、show_missing、`__main__` 守卫排除）与 `dev = ["coverage>=7.0"]` extra（wheel 运行时零依赖身份不变）；§7 与 README 记录独立覆盖率门禁命令（coverage 追踪使全套约 15–20 分钟，不替代快速门禁）。当前 488 项 Python 测试全绿，总量 91%（10969 语句）；cli.py 99%、lab_server.py 100%、feedback/e3/carm_spatial_experiments 100%、latent/policy/neural/topology_experiments 各 99%、scenarios/carm/data.py 99%（253 为构造不可达守卫，按预注册保留）、spatial_source_adapters.py 86%；剩余缺行均为公共 API 不可达的防御性 raise。逐模块 ≥80% 为一次性核验结果，长期硬门禁只锁总量 80（coverage.py 无 per-module fail_under）。所有冻结基线（单 tick、100 tick `FAILED`、WP8/CAR-M、E3–E5、checkpoint）身份与断言均未改动。
- ADR-0046 已执行 Hallmark 结构化目标重训（计算前预注册）：`mgba/hallmark_targets.py`（纯 stdlib）构建 `mgba-hallmark-target-0.1` 双臂靶标（50 Hallmark 集合维 + 冻结六节点并集头共 56 维，角色逐字继承 profile，构建期六节点头 1e-12 门禁逐单元通过）；`scripts/train_l0_hallmark_response.py`（仅 .venv-train）按 ADR-0037 冻结超参重训（Geneformer 768-d、seed 42、3000 epoch、CPU 单线程），双跑字节级确定性核验通过；`mgba/hallmark_training_evaluation.py` 与 `mgba hallmark-training-evaluate` 重算全部指标并在六节点头上施加冻结通过规则。**KD 主臂 failed**（holdout 头 MAE：MLP 0.014219 vs centroid 0.014819 vs ridge 0.014181，margin vs ridge −3.7e-05），OE 臂登记 `descriptive`；ridge 头 MAE 与 ADR-0040 逐位一致、质心头与预注册推导值 0.014819327207889445 完全一致（逐维独立基线零漂移）。KD 单敲低可学性在两条药方（更强特征 ADR-0040、更结构化目标本 ADR）均证伪后按记录关闭；未接链、未生成响应表。4 个 artifact 登记（registry 18 条目，`data-check` 绿）。ADR-0045 源码指纹按门禁既定通道更新（单/100 tick ID `mgba-4437aaca98878890`/`mgba-46de31d8b18fd252`，trace digest 与 WP8 matrix 身份不变）。当前 605 项测试全绿（基线 568 + 新增 37）。
- ADR-0048 已完成三组管线证伪对照（2026-09-11）：对照 1 标签打乱判据成立（打乱后 MLP 对质心 margin 转负 −0.001331，ADR-0037 门禁非空洞）；对照 2 层置换判据成立附边界（0/90 混合剖面落入真实库，传播 tick 碰撞率 0.6667，tick 指标不宜单独作证据）；对照 3 目标置换判据不成立，负面结果原样登记（置换 target 的 holdout NAE 10.2334 反而优于真实 12.1461，空间锚定评估器在 holdout field 指标上无区分度）。产物在 `artifacts/falsification/`。
- ADR-0049 已完成 OE 成分外推边界测定（2026-09-11）：holdout 48 单元 = component-seen 37 + component-unseen 11；外推层 MLP 0.0127172 vs 质心 0.0122139（margin −0.0005033），判据 failed，OE 外推方向正式关闭；ADR-0037 的 passed 保留但证据等级降为"插值证据"；对照锚核验偏差 0.0。产物在 `artifacts/extrapolation-boundary/`。
- D1-context-ood 登记缺口已修复（2026-09-11）：`data/registry.json` 18 → 26 条目，`tests/test_data_registry.py` 计数断言同步 18→26，`mgba data-check` 全绿；当前 631 项测试分批实测全绿（全套单次运行超出 300 秒窗口，采用分批实测口径）。
- 统计规范文档已就位（`docs/设计文件/统计规范.md`，2026-09-11）："确定性重放"与"统计重复"术语永久分离，随机主张最低 n≥10 seed + 预注册检验 + CI 与效应量同报，新"通过/效应"主张须配阴性对照；只约束新主张，不回溯改写历史 artifact 与冻结结论。
- `src/mgba/evidence_report.py` 与 `mgba evidence-report` 已按 ADR-0050 实现生成链外证据总览流水线：九类枚举输入（训练评估 / 外推边界 / 证伪对照 / 效应稳健性 / WP8 矩阵 / CAR-M 干预 / 空间锚定 / 桥覆盖 / 数据登记）经 collect → normalize → render → manifest → verify 五阶段归一化为 `mgba-evidence-report-0.1` 统一证据模型，输出零 JavaScript 中文 `index.html`（内联 SVG 条形图 / 森林图 / 色块表）、每区块 CSV 与 SHA-256 manifest 至 `artifacts/evidence-report/`；缺失源降级"未生成"，负面结果（KD failed、OE 外推 failed、对照 3 criteria_not_met、空间未锚定、WP8 FAILED 结局）汇总进顶部显著区；`--verify` 字节级比对实测通过。ADR-0045 源码指纹按既定通道更新（单/100 tick ID `mgba-a5065feac221b5fb`/`mgba-b8737d8be66d13e3`，trace digest 与 WP8 matrix 身份不变）。新增 13 项测试，`tests.test_evidence_report` / `tests.test_reporting` / `tests.test_frozen_identity` / `tests.test_cli` 实测全绿。
- 数据登记 schema 升至 `mgba-data-registry-0.2`（2026-09-15，毕设 T0.4，ADR-0021 修订 1，不新建 ADR）：新增受控词表 `license_ids` 与 `source_refs`；`mgba data-check` 新增词表、来源格式、`dataset:` 引用解析、许可传播（下游须覆盖全部上游许可）与 `repo:` 路径存在性校验，26/26 通过。ADR-0045 源码指纹按既定通道更新（单/100 tick ID `mgba-2cf0461e4813712f`/`mgba-7e9ffaa415f66163`，100 tick history digest `c073c47b…`；trace digest `20f95784…` 与 WP8 `matrix-7da4137aa39d5122` 实测不变）。**通道完整清单**：指纹变化时必须同步 7 处——`tests/test_frozen_identity.py`、`test_multiscale.py`、`test_demo.py`、`test_closed_loop.py`、`test_e3_statistics.py`、`test_neural.py`、`scripts/mvp_demo.py`；ADR-0050 只改了第一处，导致 Core CI 自 2026-09-11 起失败，本次已补齐。已知遗留：`data/aivc/D1-context-ood/` 下 8 个已登记文件被 `.gitignore` 排除，干净 clone 上 `data-check` 不通过，待所有者决策。
## Agent skills

### Issue tracker

Issues live in GitHub Issues on `ayisuplus/M-GBA`, managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary, unchanged (`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at root (created lazily by /domain-modeling) + ADRs in `docs/决策记录/`. See `docs/agents/domain.md`.
