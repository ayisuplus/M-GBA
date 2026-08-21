# M-GBA MVP 实施计划

> 版本：0.7  
> 日期：2026-08-18  
> 实施周期：16 周  
> 对应路线图：`MVP计划.md`  
> 项目守则：仓库根目录 `AGENTS.md`

## 1. 实施目标

在 16 周内交付一个可运行、可复现、可扰动、可消融的五层纵向数字生命参考系统：

```text
L0 基因/转录调控
  → L1 分子/蛋白状态
  → L2 细胞状态与行为
  → L3 多细胞组织与微环境
  → L4 宏观表型
```

首个研究场景为“虚拟组织损伤—修复—稳态”。系统需要证明一次 L0 扰动能够通过所有相邻层传播到 L4，并能量化每层对最终表型的影响。

当前 `ReferenceCrossScaleRunner` 只是契约演示器。本计划的任务是把它升级为具有明确层内动力学、时间推进和实验能力的 reference model，而不是立即追求生物真实性。

## 2. 核心 MVP 与扩展 MVP

### 2.1 核心 MVP——必须完成

- L0–L4 五层运行时状态和相邻层接口。
- 小型可解释调控网络和可审计扰动。
- 粗粒度分子状态转换。
- 规则 Cell 状态机和多个 Cell 实例。
- 简单组织图、局部环境与宏观表型。
- 多速率 `CrossScaleRunner`、manifest、事件和 trace。
- E0 跨层完整性、E1 L0 扰动、E2 层级消融。
- 相同配置和种子可复现。

### 2.2 扩展 MVP——核心完成后再做

- L4 到下层的慢反馈闭环。
- 空间场和更复杂组织动力学。
- STEN 动态拓扑对照实验。
- GNN、机器学习或 LLM Cell Policy。
- 交互式 Web/3D 可视化。

扩展项不得挤占核心 MVP 的测试、实验和文档时间。

## 3. 最终演示场景

演示包含基线组和扰动组：

1. 初始化一组具有异质表达状态的虚拟 Cell。
2. L0 调控网络在损伤输入下更新表达。
3. L1 将表达转换为信号、修复、代谢和死亡相关分子状态。
4. L2 Cell 仅依据 L1 状态与 L3 局部环境决定激活、修复、分泌或死亡。
5. L3 聚合局部行为，更新组织损伤、资源和通信结构。
6. L4 计算整体活力、炎症和稳态。
7. 对修复相关 L0 节点进行敲低，比较完整 L0–L4 轨迹。
8. 冻结或旁路一个层级，完成层级消融。

最终演示必须能回答：变化在哪里产生、经过哪些转换、在哪一层被放大或缓冲、最终如何影响宏观表型。

## 4. 工作包与依赖

```mermaid
flowchart LR
    WP0[WP0 规范与实验骨架] --> WP1[WP1 层间契约]
    WP1 --> WP2[WP2 L0 调控]
    WP2 --> WP3[WP3 L1 分子]
    WP3 --> WP4[WP4 L2 Cell]
    WP4 --> WP5[WP5 L3 Tissue]
    WP5 --> WP6[WP6 L4 Phenotype]
    WP6 --> WP7[WP7 五层 Runner]
    WP7 --> WP8[WP8 扰动与消融]
    WP8 --> WP9[WP9 统计与可视化]
    WP9 --> WP10[WP10 交付冻结]
```

不能为了并行开发而跳过依赖。可以先写接口和测试，但上层正式实现只能消费相邻下层的稳定输出。

## 5. 工作包明细

### WP0：规范、目录与实验骨架

目标：建立后续所有模型共享的工程规则。

任务：

- 定义实验 `manifest`：代码版本、配置摘要、种子、模型版本。
- 定义事件记录和 artifact 目录规则。
- 建立架构决策记录目录 `docs/决策记录/`。
- 建立层级配置、实验配置和输出配置的边界。
- 保留当前五层契约演示器和 STEN smoke 基线。

交付：manifest schema、实验 ID、空实验目录结构、首份架构决策记录。

验收：相同输入产生相同实验 ID；原始 artifact 不需要 UI 即可读取。

### WP1：五层 DTO 与接口

目标：把当前单文件演示器拆为可替换但不跳层的正式契约。

任务：

- 定义 `TranscriptState`、`MolecularState`、`CellState/CellAction`、`TissueState`、`OrganismState`。
- 为每个状态加入逻辑时间、模型版本和来源摘要。
- 定义 `GenomeModel`、`MolecularModel`、`CellModel`、`TissueModel`、`PhenotypeModel` Protocol。
- 建立层间转换事件。
- 测试 L2 无法直接消费 L0 对象等错误依赖。

交付：`src/mgba/layers/` 与契约测试。

验收：替换任意一层参考实现时，其他层和实验输入不变。

### WP2：L0 小型调控网络

目标：让 L0 从静态 traits 升级为具有时间和调控关系的模型。

建议第一版包含 5–8 个抽象变量：损伤感知、信号表达、修复程序、代谢支持、死亡程序和负反馈。正式名称与关系在实现前通过决策记录冻结。

任务：

- 定义有向激活/抑制关系和表达衰减。
- 选择离散更新或简单连续更新；保留选择理由。
- 实现损伤输入、敲低和过表达。
- 保存每步表达状态和扰动事件。
- 测试边界、稳定性、确定性和剂量响应。

交付：L0 reference model、配置和独立轨迹测试。

验收：无扰动时能达到或接近可解释稳态；敲低只直接修改 L0，后续影响必须通过 L1 传播。

### WP3：L1 粗粒度分子层

目标：建立从表达状态到细胞能力的显式转换层。

任务：

- 定义受体/信号、修复、代谢和死亡相关分子状态。
- 实现表达、降解、激活/失活等粗粒度转换。
- 明确每个 L1 状态依赖哪些 L0 输出。
- 加入局部信号反馈入口，但第一版可关闭。
- 对映射关系做单调性和边界测试。

交付：L1 reference model、转换说明和测试。

验收：L0 扰动先改变 L1，再影响 L2；删除 L1 转换时契约测试失败。

### WP4：L2 Cell 状态机

目标：让多个 Cell 根据分子能力和局部环境独立行动。

第一版状态候选：静息、激活、修复、应激、死亡。状态集合在实现前冻结，不为展示任意增加状态。

任务：

- 定义局部感知输入和 CellAction。
- 实现状态转换、分泌、资源消耗、修复和死亡规则。
- 保证 Cell 不读取全局 L4 状态和其他 Cell 内部状态。
- 建立单 Cell 行为测试和多 Cell 独立性测试。
- 保留规则状态机作为未来 ML/LLM 的永久基线。

交付：L2 reference model、状态转换图和测试。

验收：同一 L1 状态在不同局部环境下可产生不同 L2 行为；所有动作可追溯到局部输入。

### WP5：L3 组织与微环境

目标：让多个局部 Cell 的动作形成组织级动力学。

任务：

- 建立静态邻域图基线和简单局部环境状态。
- 聚合分泌、资源消耗、损伤和修复作用。
- 更新 Cell 的下一步局部环境。
- 记录组织连通性、空间/图分群和局部场统计。
- 现有 STEN 继续作为独立 smoke，不在此阶段强制启用动态拓扑。

交付：L3 reference model、组织快照和测试。

验收：改变 CellAction 分布会改变 TissueState；L3 不直接读取 L0/L1 内部状态。

### WP6：L4 宏观表型

目标：从组织状态生成整体表型，而非预写结论。

任务：

- 冻结活力、损伤/炎症、稳态和恢复能力的计算定义。
- 每个指标只依赖 L3 正式输出。
- 区分即时指标、时间窗口指标和最终结局。
- 为极端组织状态建立边界测试。

交付：L4 reference model、指标卡和测试。

验收：指标公式在实验前冻结；L4 不向 L2 直接写入行为。

### WP7：多速率 CrossScaleRunner

目标：把五层从单次映射升级为时间演化系统。

任务：

- 定义各层更新频率和稳定执行顺序。
- 实现逻辑时间、检查点、暂停和恢复。
- 输出逐步 trace、层间事件和最终摘要。
- 验证相同 manifest 的位级或容差级复现。
- 为每步设置最大事件和资源预算。

交付：正式 runner、CLI、可回放 artifact。

验收：连续运行至少 100 个参考 tick；同一 manifest 结果一致；任意层失败能定位到具体转换。

### WP8：扰动、消融与因果路径

目标：从“系统能跑”升级为“系统能回答问题”。

任务：

- E0：验证每步 L0–L4 完整性。
- E1：运行多强度 L0 敲低/过表达。
- E2：冻结或替换 L1、L2、L3 中的一个层级。
- 计算每层效应量、传播延迟和最终 L4 差异。
- 保存负面结果和无效扰动。

交付：冻结的实验配置、原始数据和路径分析。

验收：至少一个扰动和一个层级消融完成多种子运行；结论可以追溯到实验 ID。

### WP9：统计与最小可视化

目标：让结果可检查、可比较，而不是只做演示动画。

任务：

- 输出各层时间序列、效应量和种子间分布。
- 生成 L0→L4 扰动传播图和层级消融图。
- 建立只读 artifact 的最小页面或 Notebook。
- 图表必须能够由原始数据一键重建。

交付：结果表、图表脚本和最小观察界面。

验收：删除生成图后可由命令重新生成；UI 不参与核心计算。

### WP10：交付冻结

目标：形成可用于课程展示、后续研究和申请材料的稳定版本。

任务：

- 完成中文设计报告和第一版英文技术报告。
- 清理安装流程、示例配置和限制说明。
- 冻结演示脚本和 fallback。
- 进行空环境复现。
- 标记版本并保留下一阶段候选想法，不临时塞入新功能。

交付：MVP release、研究报告、演示和复现记录。

验收：新用户只按 README 能运行基线、扰动和测试；所有数字可追溯。

## 6. 每周安排

| 周 | 主任务 | 本周必须留下的 artifact |
|---|---|---|
| 1 | WP0、WP1 设计 | manifest 草案、DTO、首份决策记录 |
| 2 | WP1 实现 | 层间契约与失败测试 |
| 3 | WP2 调控模型设计 | L0 假设、调控图、更新规则 |
| 4 | WP2 实现与验证 | L0 稳态/扰动轨迹 |
| 5 | WP3 | L0→L1 映射与测试 |
| 6 | WP4 状态机设计 | 状态转换图、局部输入定义 |
| 7 | WP4 实现 | 单 Cell 与异质 Cell 测试 |
| 8 | WP5 基线 | 静态组织图和环境更新 |
| 9 | WP5 完成 | 多 Cell 组织轨迹 |
| 10 | WP6 | 指标卡、L3→L4 测试 |
| 11 | WP7 | 100 tick 五层 trace |
| 12 | WP7 复现与恢复 | manifest、摘要、检查点 |
| 13 | WP8 E0/E1 | 多强度扰动原始数据 |
| 14 | WP8 E2 | 层级消融和路径分析 |
| 15 | WP9 | 可重建图表与观察界面 |
| 16 | WP10 | release、报告、演示、复现记录 |

## 7. 每周工作节奏

每周按一个小闭环推进：

1. **学习**：理解本周模型所需的最低理论。
2. **设计**：写下假设、接口、替代方案和失败标准。
3. **实现**：让 Agent 协助最小实现，不增加本周范围外功能。
4. **验证**：运行测试和一个可观察实验。
5. **复盘**：记录学到了什么、结果是否支持假设、是否回退。

每周必须留下代码以外的证据，例如决策记录、实验 artifact、图表或失败说明。

## 8. 质量门禁

### Gate A：层级真实性

- 每层有独立状态和计算职责。
- 无跳层读取。
- 占位模型显式标记。

### Gate B：可复现性

- 显式种子和 manifest。
- 原始事件与状态可回放。
- 同一参考实验摘要稳定。

### Gate C：可证伪性

- 每个主张有对照组和失败条件。
- 负面结果不删除。
- 指标在批量实验前冻结。

### Gate D：用户知识所有权

- 用户能够解释每层模型、公式和局限。
- AI 生成的关键实现经过人工阅读和测试。
- 不把无法答辩的复杂模型纳入核心路径。

## 9. 降级方案

如果进度落后，按以下顺序降级，不能删除层级：

1. 保留五层，减少每层状态变量数量。
2. 保留时间演化，减少 Cell 数和运行 tick。
3. 保留静态组织图，推迟 STEN 动态拓扑。
4. 保留规则 Cell，推迟 ML/LLM Policy。
5. 保留 CLI 和图表，推迟 Web/3D UI。
6. 保留 E0–E2，推迟反馈与涌现实验。

不允许通过合并 L0/L1、让 L2 直接读取 L0 或让 L4 直接控制 Cell 来赶进度。

## 10. 最初启动任务（已完成）

1. 冻结五层 DTO 的最小字段和命名。
2. 决定每层第一版 Protocol，不实现复杂模型。
3. 定义 manifest、实验 ID 和 layer-transition event。
4. 把当前 `multiscale.py` 拆分计划写入首份架构决策记录。
5. 为“禁止跳层”和“所有层必须出现”先写失败测试。
6. 第一周结束时评审接口，再进入 L0 调控模型设计。

## 11. 当前执行状态

> 更新日期：2026-08-18

- WP0 已完成第一版：确定性 manifest/实验 ID、artifact 目录与追加事件协议已经实现并测试。
- WP1 已完成第一版：五层不可变 DTO、模型 Protocol、`CellAction` 和四条相邻转换事件已经实现。
- `ReferenceCrossScaleRunner` 已改为层模型注入；替换 L1 的契约测试不会改变场景和其他接口。
- E0 的早期门禁已建立：缺层、乱序、非相邻转换以及 L2 直接消费 L0 都会失败。
- 当前科学等级仍是 `contract demonstrator`；L0–L3 reference model 的逐层升级不会自动提高整个五层系统的科学等级。

### WP2 更新

- 六个抽象调控变量、13 条有向边、同步泄漏方程和持续硬钳制语义已由 ADR-0002 冻结。
- L0 reference model、独立 JSON 配置、逐 tick `TranscriptState` 和 `L0PerturbationEvent` 已实现。
- 参考轨迹通过确定性、值域、200 tick 稳定性、损伤剂量方向、非法配置和配置指纹测试。
- 默认 `mgba run` 已使用离散 GRN；静态 L0 仍保留为契约回归基线。
- WP2 第一版完成。

冻结依据见 [ADR-0001：WP0–WP1 基础契约](../决策记录/ADR-0001-WP0-WP1-基础契约.md)。
L0 模型依据见 [ADR-0002：L0 第一版离散 GRN](../决策记录/ADR-0002-L0-离散GRN.md)。

### WP3 更新

- 六类粗粒度分子状态、翻译/降解方程、受体门控和反馈抑制机制已由 ADR-0003 冻结。
- L1 reference model、独立 JSON 配置、逐 tick `MolecularState` 和可关闭 `MolecularInput` 已实现。
- 参考轨迹通过确定性、值域、200 tick 稳定性、六条直接映射单调性、全量降解、反馈开关、非法配置和配置指纹测试。
- 默认 `mgba run` 已使用粗粒度 L1；恒等式 L1 仍保留为契约回归基线。
- 当前 Runner 的 `local_signal` 固定为 0，尚未实现 L2→L1 闭环。
- WP3 第一版完成；下一项进入 WP4 的 Cell 状态、局部输入和动作规则设计。

L1 模型依据见 [ADR-0003：L1 第一版粗粒度分子动力学](../决策记录/ADR-0003-L1-粗粒度分子动力学.md)。

### WP4 更新

- 静息、激活、修复、应激、死亡五态，局部驱动量、活力更新和动作规则已由 ADR-0004 冻结。
- L2 reference model、独立 JSON 配置、逐 tick `CellState/CellAction` 和 `LocalEnvironment` 三字段边界已实现。
- 测试覆盖确定性、值域、环境依赖、修复/应激分离、死亡吸收态、动作归零、Cell 身份隔离、非法配置和配置指纹。
- 默认 `mgba run` 已使用五态 L2；旧连续规则 L2 仍保留为契约回归基线。
- 默认场景中 L0 修复敲低会让 `cell-a` 从 `ACTIVATED` 转为 `DEAD`，并继续改变 L3/L4；这只是冻结 reference 参数下的契约结果。
- WP4 第一版完成；下一项进入 WP5 的组织图、资源、损伤、修复与邻域信号更新设计。

L2 模型依据见 [ADR-0004：L2 第一版 Cell 状态机](../决策记录/ADR-0004-L2-Cell状态机.md)。

### WP5 更新

- 固定有向图、节点级压力/资源/信号状态以及组织聚合公式已由 ADR-0005 冻结。
- L3 reference model、独立 JSON 配置、逐 tick `TissueState` 和 L3→L2 `LocalEnvironment` 转换已实现。
- 测试覆盖确定性、值域、边方向、局部资源消耗、修复/凋亡压力效应、固定拓扑、不合法图、配置指纹和下一步局部环境生成。
- 默认 `mgba run` 已使用环境动力学 L3；静态聚合 L3 仍保留为契约回归基线，STEN smoke 保持独立。
- 默认修复敲低会提高 `cell-a` 的 L3 局部压力并继续降低 L4 活力；当前 Runner 只有单次跨尺度更新，不能据此声称群体动力学或涌现。
- WP5 第一版完成后进入 WP6，先冻结只依赖 `TissueState` 的 L4 指标定义和极端状态边界。

L3 模型依据见 [ADR-0005：L3 第一版组织与微环境](../决策记录/ADR-0005-L3-组织与微环境.md)。

### WP6 更新

- 活力、损伤负担、炎症、稳态、恢复能力的即时公式，以及四类最终结局阈值已由 ADR-0006 冻结。
- 新增 `OrganismState` 扩展字段、`PhenotypeWindow`、`OrganismOutcome`、独立 L4 JSON 配置和配置指纹。
- 测试覆盖健康/失败极端状态、L3 输入方向性、描述性窗口均值、四类结局优先级、类型/时间/模型版本不变量、非法配置和配置指纹。
- 默认 `mgba run` 已使用配置驱动的 L4；旧三指标聚合器以静态 L4 基线保留。
- 默认修复敲低必须先改变 L3，再使 L4 损伤/炎症升高，活力/稳态/恢复能力降低；L4 不读取扰动配置或 L2 对象。
- WP6 第一版完成；下一项进入 WP7，将现有单 tick 契约演示升级为多速率、可检查点和可回放的连续五层轨迹。

L4 模型依据见 [ADR-0006：L4 第一版宏观表型](../决策记录/ADR-0006-L4-宏观表型.md)。

### WP7 更新

- L0 每 5 tick、L4 每 10 tick、L1/L2/L3 每 tick 的冻结顺序及暂停边界语义已由 ADR-0007 定义。
- `MultirateCrossScaleRunner` 已持续传入各层上一状态，并只通过 `MolecularInput` 和 `LocalEnvironment` 闭合 L2→L1、L3→L2 相邻反馈。
- 每 tick 保存五层正式状态、动作、局部环境、扰动事件和相邻转换事件；历史摘要使用确定性哈希链。
- JSON checkpoint 保存完整继续计算状态；13+17 tick 恢复与一次运行 30 tick 的 checkpoint、历史摘要、终点观察和窗口完全相同。
- 新增 `mgba simulate`，默认运行 100 tick，可显式读写 checkpoint 和完整 trace artifact；累计 tick、Cell 数和每 tick 事件均有预算。
- 默认 100 tick 基线：实验 ID `mgba-66654d1710f94556`，历史摘要 `7edbf3b897983ae4d24e1537bcc6b6d8850f3933adfeb6cc78b215c56d1350dc`，终点 `FAILED`，损伤负担约 `0.9839`。这是未经拟合 reference 参数产生的负面结果，不为展示静默调参。
- WP7 第一版完成；下一项进入 WP8，冻结 E0–E2 的扰动强度、层级消融、效应量和传播延迟定义，再运行批量实验。

多速率与检查点依据见 [ADR-0007：WP7 多速率五层运行器与检查点](../决策记录/ADR-0007-WP7-多速率运行器.md)。

### WP8 更新

- 3 个 repair 钳制、L1/L2/L3 静态替换、逐层平均绝对距离、L4 有向差值和首次传播 tick 已由 ADR-0008 冻结。
- `CausalExperimentRunner` 按同 seed baseline 做配对比较，E0 先验证每次运行的完整 tick 和相邻转换，再生成 E1/E2 比较。
- `mgba experiment` 已运行 7 条件 × 3 seed × 30 tick；矩阵 ID 为 `matrix-7da4137aa39d5122`。
- 21 份完整 raw run（约 9.9 MB）、manifest 和 derived summary 已保存到忽略 Git 的 `artifacts/matrix-7da4137aa39d5122/`，冲突写入会失败。
- `repair_kd_000` 在 L0–L4 均有非零效应，但终点恶化较小；0.5 中间钳制与 1.0 过表达没有形成简单单调响应，三档均仍为 `FAILED`。
- L2 静态替换产生最大 L4 效应（约 `0.4984`）并使 3 个 seed 均为 `RECOVERED`；这只说明五态 L2 累积规则是当前 baseline 崩溃的首要诊断对象。
- 三个 seed 的状态效应完全相同，因为 reference model 没有随机动力学；当前不做显著性推断。
- WP8 第一版完成；下一项进入 WP9，从冻结 raw JSON 重建表格、逐层效应图和时间序列图。

实验协议见 [ADR-0008：WP8 扰动、层级消融与模型内因果路径](../决策记录/ADR-0008-WP8-扰动消融与因果路径.md)。
实验解释见 [WP8 reference matrix 实验记录](../实验记录/WP8-reference-matrix-2026-08-18.md)。

### WP9 更新

- ADR-0009 冻结了 manifest + raw JSON 的唯一输入边界，`derived/summary.json` 不被信任。
- `mgba report --matrix-root artifacts/matrix-7da4137aa39d5122` 会重算 6 条件摘要、90 条逐层效应、90 条 L4 指标效应、630 条 L3 时序与 84 条 L4 观测。
- 报告产物是 5 份 CSV、4 张带有可访问标题/描述的 SVG、无 JavaScript/网络依赖的 `report.html` 和文件 SHA-256 manifest。
- 报告测试覆盖删除后字节级重建、忽略损坏派生 summary、损坏 raw 身份与路径逃逸时闭锁失败。
- WP9 第一版完成；下一项进入 WP10，冻结交付、报告、安装复现和演示流程。

报告协议见 [ADR-0009：WP9 可重建统计表、图表与只读报告](../决策记录/ADR-0009-WP9-可重建报告与可视化.md)。

### WP10 更新

- `pyproject.toml` 与 `mgba.__version__` 共同冻结 0.1.0 发布版本。
- 中文设计报告和英文技术报告已记录架构、实验、负面基线、科学边界和下一阶段。
- `scripts/mvp_demo.py --mode full` 会校验单 tick ID、100 tick ID/历史摘要/结局、21-run matrix ID 和 10 个报告文件；`fallback` 明确不代替 WP8/WP9 证据。
- 新 Python 3.12 venv 已从无运行依赖 wheel 安装 0.1.0，通过 60 项测试和 full demo。
- 项目所有者已于 2026-08-19 接受 E0–E2 发布范围，并授权首次 commit、`v0.1.0` tag 与 GitHub 推送。

交付协议见 [ADR-0010：WP10 MVP 交付冻结](../决策记录/ADR-0010-WP10-交付冻结.md)，空环境流程见 [MVP 0.1.0 复现说明](../复现/MVP-0.1.0-复现说明.md)。

### E4 反馈闭环更新（2026-08-20）

- 可选 L4→L3 `FeedbackPolicy` 参考控制器已由 ADR-0012 冻结：离散 PI（死区 + back-calculation 反饱和）经济通道输出资源上限，无记忆安全屏障输出压力地板；只消费正式 `OrganismState`，只输出 `FeedbackConstraint`。
- `ConstraintAwareTissueModel` 在无约束时与参考 L3 动力学逐字段等价；有约束时约束进入 L3 source digest 哈希链留痕。
- Runner 可选注入 `feedback_policy`；checkpoint 恢复通过重放 `l4_observations` 重建控制器状态，checkpoint schema 不变。13+17 tick 分段恢复与 30 tick 连续运行完全一致。
- `mgba feedback-experiment` 运行 E4 三条件（无反馈/固定反馈/状态反馈）×3 seed ×60 tick；`tests/test_frozen_identity.py` 证明无反馈条件与 0.2.0 基线位级一致。
- `scripts/synthetic_feedback_benchmark.py` 生成 4 压力档 ×12 Cell 的确定性仿真场景集并运行 E4 基准；所有合成场景当前均为 `FAILED` 负面基线，保留不调参。
- 测试总数增至 109 项（原 83 + 反馈 23 + 冻结身份 3）。

### L2 主动推理策略更新（2026-08-20）

- 可选 L2 `CellModel` 实现 `ActiveInferenceCellModel` 已由 ADR-0013 冻结：离散五相生成模型（A 似然、B 转移、C 偏好、D 先验），状态推断取内感受四元驱动的高斯后验，行动选择取预期自由能 $G(a)=\text{risk}+\text{ambiguity}$ 的确定性 argmin（$\gamma\to\infty$ 极限，无采样、无随机源）。
- AIF 与规则状态机共享驱动语义与状态簿记（活力、压力、吸收态同族方程），E2 式策略替换只隔离"决策规则"一个变量；对照矩阵构造器强制两 runner 仅 L2 版本不同。
- `mgba policy-experiment` 运行规则 vs 主动推理 ×3 seed ×30 tick；默认演示场景上 L0/L1 效应为零（L1 仅经相邻 L2→L1 `local_signal` 反馈出现 <1e-6 差异），L2→L3→L4 传播成立。
- `scripts/synthetic_policy_benchmark.py` 复用反馈基准仿真数据集运行策略对照；AIF 在 calm/injury 档稳态略高、炎症略低，但两策略全部合成场景均 `FAILED`，保留为负面基线，不调参。
- 测试总数增至 127 项（109 + 主动推理 18）。

### E5 动态拓扑更新（2026-08-20）

- 可选 L3 `TissueModel` 实现 `DynamicTopologyTissueModel` 已由 ADR-0014 冻结：每节点按局部应激/分泌信息提出至多一个 T1 式边交换（丢最高应激入边、加最高分泌候选），系统侧授权（无自环/重复边/死亡端点、出度上限 $\Delta_{\max}$、边际增益 $\ge\theta$），每 tick 全局预算 $B$，cell id 字典序确定性处理。
- 拓扑状态寄宿在 `TissueState.edges`：`step` 的 `edges` 参数仅为首 tick 种子拓扑，后续以 `previous_state.edges` 为准；checkpoint 精确恢复，schema 不变。`_validated_inputs` 新增 `dynamic_topology=False` 旗标，默认静态门禁位级不变。
- `mgba topology-experiment` 运行静态 vs 动态 ×3 seed ×30 tick，构造器强制两 runner 仅 L3 版本不同；`TopologyStability` 记录提交交换数、交换 tick 数与边数差。
- `scripts/synthetic_topology_benchmark.py` 复用共享仿真数据集运行 E5 对照：冻结阈值下默认场景零提交、合成 calm 档每 seed 恰好 1 次确定性交换；所有场景两条件均 `FAILED`，保留为负面基线，不调参。
- 测试总数增至 142 项（127 + 拓扑 15）。

### E3 群体统计与转录噪声更新（2026-08-20）

- 可选 L0 `GenomeModel` 实现 `NoisyDiscreteGrnModel` 已由 ADR-0015 冻结：确定性泄漏更新右端与参考 GRN 逐位相同，扰动前对每个基因值叠加有界乘性噪声 $x_i'=\mathrm{clamp}(x_i(1+\sigma_\eta u_i),0,1)$，$u_i\sim\mathcal{U}[-1,1]$；噪声流由 $\mathrm{sha256}(\text{seed}\|c\|t)$ 派生，无状态、checkpoint 精确恢复、逐 tick 哈希链留痕。`noise_sigma=0` 时基因值与确定性基线逐位一致。
- `mgba.e3_statistics` 实现 W14/M9 预注册判据：变异系数稳定性、微观驱动 OLS 解耦（$1-R^2$）、持续性；分级阶梯 insufficient_seeds / no_pattern / emergence_candidate / group_dynamics / aggregation，阈值全部在配置中预注册。
- `mgba e3-experiment` 运行 5 seed ×30 tick 噪声集合；默认演示场景打破简并（5 个不同实验 ID），分级结果为 no_pattern（死亡吸收态）与 group_dynamics（与微观驱动耦合）——诚实的 reference-model 诊断。
- `scripts/synthetic_e3_benchmark.py` 复用共享仿真数据集运行 E3 基准：calm 档 tissue_damage 与 inflammation 命中预注册 emergence_candidate 判据（$\mathrm{CV}\le0.05$、解耦 $\ge0.5$、持续性 $\ge0.6$）；按 AGENTS §4，这只达到 emergence candidate 级别，validated result 仍需冻结协议、统计检验与层级消融。
- 测试总数增至 158 项（142 + 噪声/E3 16）。

### E4×E3 随机闭环更新（2026-08-20）

- 随机闭环矩阵已由 ADR-0016 冻结：三条件（噪声开环 / 噪声闭环 / 确定性闭环）配对运行，闭环两条件仅差 L0 噪声；复用 ADR-0012 控制器与 ADR-0015 噪声模型，复用 WP8 配对比较指标。
- 预注册稳定性分级（每 run 的慢时钟 homeostasis 观测序列 $h_1..h_K$）：一阶差分变号数 $\phi$、振幅 $s=\mathrm{std}(h)$、趋势 $\Delta=h_K-h_1$；阶梯为 insufficient_observations / oscillation / lock / recovery / deterioration / indeterminate，阈值冻结在 `configs/experiments/closed_loop_stochastic.json`。
- `mgba closed-loop-experiment` 与 `scripts/synthetic_closed_loop_benchmark.py` 可执行；默认演示场景 5 seed 全部判为 `deterioration`（噪声开环 1 次变号 vs 闭环 0 次），合成基准 48 行全部分布在 deterioration/indeterminate/lock——E4 问题在噪声下得到诚实的负面测量，未调参。
- 测试总数增至 169 项（158 + 闭环 11）。

### 分层异构神经网络更新（2026-08-20）

- 冻结权重契约演示器已由 ADR-0017 冻结：`mgba.neural` 纯标准库基元（$\mathrm{sha256}(seed\|salt\|i\|j)$ 逐元素派生的 Xavier 式 `seeded_matrix`、溢出安全的 `mlp_forward`（hidden tanh / 输出 sigmoid）、入邻均值 `message_passing_step`），无全局随机状态、无训练循环。
- 可选 L0 `GenomeModel` 实现 `NeuralGrnModel`：输入 $u=(x(t-1),g,d)\in[0,1]^{13}$，目标 $y=\sigma(W_2\tanh(W_1u))$，自然更新沿用参考族 $x_i(t)=(1-\lambda)x_i(t-1)+\lambda y_i$；扰动硬钳制仍在 MLP 之后精确生效，config 进入 L0 source digest 哈希链。
- 可选 L3 `TissueModel` 实现 `GnnTissueModel`：节点特征为上一步节点 3 字段 + 当前动作 3 字段，$h_i=\sigma(W_{self}x_i+W_{neigh}m_i+b)$ 写回 $(stress, resource\_level, signal)$；聚合复用冻结公式，`tissue_damage` 沿用 ADR-0005 的 0.6/0.4 权重；非空约束显式抛错（不进入 E4 闭环），拓扑从不被修改。
- `mgba neural-experiment --layer l0|l3` 与 `mgba.neural_experiments` 实现 E2 式单层替换配对对照，构造器强制两 runner 仅在 swapped 层不同；`scripts/synthetic_neural_benchmark.py` 复用共享数据集生成器运行两组矩阵（合成基准 48 行：4 场景 × 2 层 × 2 条件 × 3 seed）。
- 科学边界：两个变体是 `contract demonstrator`（AGENTS §4 第 1 级），权重由显式种子派生而非训练，不宣称神经真实拟合或算力收益；CNN 用于 L1 被否决（无空间/序列轴，归纳偏置不符）。
- 测试总数增至 191 项（169 + 神经 22）。

### L2 规则参数标定更新（2026-08-21）

- 预注册确定性标定已由 ADR-0018 冻结：`mgba.calibration` 纯搜索核心（不 import runner；目标函数注入式），采样 $\mathrm{Random}(\mathrm{sha256}(seed\|\text{candidate}\|k)[:8])$ 逐候选均匀抽取 $[0,1)^{19}$，坐标细化（声明序 × 步长 0.1/0.05 × 双向，接受阈值 $10^{-12}$，重复点去重）；参考向量恒为首个评估点并进入细化种子，训练结果不可能差于参考。
- 协议：搜索空间为 `CellConfig` 19 个标量（`model_version` 与分泌乘子冻结）；目标为演示场景 60-tick 的 `mean_homeostasis`；预算 512 候选 + top-3 细化；holdout 为 `data/synthetic-feedback` 四档压力场景；判定规则先验固定（四档差值全正 `generalized` / 全非正 `not-generalized` / 其余 `mixed`）。
- 首次运行（search_digest `99ce6e355b8e0afa…`，1003 次评估，178 s）：训练 0.2076→0.5927（+0.385）；holdout 平均 +0.2207，判定 `generalized`——calm/injury 结局 `failed → stable`，severe/collapse 仍 `failed` 但终末活力脱离 0。多个坐标顶到 $[0,1]$ 盒边（`repair_recovery_rate`=1.0、`signal_activation_weight`=0.0 等），提示类内最优点可能在盒外；扩盒需新一轮预注册协议。
- 边界：reference model 类内诊断，非生物拟合；标定配置只写入 artifact（带溯源），不进入任何冻结实验协议；冻结基线位级不变（测试门禁固定）。
- 测试总数增至 204 项（191 + 标定 13）。
