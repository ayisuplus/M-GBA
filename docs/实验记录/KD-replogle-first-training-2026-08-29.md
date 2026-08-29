# KD 语义扩展首次实验记录（ADR-0039）：负面结果

- 日期：2026-08-29
- 契约：`docs/决策记录/ADR-0039-KD语义扩展契约.md`（计算前预注册）
- 数据：B2 `ReplogleWeissman2022_K562_essential.h5ad`（310,385 细胞 × 8,563 基因 dense 原始计数；control 10,691；≥50 细胞单元 1,832）
- Profile：`replogle-kd-perturbation-profile-5eeb02e1124fcbad`（train 1465 / holdout 367）
- 评估：`l0-training-eval-257b37036f010055`（已登记 registry）
- 模型级别：`reference model`；**verdict：failed（冻结规则）**

## 1. 管线

与 ADR-0036–0038 同构：`scripts/aivc_replogle_empirical.py`（dense X 实证段，1,832 单元 × 2,377 桥基因）→ 核心聚合（同桥、同归一化、digest 拆分、train-only 质心）→ ADR-0037 冻结超参训练（CPU 单线程、种子 42、3000 epoch）→ 核心核验段判定。桥在 8,563 基因宇宙上的节点覆盖 190/161/133/304/85/38（负反馈最弱，延续已标注缺口）。

## 2. 结果（冻结通过规则）

| 预测器 | holdout MAE | 方向一致率 | Spearman |
|---|---:|---:|---:|
| centroid | 0.014821 | 0.627 | 0.325 |
| ridge | 0.014418 | 0.000 | 0.000 |
| MLP | 0.014813 | 0.627 | 0.325 |

- margin_vs_centroid = **+0.000007**（>1e-12，勉强通过质心一侧）
- margin_vs_ridge = **−0.000396**（不优于 ridge）→ **verdict：failed**
- 按 ADR-0039 §4：不生成 KD 响应表、不进入链路配对实验；负面结果原样登记。

## 3. 失败分析（描述性，不改协议的理由）

- **单样本单坐标问题**：1,832 个单元绝大多数只出现一次（one-hot 每单元独占一维），身份编码不携带任何跨单元共享结构——模型对未见单元只能回到近质心预测。这与 Norman 数据集（105 个成分基因 + 组合共享成分）形成结构性对照：OE 臂可学正是因为组合扰动共享了成分坐标。
- **ridge 退化**：无截距闭式解在独占坐标上对 holdout 输出近零向量（方向一致率 0.000、Spearman 0.000），MAE 略优于质心纯属向零收缩的假象。
- **MLP 与质心同分**（sign 0.627、Spearman 0.325 完全一致）：MLP 学到的输出非常接近"质心 + 微小单元偏差"，说明身份特征本身没有提供可泛化信息。
- 结论：要给 KD 响应提供可学结构，需要**基因级特征**（如 Geneformer 嵌入——C1 已到位）作为输入而不是纯身份 one-hot。这是后续 ADR 的候选方向，不是本次协议内的调整。

## 4. 协议守卫记录

- ADR-0037 训练脚本 split 回执原硬编码模块常量 salt，已修正为随 profile 携带（实现偏差修复，不改变任何已产 artifact：Norman salt 恰等于该常量）。
- `profile_id` 前缀按 dataset 定键，Norman Stage 1 身份逐位不变（重建逐字节一致已验证）。
- 核心装载器新增 dataset_id 白名单 + 按数据集冻结参数集（Norman 参数集不变；B2 为 `none-filtered-release`）。

## 5. 下一步

- 候选 ADR：以 C1 Geneformer 嵌入作为扰动基因特征重训 KD 响应（新协议、新通过规则，须另行预注册）。
- A3 GEO 原生矩阵已到位：Norman 管线的端到端交叉校验可随时做。
- OE 链路（ADR-0038 已验证）可扩展至多单元/组合调度（ADR-0029 schedule 复用）。
