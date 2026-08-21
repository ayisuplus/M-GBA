# CAR-M 因果空间 L3 首次配对实验记录

- 日期：2026-08-21
- 协议：`configs/experiments/carm_spatial_comparison.json`
- 空间配置：`configs/layers/l3_carm_spatial.json`
- 场景：`configs/scenarios/carm/high_immune_her2.json`
- 矩阵 ID：`carm-spatial-0f88408d1e44b25a`
- Artifact：`artifacts/carm-spatial/carm-spatial-0f88408d1e44b25a/`
- 模型级别：`reference model`

## 1. 预注册比较

比较两个 runner：

- `fixed_graph`：冻结 CAR-M 固定图 `CarmTissueModel`；
- `spatial_field`：`SpatialCarmTissueModel`，显式坐标、三通道网格与空间邻域。

两个 runner 的 L0、L1、L2、L4、时钟、场景和 cohort profile 相同，构造门禁确认只改变 L3 模型版本。每个条件运行 20 tick，scenario seed 为 41、42、43。

## 2. 结果

三个 seed 得到相同数值：

| 指标 | 空间条件相对固定图 |
|---|---:|
| L0 终末距离 | 0.000000 |
| L1 终末距离 | 0.000117 |
| L2 终末距离 | 0.041974 |
| L3 终末距离 | 0.059804 |
| L4 终末距离 | 0.054401 |
| vitality 差值 | +0.082359 |
| damage_burden 差值 | -0.065809 |
| inflammation 差值 | -0.035882 |
| homeostasis 差值 | +0.047826 |
| recovery_capacity 差值 | +0.040130 |

首次差异 tick：L3=1、L4=1、L2=2、L1=3；L0 始终无差异。这符合当前相邻反馈路径：空间 L3 先改变局部环境，下一 tick 影响 L2，再经 L2→L1 的正式入口影响 L1，没有跳层回写 L0。

20 tick 时两个条件均为 `RECOVERED`，所以本实验没有改变冻结结局类别，只改变了连续 L4 代理值。

空间运行的诊断指标：

| 指标 | 值 |
|---|---:|
| 初末平均位移 | 0.022272 |
| 平均逐 tick 边周转率 | 0.017923 |
| 终末三通道场异质性 | 0.071050 |
| 终末邻格梯度 | 0.036441 |

这些量均在无量纲单位方形/网格上计算。

## 3. 解释边界

当前 L4 差值方向在模型内部看似更有利，但不能称为疗效改善或空间模型更真实：

- 坐标、移动、混合和源汇系数没有真实空间数据标定；
- 固定图 vs 空间条件同时改变了 L3 内的坐标、场和邻域三个机制，尚未做 L3 内部逐项消融；
- TCGA 聚合 profile 没有空间真值；
- 两个条件在 20 tick 的结局类别相同；
- scenario seed 没有进入当前确定性空间动力学，三个 seed 只是复现门禁，不是独立随机重复，不能计算统计显著性。

因此目前只能得出：**显式、可 checkpoint 的空间 L3 在当前 reference model 中产生了可追踪的跨尺度差异。**

## 4. 下一步

1. 在不改变 L0/L1/L2/L4 的前提下，预注册 L3 内部消融：仅空间邻域、仅三通道场、完整空间模型。
2. 为坐标分布、邻域尺度和场异质性寻找可授权的空间组学或成像聚合统计锚点；先登记数据来源、许可、磁盘预算和 holdout 判据，再下载或标定。
3. 只有引入显式随机过程后才把多个 seed 当作统计重复；随机状态仍必须由显式 seed 派生并可 checkpoint 精确恢复。
4. 观察台若接入该空间轨迹，必须直接读取 `SpatialTissueState`，并与 ADR-0022 的显示投影清晰区分。
