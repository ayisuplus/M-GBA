# ADR-0011：CAR-M 场景包与群体 L0 扰动

> 状态：Accepted
> 日期：2026-08-19

## 背景

旧 CAR-M 项目已有 TCGA/STRING 派生数据、四类细胞规则、细胞因子场、ABM 和前端。直接把旧引擎并入主干会形成与 M-GBA L0→L4 并行的第二套架构；把旧患者级 GAT 放进 L1 又会绕过 L2/L3，直接靠近宏观标签。

## 决定

1. CAR-M 作为 `mgba.scenarios.carm` 场景包存在，核心 DTO、Protocol 和 Runner 不变。
2. L0/L1/L4 保留参考实现；先把旧细胞和环境规则适配为 L2/L3 模型。
3. 工程化与野生型巨噬细胞基础规则相同，CAR 效应必须从 L0 `signal_expression` 经过 L1 进入 L2。
4. 新增独立 `GroupPerturbationCondition(targets, gene, value)`；旧 `PerturbationCondition(cell_id, gene, value)` 保持原字段和序列化，因此 v0.1 参考矩阵身份不变。
5. 患者级 GAT 结果只作为 cohort 初始化代理和外部对照。只有得到明确的层内监督目标后，才允许训练模型替换某一层参考实现。
6. v0.2 使用固定图和确定性期望值，不迁移随机移动、增殖、动态图和 UI。

## 结果

- CAR-M 获得完整相邻层 trace、checkpoint、消融和 raw-only 报告能力。
- 旧项目可以逐项迁移，而不会把 M-GBA 退化为 CAR-M 2.0。
- 场景适配器仍使用粗粒度变量；它只能作为机制参考模型。
- v0.2 不具备空间 ABM、随机统计或临床预测能力。

## 回退

删除 `mgba.scenarios.carm`、对应配置和群体条件类型即可回到 v0.1 参考能力；旧单 Cell 扰动配置和所有核心契约不依赖 CAR-M 包。
