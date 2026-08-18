# M-GBA v0.2 CAR-M 纵向切片实施记录

> 状态：已实现并通过发布门禁
> 日期：2026-08-19
> 场景：TCGA-BRCA high immune / HER2 CAR-M

## 1. 目标

旧 CAR-M 项目作为 M-GBA 的第一个生物学场景包接入，不成为第二套运行架构。v0.2 保持 L0–L4 DTO、Protocol、参考模型和多速率 Runner 不变，只增加：

- 去标识化 TCGA 代理数据导入；
- CAR-M 场景配置、角色和固定拓扑编译；
- 实现现有 `CellModel` / `TissueModel` 协议的 L2/L3 适配器；
- 支持多个 Cell 的群体 L0 扰动；
- `carm-import` 与 `carm-experiment` 命令。

## 2. 资产迁移清单

| 旧资产 | 处理 | v0.2 位置或理由 |
|---|---|---|
| TCGA 预测 JSON | 适配迁移 | 聚合为不含 `sample_id` 的 cohort profile，保留源 SHA-256 |
| STRING 图元数据 | 适配迁移 | 只记录来源、节点数和边数，不进入热路径 |
| CAR-M / WT / Tumor / CD8 规则 | 适配迁移 | 改写为确定性期望值 L2 模型，只消费 L1 与局部 L3 环境 |
| CytokineField 局部作用 | 适配迁移 | 压缩为资源、压力和信号三个正式 L3 变量 |
| seeded RNG、空间哈希、移动、增殖 | 暂缓 | 等待随机协议和空间 L3 契约 |
| NumPy/PyTorch GAT | 暂缓 | 当前输出是患者级代理标签，不能直接作为 L1→L2 热路径 |
| React/Three.js UI | 暂缓 | 等 artifact/DTO 稳定后只读接入 |
| legacy MLP surrogate | 拒绝迁移 | 已被旧项目 GAT 路线替代且无独立科学用途 |
| CD47、MERTK 抗原预设 | 拒绝导入 | 不符合旧项目自身 `TargetAntigen` 类型；MerTK 仍可作为信号域 |
| 临床疗效与生存预测主张 | 拒绝迁移 | 代理标签与模型精度不足以支持临床结论 |

## 3. 冻结实现

- cohort profile 重新统计 752 个样本：high immune 323、low immune 273、normal 156；旧预设的 `n=45` 只作为历史字段保存。
- 首场景包含 15 个工程化巨噬细胞、10 个野生型巨噬细胞、20 个肿瘤细胞和 18 个 CD8 T 细胞。
- 工程化与野生型巨噬细胞使用同一基础 Genome 和同一 L2 公式。CAR 差异只来自对工程化 Cell 的 L0 `signal_expression` 钳制。
- L0/L1/L4 沿用 0.1 参考模型；L2/L3 使用场景适配器；固定拓扑为角色内双向环及免疫—肿瘤局部双向边。
- `tissue_damage` 在该场景中是肿瘤活力和免疫细胞损伤的冻结代理，不是临床终点。
- 多种子只保留实验协议兼容；当前仍是确定性模型，不报告统计显著性。

## 4. 冻结实验

实验为 7 条件 × 3 seed × 30 tick：baseline、`car_off_000`、`car_affinity_070`、`car_max_100`、L1/L2/L3 静态替换。三个 CAR 条件均同时作用于 15 个工程化巨噬细胞。

通过条件：

- 21 份运行和 18 份同 seed 比较完整；
- 0.7 与 1.0 剂量在 L0–L4 均产生非零可追踪差异；
- 每个消融只改变目标层模型版本；
- checkpoint 分段恢复与连续运行完全一致；
- 报告只从 manifest 与 raw run 重建。

## 5. 科学边界

v0.2 是“TCGA 代理数据锚定的机制参考模型”，不是经过校准的 CAR-M 疗效模拟。旧 GAT 的 immune infiltration 是基因签名代理标签上的预测，survival AUC 也不支持临床风险使用。任何方向性结果，包括不利结果，都原样保存，不为了演示调参。
