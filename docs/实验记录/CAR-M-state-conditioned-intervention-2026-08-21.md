# CAR-M 状态条件序列干预首次实验记录

- 日期：2026-08-21
- 协议：ADR-0029
- 命令：`mgba carm-intervention-experiment --artifact-root artifacts/carm-state-conditioned-intervention`
- artifact：`artifacts/carm-state-conditioned-intervention/state-intervention-0e92bb234ba3a840/`
- 条件：baseline、early_short、late_short、early_long、late_long
- 规模：5 条件 × 3 seed × 60 tick = 15 raw runs
- 目标：15 个 engineered macrophage 的抽象 L0 `signal_expression=1.0`

## 门禁

- schedule 只落在 L0 update ticks；
- late 条件在 tick 31 前相对 baseline 的所有可观察层距离均为 0；
- 每次 scheduled tick 均产生正式 L0 perturbation event；
- 相同完整 schedule 的 6+6 checkpoint 恢复与 12-tick one-shot history/checkpoint 精确相同；
- 三个 seed 数值相同，明确只作确定性复现，不作样本量或显著性解释。

## 结果

| 条件 | L0 effect | L1 effect | L2 effect | L3 effect | L4 effect | vitality Δ | damage Δ | inflammation Δ | homeostasis Δ | outcome |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| early_short | 0.003065 | 0.002552 | 0.020053 | 0.008627 | 0.019804 | -0.043120 | +0.009139 | +0.004058 | -0.020622 | RECOVERED |
| late_short | 0.022276 | 0.017085 | 0.012678 | 0.020114 | 0.016719 | -0.031951 | +0.005261 | +0.012797 | -0.018217 | RECOVERED |
| early_long | 0.008889 | 0.006997 | 0.027559 | 0.013784 | 0.031684 | -0.068369 | +0.014125 | +0.007705 | -0.033077 | RECOVERED |
| late_long | 0.053620 | 0.038726 | 0.086848 | 0.042715 | 0.025330 | -0.036326 | +0.005365 | +0.044066 | -0.029567 | RECOVERED |

short timing contrast terminal L4 distance = 0.006580；long timing contrast = 0.020899。晚期干预表现出较小的 vitality/damage 代价，同时具有更高的 inflammation，属于明确的 trade-off，不是“更优时机”。

## 结论等级

`reference model` 内的 state-conditioned group dynamics 诊断。它证明协议能区分相同干预在不同轨迹状态中的后果，并保留相邻层传播证据；不证明真实细胞状态依赖、疗效或 AIDO 模型能力。下一步需要真实 Perturb-seq target，而不是继续调 reference rules。
