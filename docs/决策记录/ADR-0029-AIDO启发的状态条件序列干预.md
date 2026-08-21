# ADR-0029：AIDO 启发的状态条件序列干预协议

- 状态：已接受、实现并完成首次 reference 实验
- 日期：2026-08-21
- 所属层级：L0 干预协议 + 生成链外实验基础设施
- 关联：ADR-0007、ADR-0008、ADR-0011、ADR-0028

## 1. 外部启发与项目边界

GenBio AI 对 AIDO Virtual Cell 的公开描述强调一种任务形状：给定细胞初始状态、扰动和环境条件，预测后续状态与功能；AIDO.Cell 还把 perturbation modeling 作为主要评估任务。其后续公开材料也强调 state-conditioned perturbation、显式强基线和同一干预在不同细胞状态下可能产生不同效应。

M-GBA 借鉴的是这个**可证伪任务协议**，不是 AIDO 的品牌主张或预训练权重：

- 不引入中央潜状态跨过 L0–L4；
- 不让 L2 直接读取 L0 干预；
- 不把预期答案写进 L4；
- 不下载 AIDO.Cell 权重或增加 PyTorch 依赖；
- 固定规则、CAR-M 固定图和现有实验继续作为强基线。

## 2. 新能力准入六问

1. **属于哪一层？** 干预只进入 L0；调度、配对和评分位于生成链外。
2. **增强什么基线？** 把原先“全程恒定 clamp”扩展为可审计的 L0 慢时钟脉冲；恒定 perturbation 和所有旧 runner 身份不变。
3. **回答什么问题？** 对同一 CAR-M reference 轨迹，同剂量、同暴露次数的 signal clamp 在早期状态与晚期状态施加，L0→L4 响应是否不同？
4. **如何判断有效？** 干预前逐层距离必须 ≤1e-12；事件 tick 必须等于预注册 schedule；early/late 暴露数相同；报告终末 L4 timing contrast 和完整 raw trace。
5. **失败能否移除？** 可以；调度参数是 runner 的可选入口，未传时 manifest 与冻结身份不变；实验模块可独立删除。
6. **能否解释？** 每个脉冲都是六节点 L0 的显式硬钳制，传播路径和时钟都在 trace 中可见。

## 3. 决策

`MultirateCrossScaleRunner.run` 增加可选 `perturbation_schedule`：

- key 是绝对 logical tick，且必须对齐 L0 慢时钟；
- value 仍是 `Cell → abstract gene → [0,1] clamp`；
- schedule 与旧恒定 `perturbations` 互斥，避免语义歧义；
- 完整 schedule 进入 experiment manifest，因此 checkpoint 恢复必须使用同一调度并可精确重放；
- 未提供 schedule 时不增加 manifest 字段，冻结 identity 位级不变。

新增 `mgba.intervention_experiments` 与：

```powershell
mgba carm-intervention-experiment `
  --intervention-config configs/experiments/carm_state_conditioned_intervention.json `
  --artifact-root artifacts/carm-state-conditioned-intervention
```

冻结设计为 2×2 timing×exposure：

| 条件 | L0 update ticks | 暴露次数 |
|---|---|---:|
| early_short | 1, 6, 11 | 3 |
| late_short | 31, 36, 41 | 3 |
| early_long | 1, 6, 11, 16, 21, 26 | 6 |
| late_long | 31, 36, 41, 46, 51, 56 | 6 |

四个条件都只对 15 个 engineered macrophage 的抽象 `signal_expression` 钳制到 1.0。baseline 无干预。early/late short 与 early/late long 分别构成等暴露 timing contrast。其余 L0/L1/L2/L3/L4 模型、CAR-M 场景和 60-tick horizon 完全相同。

## 4. 首次结果

正式 artifact：`state-intervention-0e92bb234ba3a840`，5 条件 × 3 seed × 60 tick，共 15 份 raw run。所有条件结局均为 `RECOVERED`。三个 seed 的数值完全相同，因为当前 CAR-M reference dynamics 是确定性的；它们只是重放门禁，不是统计重复。

相对 baseline：

| 条件 | terminal L4 distance | vitality Δ | inflammation Δ | homeostasis Δ |
|---|---:|---:|---:|---:|
| early_short | 0.019804 | -0.043120 | +0.004058 | -0.020622 |
| late_short | 0.016719 | -0.031951 | +0.012797 | -0.018217 |
| early_long | 0.031684 | -0.068369 | +0.007705 | -0.033077 |
| late_long | 0.025330 | -0.036326 | +0.044066 | -0.029567 |

等暴露 timing contrast：

- short：early vs late terminal L4 distance = **0.006580**；
- long：early vs late terminal L4 distance = **0.020899**。

所有 late 条件在 tick 31 前与 baseline 的 L0–L4 最大距离都精确为 0。由此只能说：**在当前 reference rules 内，干预时机改变了跨层响应**。晚期施加减轻了终末 vitality 损失和 damage burden，但增加了 inflammation，尤其 long exposure。该混合/负面结果必须保留，不能包装成疗效。

## 5. 为什么这比“再加一个模拟器功能”更深一层

此前模型主要回答“某个固定规则会跑出什么轨迹”。本协议开始回答可被真实 Perturb-seq/时间序列数据否证的问题：

- 相同干预在不同基线状态下的 effect 是否可转移？
- timing effect 能否在 L0/L1 真实扰动目标上复现？
- 简单 reference baseline 与未来 AIDO.Cell/STATE oracle 谁更准确？

当前只完成了问题和实验边界，没有真实 target。因此它仍是 `reference model` 级证据，而不是 validated virtual cell。

## 6. 后续数据门槛

下一步不是调参放大 timing contrast，而是预注册 L0/L1 真实 perturbation target：

1. 选择一个许可明确、处理版可控的 Perturb-seq 数据集；
2. 冻结 control state、perturbation、dose/time、train/holdout 和简单 centroid baseline；
3. 先用透明六节点语义桥评估方向与状态依赖；
4. 只有简单基线成立且磁盘/依赖另行授权后，才评估 AIDO.Cell 或 STATE 权重。

## 7. 科学边界与回退

本结果不证明 AIDO、数字生命、临床疗效或真实细胞可编程。`signal_expression` 是抽象 L0 节点，CAR-M profile 是旧 GAT 代理聚合，所有动态仍是手工 reference rules。

回退时删除 `mgba.intervention_experiments`、CLI、配置和测试，并移除 runner 的可选 schedule 参数即可。未使用 schedule 的冻结 manifest、checkpoint、run 和矩阵身份不变。
