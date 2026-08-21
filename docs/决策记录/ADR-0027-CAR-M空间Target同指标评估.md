# ADR-0027：CAR-M 空间 Target 同指标评估

- 状态：已接受并实现
- 日期：2026-08-21
- 所属层级：L3 生成链外观察与评估
- 关联：ADR-0026、ADR-0025、ADR-0023

## 1. 问题

ADR-0026 可以从真实 observation bundle 生成去标识 target，但 ADR-0023 的空间 reference model 仍只报告位移、边周转、平均场异质性和平均梯度。如果 target 和模型使用不同统计语言，真实数据到达后仍需人工挑选图表，无法执行冻结的 calibration/holdout 门禁。

因此需要一个只读投影：把正式 `SpatialTissueState` 映射到与外部 target 完全相同的 15 个 field 和 9 个 neighborhood 指标，再用预注册的描述性距离评分。

## 2. 决策

### 2.1 模型状态投影

`project_spatial_tissue_state` 只读取：

- `SpatialTissueState.field_cells`、grid 大小与 metadata；
- `SpatialTissueState.coordinates`；
- CAR-M 场景正式 `CellRole` 映射；
- ADR-0026 的冻结协议。

Field grid cell 中心归一化到单位方形，三通道直接使用 dimensionless stress/resource/signal。为了对应外部病理区域方差指标，模型 grid 按“到最近 tumor Cell 的距离”分成 proximal/distal 两组，阈值固定为全部 grid 距离的 0.5 分位数；这个规则在真实 target 读取前已写入协议，不能按结果改变。

Neighborhood 投影把 engineered macrophage、wild-type macrophage 和 CD8 合并为 `immune`，tumor 保持 `tumor`；不向任何 DTO 添加类型字段。坐标通过 ADR-0026 同一最近邻/半径/邻接指标函数处理。

### 2.2 Target 距离

每个 metric/role 的描述性误差定义为：

```text
abs(model_value - target_median)
──────────────────────────────────────────────────────────────
max(target_IQR, target_population_sd, 0.05 × max(|median|, 1))
```

同时报告模型值是否位于观测 sample min–max。这只是跨量纲可读的描述性距离：

- 不是假设检验、p 值或 likelihood；
- 不把不同 metric 平均值解释为生物真实性概率；
- calibration、holdout、external validation 分开汇总；
- neighborhood target 只能进入 external validation。

### 2.3 正式评估命令

`configs/experiments/carm_spatial_anchor_evaluation.json` 冻结 20 tick、scenario seed 42。命令：

```powershell
mgba carm-spatial-anchor-evaluate `
  --target <verified-target.json> `
  --artifact-root <artifact-root>
```

输出独立 append-only artifact：

```text
<evaluation-id>/
├── manifest.json
├── raw/run.json
└── derived/summary.json
```

summary 含 24 个模型投影指标、39 个 role×metric 对照，以及 calibration=15、holdout=15、external-validation=9 三组汇总。raw run 保留完整 L0→L4 trace，确保 score 可追溯回 L3 source digest，而不是只保存一张派生表。

## 3. 有效性门禁

- 输入必须是正式 `SpatialTissueState`，roles 与 coordinate ids 严格对齐；
- 模型投影必须恰好覆盖 24 个冻结 metric ID；
- 同状态投影确定性相同，时间变化会改变指标；
- target distribution 必须完整覆盖 field calibration/holdout 和 neighborhood external validation；
- 每项误差有限、scale 正、range flag 可重算；
- evaluation identity 同时包含 target、scenario、run history 与 score identity；
- artifact 保存完整 raw run，重复写入幂等、篡改后拒绝；
- 评估模块不改变 runner、L3 状态或任何模型参数。

## 4. 当前结果边界

已用 ADR-0026 的合成 fixture target 证明 24→39 指标/角色闭环、CLI 和 artifact 工作；fixture 数值没有生物含义，不保存为正式实验结果。由于 Wu/Jackson 尚未授权下载，当前没有真实 calibration/holdout 分数，不允许据此声称模型已经被外部数据验证。

## 5. 回退

删除 `spatial_anchor_evaluation.py`、评估命令/配置/测试和本文档即可回到 ADR-0026。target builder、空间 reference、固定图基线和冻结矩阵均不依赖本评估器。
