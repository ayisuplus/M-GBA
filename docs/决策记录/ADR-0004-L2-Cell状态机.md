# ADR-0004：L2 第一版 Cell 状态机

> 状态：已接受  
> 日期：2026-08-18  
> 作用范围：WP4 L2 Cell reference model

## 背景与研究问题

当前 L2 只用单次公式计算激活、存活和分泌，没有离散细胞状态、上一时刻状态或明确动作语义。WP4 要回答：

> 同一组粗粒度分子能力在不同局部环境下，能否通过可审计状态转换形成不同的 Cell 状态与动作，同时保持 Cell 只使用局部信息？

本工作包只升级 L2。L0、L1 与 L3–L4 基线保持不变。Cell 是虚拟局部单元，不对应真实细胞系、疾病机制或治疗反应。

## 正式输入

Cell 每个 tick 只能接收：

1. 本 Cell 的 `MolecularState`；
2. 本 Cell 的 `LocalEnvironment`；
3. 本 Cell 的上一 `CellState`，首步可为空。

`LocalEnvironment` 第一版固定三个 `[0,1]` 字段：

| 字段 | 含义 |
|---|---|
| `stress` | 局部损伤/压力水平 |
| `resource_level` | 局部可用资源 |
| `incoming_signal` | 邻域传入的归一化信号 |

Cell 不得读取其他 Cell 内部状态、全局 Tissue、L4 指标或 L0 转录值。

## 五个离散状态

`CellPhase` 固定为：

- `QUIESCENT`：静息；
- `ACTIVATED`：激活并主要执行信号分泌；
- `REPAIRING`：在资源允许时执行修复；
- `STRESSED`：压力较高但修复驱动不足；
- `DEAD`：死亡吸收态，后续不能被同一 reference model 复活。

`CellState` 同时保存连续的 `activation`、`viability` 和 `stress_load`，用于解释为什么发生状态转换，而不是只保留一个标签。

## 局部驱动量

```text
stress_load
  = clamp(
      0.7 * stress
      + 0.3 * (1 - resource_level)
      + 0.2 * death_effector
      - 0.2 * metabolic_capacity,
      0, 1
    )

activation_drive
  = clamp(
      0.7 * signal_protein
      + 0.3 * incoming_signal,
      0, 1
    )

repair_drive
  = clamp(
      repair_protein * stress_load * resource_level,
      0, 1
    )

death_drive
  = clamp(
      0.6 * death_effector
      + 0.4 * stress_load * (1 - metabolic_capacity),
      0, 1
    )
```

## 活力更新

首步的基础活力来自 L1 能力：

```text
viability_base = 0.5 * repair_protein + 0.5 * metabolic_capacity
```

后续使用上一 `CellState.viability`。每 tick：

```text
viability(t+1)
  = clamp(
      viability_base_or_previous
      + 0.20 * repair_drive
      - 0.25 * stress_load
      - 0.30 * death_drive,
      0, 1
    )
```

该式只是粗粒度平衡，不是细胞生存率预测。

## 状态转换顺序

转换按以下固定优先级执行：

1. 上一状态为 `DEAD`：保持 `DEAD`；
2. `viability <= 0.05` 或 `death_drive >= 0.65`：进入 `DEAD`；
3. `repair_drive >= 0.08`：进入 `REPAIRING`；
4. `stress_load >= 0.45`：进入 `STRESSED`；
5. `activation_drive >= 0.15`：进入 `ACTIVATED`；
6. 否则进入 `QUIESCENT`。

修复优先于一般应激，使“高压力但修复能力充分”和“高压力且修复不足”形成可检验对照。死亡判据始终优先。

## CellAction

`CellAction` 固定包含：

- `secretion`：信号分泌；
- `resource_consumption`：局部资源消耗；
- `repair_effort`：对组织的修复作用；
- `apoptosis`：是否已提交死亡动作。

分泌倍率按 phase 固定：静息 `0.05`、激活 `1.0`、修复 `0.25`、应激 `0.5`、死亡 `0`。

```text
secretion
  = phase_multiplier * activation_drive * metabolic_capacity

repair_effort
  = repair_drive       if phase == REPAIRING
  = 0                  otherwise

resource_consumption
  = clamp(
      0.05
      + 0.20 * activation_drive
      + 0.30 * repair_effort,
      0, 1
    )                  if alive
  = 0                  if DEAD
```

`apoptosis` 仅在 `DEAD` 为真。宏观修复结果不会直接写入 Cell 目标函数。

## 配置与时间

阈值、权重和动作倍率保存在独立 L2 JSON 配置中，模型版本包含配置摘要。所有更新同步读取当前 L1、局部环境和上一 L2 状态。

独立 L2 轨迹从 `previous_state=None` 开始。当前五层 Runner 只推进一个 L2 tick；WP7 再持续传入上一 Cell 状态。

## 验收与失败判据

1. 相同输入产生完全相同的 Cell 轨迹；所有连续量保持在 `[0,1]`；
2. 同一 `MolecularState` 在不同局部压力、资源或传入信号下产生可测的状态/动作差异；
3. 高压力且修复驱动充分时进入 `REPAIRING`，修复不足时进入 `STRESSED`；
4. 高死亡驱动或持续活力损失使 Cell 进入 `DEAD`；
5. `DEAD` 是吸收态，健康输入不能让其复活；
6. 不同 Cell 的上一状态不能互换，Cell ID 不匹配必须失败；
7. 死亡 Cell 的分泌、消耗和修复动作全部为零，`apoptosis=true`；
8. 配置缺字段、非有限参数、越界权重、非法阈值或未知 phase 必须失败；
9. 五层 Runner 中 L0 修复敲低仍先经过 L1，再改变 L2 phase/viability、L3 和 L4。

## 备选方案

1. 继续使用纯连续公式：无法表达离散状态和死亡吸收态，拒绝作为默认 L2。
2. 随机状态机：可形成种子分布，但会妨碍第一版规则调试，推迟。
3. 强化学习或 LLM Cell Policy：没有已冻结奖励、数据或对照，且会削弱可解释基线，拒绝进入 WP4。
4. 真实细胞自动机：需要空间和组织更新先稳定，留给 WP5 以后。

## 影响、局限与回退

- `CellState` 增加 `phase`、`stress_load`；`CellAction` 增加资源消耗、修复和凋亡语义。
- `CellModel` Protocol 增加上一 L2 状态。
- 旧连续公式以 `StaticCellModel` 保留，可通过依赖注入恢复。
- 当前没有增殖、移动、分裂、突变、真实细胞周期或概率死亡；不得声称真实细胞行为或涌现。
