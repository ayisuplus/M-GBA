# M-GBA 五层纵向 MVP 计划

> 版本：0.8  
> 日期：2026-08-18  
> 第一阶段周期：16 周  
> 长期节奏：随大三、大四课程持续升级

详细的工作包、每周任务和质量门禁见 [MVP实施计划](MVP实施计划.md)。

## 1. MVP 定义

MVP 不是“做出一个多智能体系统”，而是：

> 完成一个从 L0 微观调控出发，经 L1 分子状态、L2 细胞行为、L3 组织动力学，最终生成 L4 宏观表型的最小可运行闭环。

首个场景选择虚拟组织的损伤—修复—稳态。所有层可以使用简化模型，但必须存在、必须相邻传递、必须留下跨层 trace。

## 2. 首要研究问题

1. L0 的受控扰动能否经过各层产生可测的 L4 表型差异？
2. 哪一层会放大、缓冲或改变这种扰动？
3. 多个局部 Cell 的相互作用能否形成未被单个 Cell 直接编码的组织级模式？
4. 宏观环境反馈能否改变下一轮微观表达并形成闭环？

STEN、LLM Agent 和通信性能是第四个问题之后的增强研究，不再作为 MVP 的入口。

## 3. 每层最小实现

| 层 | 第一版模型 | 必须完成的能力 | 后续课程升级 |
|---|---|---|---|
| L0 | 小型离散 GRN | 表达更新、激活/抑制、敲低/过表达 | 概率模型、连续动力系统、真实转录组 |
| L1 | 显式映射+有限状态 | 受体/信号/修复/代谢状态 | 深度学习、蛋白嵌入、动力学 |
| L2 | 规则 Cell 状态机 | 感知、状态转换、分泌、存活/死亡 | ML policy、RL、轻量 LLM |
| L3 | 图+简单环境场 | 邻域、信号传播、组织拓扑、局部资源 | GNN、STEN、动态图、多智能体调度 |
| L4 | 指标聚合器 | 活力、稳态、炎症/损伤、恢复 | 表型模型、因果分析、中央解释器 |

## 4. 16 周里程碑

| 周次 | 里程碑 | 交付物 | 验收条件 |
|---|---|---|---|
| W1 | M0 核心原则与契约 | 五层对象、相邻接口、trace schema | 架构中不存在跳层依赖 |
| W2–3 | M1 L0 调控层 | 抽象 GRN、表达状态、扰动工具 | 同种子可复现；敲低只直接改变 L0 |
| W4 | M2 L1 分子层 | 表达映射、分子状态转换 | L1 只消费 L0 输出和相邻反馈 |
| W5–6 | M3 L2 单细胞 | 状态机、局部感知、动作 | L2 行为随 L1 变化，不能直接读取 L0 |
| W7–8 | M4 L3 组织层 | 多 Cell、邻域图、场、局部通信 | L2 行为能改变节点环境与组织状态；固定图基线保持拓扑不变 |
| W9 | M5 L4 宏观层 | 活力、稳态和损伤指标 | 指标只从 L3 聚合，不预写实验答案 |
| W10 | M6 五层贯通 | `CrossScaleRunner`、跨层 trace | 一次 L0 扰动完整传播到 L4 |
| W11 | M7 反馈闭环 | L4 环境压力→L3/L2/L1/L0 | 反馈慢时钟、可审计、可关闭 |
| W12–13 | M8 因果与消融 | 层冻结、层替换、扰动实验 | 能量化每层对 L4 差异的贡献 |
| W14 | M9 群体与涌现预实验 | 多种子、宏观模式判据 | 区分聚合、群体动力学和涌现 |
| W15 | M10 最小可视化 | 五层 trace、状态和表型图 | UI 只读 artifact，不参与计算 |
| W16 | M11 交付冻结 | 英文技术报告、复现说明、演示 | 空环境可运行，结论可追溯到实验 ID |

## 5. 实验矩阵

### E0 跨层完整性

- 检查每个运行步是否产生 L0–L4 状态和相邻转换事件。
- 故意删除或绕过一层时，契约测试必须失败。
- 目的：证明架构真的纵向贯通，而非用五个名字包装单层模型。

### E1 L0 扰动传播

- 对修复、信号或代谢相关抽象基因进行不同强度的敲低/过表达。
- 记录每层效应量和传播延迟。
- 输出“扰动强度—L1—L2—L3—L4”的路径图。

### E2 层级消融

- 冻结 L1、替换 L2 策略、关闭 L3 通信或移除 L4 反馈。
- 比较 L4 表型分布，而不是只比较运行速度。
- 目的：证明各层有真实计算职责，而不是装饰性封装。

### E3 微观规则到宏观模式

- 多个 Cell 仅使用局部信息。
- 在多个种子下观察空间分群、稳态、损伤扩散或修复波。
- 只有宏观模式没有被直接写入 Cell 目标且跨种子稳定出现，才进入“涌现”候选。

### E4 反馈闭环

- 比较无反馈、固定反馈和状态相关反馈。
- 观察系统能否恢复稳态，或是否出现震荡、锁死和恶化。
- L4 反馈只能改变环境和约束，不能直接设置 L2 行为。

### E5 L3/STEN 增强

- 在五层闭环稳定后，比较静态邻域、规则 rewiring 和 STEN 语义拓扑。
- 指标同时包含宏观表型、通信成本、拓扑稳定性和多样性。
- 该实验回答 STEN 对数字生命跨尺度过程的贡献，而不是把项目重新定义成通信系统。

## 6. Definition of Done

第一阶段 MVP 完成必须满足：

- L0–L4 都有运行时状态，不是文档占位符。
- 所有主生成流只发生在相邻层之间。
- 至少一个 L0 扰动在 L4 产生可复现差异，并有完整 trace。
- 至少完成一次层级消融，证明某层不是空包装。
- L4 宏观指标没有直接编码进 L2 的目标答案。
- 规则基线在相同 manifest 下产生相同摘要。
- 负面结果、无效扰动和系统局限同样保存。
- 不宣称真实 DNA、蛋白动力学、临床效果或已证明数字生命。

## 7. 与大三、大四学习同步

### 大三上：计算与实验基础

- Python、数据结构、线性代数、概率统计；
- 完成确定性五层参考模型和测试；
- 重点学习“模型假设如何进入代码”。

### 大三下：机器学习进入各层

- 用课程中的回归、分类和神经网络替换一个明确层级；
- 保留简单模型作为基线；
- 第一次形成 E0–E2 的英文技术报告。

### 大三暑假至大四上：图学习与群体智能

- 把 GNN、动态图和 STEN 用于 L3；
- 研究微观交互、拓扑与宏观表型的关系；
- 再评估 L2 是否需要 LLM，而不是为了热点强行接入。

### 大四：论文与外部验证

- 冻结研究问题和实验协议；
- 完成 E3–E5、多种子统计、公开仓库和英文论文稿；
- 用项目发展过程证明独立研究能力，而不只展示最终 Demo。

## 8. 当前迭代

- [x] 纠正项目定义：五层纵向递进为核心，多智能体/STEN 为子问题。
- [x] 建立五层核心原则和层间契约。
- [x] 初始化最小 `CrossScaleRunner` 和 L0–L4 trace。
- [x] 验证 L0 扰动能改变 L4，且中间路径完整。
- [x] 将现有 STEN smoke 明确归档为 L3 子系统测试。
- [x] 冻结五层 DTO/Protocol、相邻转换事件和实验 manifest。
- [x] 建立“禁止跳层、不得缺层、单层可替换”的自动化门禁。
- [x] 冻结并实现六节点离散 GRN、持续扰动、独立轨迹和稳定性/剂量响应测试。
- [x] 冻结并实现 L1 粗粒度翻译/降解、相邻信号入口和稳态/单调性测试。
- [x] 冻结并实现 L2 五态 Cell 状态机、局部感知、动作与死亡吸收态测试。
- [x] 冻结并实现第一版 L3 固定组织图、节点级微环境更新与组织聚合；当前结果不得用于群体动力学或涌现结论。
- [x] 冻结并实现第一版 L4 即时宏观表型、窗口摘要、最终结局与边界测试；指标只消费正式 `TissueState`。
- [x] 实现 WP7 多速率五层 Runner、相邻快速反馈、检查点、可回放逐步 trace 与 L4 时间窗口。
- [x] 冻结并执行 WP8 E0–E2：3 档 L0 钳制、L1–L3 静态替换、逐层效应和传播 tick，共保存 21 条 raw trace。
- [x] 完成 WP9：只从 `matrix-7da4137aa39d5122` raw artifact 重建 5 份 CSV、4 张 SVG、静态 HTML 和 SHA-256 manifest，不在绘图阶段调参。
- [x] 完成 WP10 发布冻结：中英文技术报告、wheel 安装与空环境复现、full/fallback 演示和发布清单。
- [x] 项目所有者于 2026-08-19 接受 E0–E2 范围，并授权首次 Git commit、`v0.1.0` tag 与 GitHub 推送。
- [x] 将旧 CAR-M 资产适配为首个独立场景包，保持核心 DTO/Protocol 和参考模型不变。
- [x] 从 752 个旧 TCGA-BRCA 预测生成无样本 ID 的聚合 profile，并保存源 artifact 摘要与代理标签声明。
- [x] 完成 63-Cell CAR-M 固定图、群体 L0 剂量、L2/L3 场景模型及 21-run E0–E2 矩阵。
- [x] 实现可选 L4→L3 稳态反馈参考控制器（ADR-0012）：离散 PI + 反饱和 + 安全屏障，仅经 `FeedbackConstraint` 改变 L3 环境场；无注入时冻结基线位级不变。
- [x] 冻结并执行 E4 三条件对照（无反馈/固定反馈/状态反馈），复用 WP8 配对比较指标；当前三条件均为 `FAILED` 负面基线。
- [x] 提供仿真场景数据集生成与基准脚本 `scripts/synthetic_feedback_benchmark.py`（4 压力档 × 12 Cell，种子确定、幂等、SHA-256 校验）。
- [x] 实现可选 L2 主动推理（变分自由能）Cell 策略（ADR-0013）：预期自由能最小化、确定性 argmin、无采样；规则状态机保留为默认与永久基线。
- [x] 冻结并执行规则 vs 主动推理的 L2 策略配对对照（`mgba policy-experiment`），复用 WP8 配对比较指标；当前两策略均为 `FAILED` 负面基线。
- [x] 提供规则 vs 主动推理仿真基准脚本 `scripts/synthetic_policy_benchmark.py`（复用反馈基准数据集生成器）。
- [x] 实现可选 L3 受治理动态拓扑（ADR-0014）：应激回避 T1 式边交换、提案→授权→提交治理链、交换预算与入度守恒；固定图保留为默认与永久基线。
- [x] 冻结并执行 E5 静态 vs 动态拓扑对照（`mgba topology-experiment`），含拓扑稳定性指标（交换计数/交换 tick/边数差）；冻结阈值下默认场景零提交，均为 `FAILED` 负面基线。
- [x] 提供 E5 仿真基准脚本 `scripts/synthetic_topology_benchmark.py`（复用共享数据集生成器，calm 档每 seed 恰好 1 次确定性交换）。
- [x] 实现可选 L0 种子化转录噪声模型（ADR-0015）：确定性右端位级不变 + 有界乘性噪声，噪声流由 `sha256(seed|cell|time)` 派生，checkpoint 精确恢复；确定性 GRN 保留为默认。
- [x] 实现并执行 W14/M9 的 E3 群体统计协议（`mgba e3-experiment`）：多种子噪声集合按预注册判据分级（aggregation / group_dynamics / emergence_candidate）；不同 seed 已形成可统计分布，打破"所有 seed 轨迹相同"的旧限制。
- [x] 提供 E3 仿真基准脚本 `scripts/synthetic_e3_benchmark.py`（复用共享数据集生成器）；calm 档出现 2 个预注册判据命中的 emergence_candidate，按 §4 术语不构成已验证涌现。
- [x] 实现 E4×E3 随机闭环实验（ADR-0016）：`mgba closed-loop-experiment` 组合噪声 L0 与 L4→L3 反馈控制器，按预注册稳定性判据（震荡/锁死/恢复/恶化/不定）分级慢时钟稳态序列；当前全部合成场景判为 deterioration/lock/indeterminate，保留为负面基线。
- [x] 提供随机闭环仿真基准脚本 `scripts/synthetic_closed_loop_benchmark.py`（复用共享数据集生成器）。
- [x] 实现分层异构神经网络契约演示器（ADR-0017）：纯标准库神经基元 + 可选冻结权重 L0 MLP（`NeuralGrnModel`）与 L3 消息传递 GNN（`GnnTissueModel`）层内变体；确定性参考模型保留为默认与永久基线。
- [x] 冻结并执行参考 vs 神经单层替换配对对照（`mgba neural-experiment --layer l0|l3`），复用 WP8 配对比较指标；提供仿真基准脚本 `scripts/synthetic_neural_benchmark.py`（复用共享数据集生成器）。
- [x] 实现预注册 L2 规则参数标定（ADR-0018）：`mgba.calibration` 纯搜索核心 + `scripts/calibrate_l2_cell.py`；目标函数、搜索空间、预算与 holdout 判定规则在任何评估前冻结，参考配置不被修改。
- [x] 执行首次标定：训练 mean homeostasis 0.2076→0.5927（+0.385），四档 holdout 全部提升（判定 `generalized`；calm/injury 结局 `failed → stable`，severe/collapse 仍 `failed` 保留为负面结果）；多坐标顶到盒子边缘，扩盒属下一轮预注册协议。
- [x] 实现可选 L2 连续潜状态"虚拟细胞"策略（ADR-0019）：AIVC 架构类（连续潜状态 + 结构化转移算子 + 相位读出）的纯标准库层内实例化；冻结种子派生权重（非训练），潜状态每 tick 从正式 `CellState` 确定性重建（无隐藏记忆）；死亡仅由同族硬护栏产生；规则状态机保留为默认与永久基线。
- [x] 冻结并执行规则 vs 潜状态 L2 策略配对对照（`mgba latent-experiment`），复用 WP8 配对比较指标；提供仿真基准脚本 `scripts/synthetic_latent_benchmark.py`；默认场景两条件均 `FAILED` 且跨层效应 ≤1e-12（零结果基线），合成基准 24 行全部 `FAILED`，不调参。
- [x] 实现自动实验调度器元层（ADR-0020，Phase 1）：预注册假设注册表 + 冻结"筛选→确认"策略的确定性闭环（`mgba autolab`），核心不 import runner、评估器注入式；首次会话 4 次评估内自主复现 WP8 结论（L2 最大杠杆点，30→100 tick 稳健）。
- [x] 提供 fail-closed 提案验证通道（`mgba autolab-propose`）：提案须符合注册表 schema 且永不自动执行，跳层提案直接拒绝；这是未来 LLM 假设提出器的唯一入口，人审后生效。
- [x] 将旧 `D:\car-m-virtual-cell` 的 Canvas/场叠加/实验对照交互模式迁入只读观察层（ADR-0022），把 `mgba demo-export` 升级为 baseline/干预同 tick 双轨 CAR-M 研究观察台；旧 ABM/GAT 热路径不迁移，核心 L0–L4 DTO/Protocol 与冻结矩阵不变。
- [x] 实现 CAR-M 因果空间 L3 单层增量（ADR-0023）：`SpatialTissueState` 显式保存归一化坐标、12×12 压力/资源/信号场和空间邻域，checkpoint 落盘/恢复精确；`mgba carm-spatial-experiment` 强制固定图与空间条件只在 L3 不同，并报告位移、边周转、场异质性和梯度。固定图 CAR-M 与冻结 21-run 矩阵不变。
- [x] 执行首次 2 条件 ×3 seed ×20 tick 空间配对：空间条件在 L3/L4 产生可测差异且两条件均为 `RECOVERED`；三个 seed 数值完全相同，只视为确定性复现而非统计重复。下一轮须先做 L3 内部机制消融和外部空间统计锚定，不据此声称疗效或真实性提升。
- [x] 完成 movement×field_coupling×spatial_topology 的 2×2×2 L3 内部因子审计（ADR-0024）：全关条件与固定图 L0–L4 零差异；仅移动有位移但 L3/L4 零差异；当前模型内 L4 描述性主效应为场耦合 0.048720、空间邻域 0.025588、移动 0.000898。下一步数据锚定优先局部场异质性和细胞邻域统计。
- [x] 预注册并完成 CAR-M 空间 L3 外部数据锚定（ADR-0025/0028）：Wu/Swarbrick Visium 三文件与 Jackson IMC 两文件共 241,284,013 bytes 已下载核验，已生成去标识 target 并完成首次同指标评估。
- [x] 完成旧 `D:\car-m-virtual-cell` 空间资产复查：本地 TCGA/Tahoe/OmniPath 缓存均非空间真值；旧 ABM 坐标/十通道手工场只能作为格式与语义参考，缺失其声称的 `trajectories.json` source data，不能伪装成真实 L3 锚点。
- [x] 实现 ADR-0026 去标识空间锚点聚合契约：两种 observation bundle、4/2 固定摘要划分、15 个场指标、9 个邻域指标、external-validation 隔离、write-once target 与 digest/隐私校验；真实文件已贯通 CLI 并生成登记 target。
- [x] 实现并执行 ADR-0027 模型—Target 同指标评估：正式 `SpatialTissueState` 投影 24 个同名指标，按 calibration 15 / holdout 15 / external validation 9 生成 39 个描述性对照；首次真实 target 结果为未锚定，不产生生物验证结论。
- [x] 实现 ADR-0028 源格式适配器：下载前冻结三个透明八基因场代理及确定性归一化；流式读取 Wu 10x MatrixMarket；Jackson 位置/cluster exact join 且未知标签 fail-closed；逐个归档/解压输入复核路径、Rights、bytes、SHA-256。七项合成原始格式测试已贯通 target checker。
- [x] 实现并执行 ADR-0029 AIDO 启发的状态条件序列干预：runner 可选 schedule 只在 L0 慢时钟生效并进入 manifest/checkpoint；CAR-M 2×2 timing×exposure 设计强制 onset 前逐层零差异。首次 15-run 矩阵 short/long timing L4 距离为 0.006580/0.020899，晚期干预体现 vitality/damage 与 inflammation 的混合 trade-off；仍是 reference-model 证据。
- [x] 实现 ADR-0030 比赛版跨尺度虚拟实验室：`mgba lab-export` 冻结 request/bundle/catalog schema，并从既有 artifact 确定性生成三套延迟加载实验与 SHA-256 manifest；`web/` 完成首页、工作台、分享页、证据页、移动端阅读、Open Graph 和离线 Demo。观察层不进入 tick、不修改 DTO/Protocol。
- [x] 实现受限在线链：Worker 对唯一 CAR-M 状态条件协议做严格枚举校验、确定性 run ID、5 次/IP/小时门禁、45 秒代理超时与 R2 30 天结果读取；Python 服务以服务凭证保护、全局并发 2，并只执行单组 baseline/intervention。`LAB_LIVE_RUNS_ENABLED=false` 时明确回退预计算 bundle，不伪装在线结果。
- [x] 完成比赛站门禁并扩展 ADR-0031 回归：319 项 Python 测试、13 项前端契约/交互测试、lint、生产构建与主要路由 smoke 通过；`mgba run` 和 `sten-smoke` 保持通过。
- [x] 实现 ADR-0031 群体动力学观察层：生成链外 `CollectiveDynamicsObserver` 从正式逐 Cell trace 重算 direction/intensity/polarization、冻结状态与转换、外部 cohort、个体 archetype 和 L4 时间关联；不改变 L0–L4、tick、checkpoint、history digest 或 E3 阶梯。
- [x] 将群体相图接入三套比赛 bundle 与工作台：baseline/intervention 双轨路径与主播放器同步，支持全组织/四角色切换、转换点事件审计、旧 bundle 降级和移动端阅读；新增序列体积增长均低于 15%，live runner revision 升级到 `carm-state-conditioned-paired-0.2` 且继续默认关闭。
- [x] 实现 ADR-0032 OCellus 启发的 Autolab 计划控制面：冻结注册表→closed-schema DAG、固定工具 Router、schema/DAG→架构/预算→manifest/history/科学表述三层 Verifier；`mgba autolab-plan` 永不执行，现有 `mgba autolab` 通过前后核验后仍复现原顺序、L2 leader 和 history digest。
- [x] 实现 ADR-0033 `ClockSectorObserver`：从正式空间 L3 与同 tick 可见 L0 生成六方向×三归一化距离环的独立 write-once artifact；顺序、尺度和 checkpoint 重建稳定，观察前后 trace/checkpoint/history digest 不变。半径/网格/ClockSector 真实 holdout 比较仍等待 Wu/Jackson Target。
- [x] 实现 ADR-0034 OCellus 离线扰动锚点契约：许可/模型/SHA-256、empirical/predicted 分栏、冻结 Hallmark 六节点桥、train-only centroid、holdout MAE/方向/Spearman、负面结果和精确人审 schedule 候选均 fail-closed；当前无权重下载、无真实 OCellus 结果、无生成热路径接入。
- [x] 完成 OCellus 三阶段回归门禁：Python 总测试增至 356 项；`mgba autolab-plan` 零执行、真实 `mgba autolab` 原身份/顺序/leader、冻结 identity、L0 扰动传播、完整测试与 AGENTS.md 三条最低命令均通过。
- [x] 已下载并核验 S1/S2 五文件，冻结真实解压 inventory、region_map 和 cluster label_map，生成可字节重建的去标识 L3 target，并完成首次评估。ADR-0043 标定因 105 次评估超过 89 次上限，按 ADR-0044 仅保留为探索性结果；新的确认需新 target。
- [x] 以 ADR-0047 冻结 L0/L1 真实 Perturb-seq state-conditioned 方法路线：四个 CRISPRi 背景、未处理对照状态、50 维 Hallmark target、5 salt × 4 outer context 的 gene/context/joint OOD、低秩交互与严格评估门均已实现；不修改 L0–L4。
- [x] 补齐 Replogle RPE1、Nadig HepG2/Jurkat，生成四背景 bundle 并通过共享基因 ≥500、各背景 split-half Spearman ≥0.30 的数据门；最终可建模交集为 559 个基因。
- [x] 以固定公共镜像摘要封存 Arc H1，锁定559基因×20折 split，并完成零泄漏简单基线筛查；joint-OOD 最佳为 gene-only ridge（标准化 macro-MAE 0.75420）。
- [x] 完成 20 折低秩交互模型开发评估：joint-OOD 标准化 macro-MAE 0.81214，差于最佳简单基线 0.75420（相对退化 7.68%，四背景 0/4 胜出），已触发预注册 No-Go。按冻结规则停止 GEARS/scGPT/biolord 与 Arc H1，不换指标、不挑子集、不扩展网络，回到 evidence-governed 软件论文路线。
