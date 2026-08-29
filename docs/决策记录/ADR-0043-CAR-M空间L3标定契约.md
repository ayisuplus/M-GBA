# ADR-0043：CAR-M 空间 L3 calibration 子集参数选择契约

- 状态：契约已接受（2026-08-29，搜索前预注册）
- 日期：2026-08-29
- 影响范围：生成链外 L3 参数选择评估；产物落 `artifacts/carm-spatial-calibration/`
- 不影响：ADR-0023 空间 reference 模型默认身份、固定图 CAR-M 冻结矩阵、全部既有基线；标定结果**不**自动进入任何配置

## 1. 背景与准入

ADR-0027 首次真实同指标评估记为"未锚定"（calibration 均 NAE 10.3478、holdout 12.1461、场指标全部落在观测分布外）。ADR-0025 §4.3 预注册了唯一的合规回应：只在 calibration 子集选有限个 L3 参数，holdout 一次确认，Jackson external validation 不参与拟合，不改善则保留"未锚定"。本 ADR 冻结这次选择的参数、界、目标、搜索预算与确认规则。六问：L3 层外参数诊断（不改层模型）；替换对象无（reference 原样保留）；研究问题为"当前空间 reference rules 的参数能否逼近真实场统计"；指标为冻结的 24 指标空间的角色均 NAE；失败即保留负面结果；搜索全程确定性可复放。

## 2. 冻结搜索定义

- **参数**（4 个，对应 ADR-0024 审计定位的杠杆点）：`neighbor_radius`、`field_retention`、`field_diffusion`、`node_field_coupling`。三个 source/sink gain 固定不动（尺度不变指标不消费其自由度）。
- **界**（unit box 映射）：neighbor_radius [0.05, 0.40]（ref 0.16）；field_retention [0.50, 0.98]（ref 0.82）；field_diffusion [0.00, 0.60]（ref 0.28）；node_field_coupling [0.00, 1.00]（ref 0.35）。
- **目标函数**：最大化 −（calibration 角色 15 场指标的归一化绝对误差均值），由完整 `SpatialAnchorEvaluator` 20 tick 轨迹投影计算（`configs/experiments/carm_spatial_anchor_evaluation.json`，scenario seed 42）。
- **搜索协议**（复用 ADR-0018 纯标准库核心 `mgba.calibration.run_search`）：search_seed 20260829；candidate_count 24；top_k 4；refinement_steps (0.25, 0.125)；max_sweeps 2；**incumbent = 参考配置**（入盒逆映射），搜索结果在训练目标上不劣于 reference。
- 评估预算上限：24 + 4×(2×4×2) + 1 = 89 次，逐次留痕写入 artifact。

## 3. 冻结确认规则

搜索结束后，用最佳配置**只跑一次**完整评估（同 ADR-0027 的 39 距离链）：

- **improved**：holdout 均 NAE 严格低于参考值 12.146142329407688（margin > 1e-12）；
- **否则**：维持"未锚定"，负面结果保留，不得加参重搜。
- calibration 与 external_validation 距离完整报告但不进入判定；任何 calibration 角色上的拟合改善不构成通过证据。

## 4. 产物与边界

- `mgba carm-spatial-calibrate`：搜索 artifact（逐次评估留痕 + 最佳配置 + digest）；确认 artifact（39 距离 + verdict）。
- 最佳配置**只**写入 artifact 目录（带完整溯源），不改 `configs/layers/l3_carm_spatial.json`；若要采纳为新的 reference，需另行 ADR 与矩阵重跑。
- 边界：calibration 只在 calibration 角色上拟合；这是 24 指标空间的参数诊断，不是生物拟合、不是疗效证据；术语上限 `reference model`。

## 5. 未采用方案与回退

未采用：把 source/sink gain 纳入搜索（尺度不变指标不消费）、梯度法（非可微）、Jackson 参与拟合（角色冻结为 external validation）、holdout 反复回看调参。回退：删除 artifact 目录与校准 CLI；reference 空间模型与全部冻结实验不受影响。

## 6. 验证

测试覆盖：unit-box 映射与界外拒绝、incumbent 不劣性、目标函数接线（合成 evaluator stub 手算值）、确认规则真/假分支、write-once、CLI 往返、冻结 reference 配置不动；既有全套测试与 `mgba data-check` 绿色。
