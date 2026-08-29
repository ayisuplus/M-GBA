# ADR-0041：OE 链路多单元与调度扩展契约

- 状态：契约已接受（2026-08-29，实现与运行前预注册）
- 日期：2026-08-29
- 影响范围：生成链外配对实验；产物落 `artifacts/empirical-l0-schedule/`
- 不影响：ADR-0038 冻结矩阵身份、五层契约、参考基线、核心零依赖

## 1. 背景与准入

ADR-0038 已验证单一单元（BAK1，cell-a，常量）的实证响应语义可接链并跨层传播。本 ADR 把该资产扩展到**多单元并行**、**组合扰动**与**时序调度**三个维度，复用 ADR-0029 的 manifest-bound L0 时钟调度机制。六问：L0 层内变体的实验协议扩展（不改层模型/变体）；研究问题为经验响应语义在多单元/组合/时序下的跨层传播是否与单单元一致、与硬钳制语义差异如何放大；指标复用 WP8 配对距离与传播 tick；失败保留负面结果；全部单元/映射/时序计算前冻结。

## 2. 冻结选择（实现前确定）

- **多单元映射**（train 角色 ∧ 单基因 ∧ 桥并集 ∧ 细胞数最多前三）：cell-a `BAK1`、cell-b `ETS2`、cell-c `TGFBR2`；cell-d 为旁观者（不扰动）。
- **参考臂节点**（同 ADR-0038 规则：含基因桥集最多，平手按 ABSTRACT 序）：BAK1→damage_response、ETS2→signal_expression、TGFBR2→damage_response。
- **组合单元**：`BCL2L11_BAK1`（两成分均为 train 单基因且在表内；Norman 组合）。
- **调度**：L0 慢时钟（interval 5）；scheduled 臂在 tick 16  onset（30 tick 后半段起点；早=1、晚=16 沿用 ADR-0029 early/late 形状）。
- **剂量**：全部 1.0。场景 `configs/multiscale_demo.json`，30 tick，seeds 41/42/43（确定性重放门禁）。

## 3. 条件与比较（全部冻结）

| condition_id | arm | 扰动 |
|---|---|---|
| baseline | reference | 无 |
| reference_multi_clamp | reference | 常量三节点硬钳制（cell-a damage、cell-b signal、cell-c damage → 1.0） |
| empirical_multi_constant | empirical | 常量三单元（BAK1/ETS2/TGFBR2 @1.0） |
| empirical_multi_scheduled | empirical | 同上映射，tick 16 起（schedule） |
| empirical_combo_constant | empirical | cell-a `BCL2L11_BAK1` @1.0 常量 |

比较（WP8 配对机制，同 seed 配对）：

1. reference_multi_clamp vs baseline
2. empirical_multi_constant vs baseline
3. empirical_multi_constant vs reference_multi_clamp
4. empirical_multi_scheduled vs empirical_multi_constant（时序主效应）
5. empirical_combo_constant vs baseline

身份门禁不变：empirical runner 无扰动轨迹须与参考 baseline 逐值一致；构造器强制两臂仅 L0 模型不同。

## 4. 实现与边界

- 新增**配置驱动**的调度配对 runner（条件为数据：arm + 常量/调度其一），与 ADR-0038 的三条件硬编码 runner 并存且不改其逐位行为；artifact schema `mgba-empirical-l0-schedule-0.1`，append-only。
- 语义边界不变：参考模型级语义对照；单元响应来自 K562 CRISPRa，不得外推；多单元同时扰动的叠加语义为"各自经验模式并存"（无交互项），组合单元则携带其真实组合测量值。
- 负面结果保留；任何条件结局变化都必须按既有结局审计规则记录。

## 5. 未采用方案与回退

未采用：多单元间加交互项（无数据支撑）、跨层反馈控制器联用、CAR-M 场景（需单独预注册）、改动 ADR-0038 runner。回退：删除新 runner 类与实验 artifact；ADR-0038 链路与全部冻结实验不变。

## 6. 验证

测试覆盖：条件配置校验（arm/互斥通道/未知单元拒绝）、构造器单层门禁、无扰动逐值一致门禁、五条件 × 3 seed 矩阵形状与比较序、时序臂 onset 前与常量臂逐值一致（schedule 机制不变量）、write-once、CLI 往返；既有全套测试与 `mgba data-check` 绿色。
