# Geneformer 嵌入重训实验记录（ADR-0040）：两个臂均未通过

- 日期：2026-08-29
- 契约：`docs/决策记录/ADR-0040-Geneformer嵌入特征重训契约.md`（计算前预注册）
- 资源：C1 Geneformer-V2-104M_CLcancer（输入 token 嵌入纯查表，无模型前向）+ ADR-0036/0039 两个 profile
- 嵌入表：`data/aivc/derived/gene-embedding-table.json`（1,877 解析 / 56 未映射，768 维，全源 SHA-256）
- 评估：KD 臂 `l0-training-eval-d6471a14fc2f3a5d`；OE 描述臂 `l0-training-eval-03e335bca1ca8c9b`（均已登记 registry）
- 模型级别：`reference model`；**两臂 verdict：failed（冻结规则）**

## 1. 协议执行

特征 = Geneformer 输入 token 嵌入（单基因直取；组合取成分均值）。超参与 ADR-0037 逐字相同；拆分沿用各 profile 自带盐与角色（覆盖子集受限，不重切）。KD 覆盖 1,780/1,832 单元（52 个映射缺失被 fail-closed 排除并计数）；OE 覆盖 229/236。

## 2. 结果（冻结通过规则）

KD 臂（n=354 holdout）：

| 预测器 | MAE | 方向一致率 | Spearman |
|---|---:|---:|---:|
| centroid | 0.014805 | 0.627 | 0.313 |
| ridge | 0.014181 | 0.628 | 0.317 |
| MLP | 0.014212 | 0.629 | 0.315 |

margin：+0.000593（过质心）/ **−0.000030（未过 ridge）** → failed

OE 描述臂（n=46 holdout；覆盖子集使拆分成员与 ADR-0037 不同，故仅描述）：

| 预测器 | MAE | 方向一致率 | Spearman |
|---|---:|---:|---:|
| centroid | 0.012514 | 0.714 | 0.820 |
| ridge | 0.010691 | 0.808 | 0.862 |
| MLP | 0.010710 | 0.819 | 0.877 |

margin：+0.001803 / **−0.000020** → failed（描述性，不触碰 ADR-0037 的 passed 身份）

## 3. 结论（reference-model 级）

- 基因语义嵌入**修复了 ADR-0039 的结构退化**：ridge 在嵌入特征上恢复为有效基线（方向/Spearman 正常），两个学习器在两个数据集上都明确优于质心。
- 但 MLP 在两臂均不优于 ridge（margin −2e-05/−3e-05）：**该任务在 Geneformer 基因语义空间内近似线性**，当前数据规模没有可学习的非线性剩余。
- 按规则：不生成 KD 响应表、不进链路；两个负面评估原样登记。身份 one-hot（ADR-0037 OE passed / ADR-0039 KD failed）与嵌入（ADR-0040 双 failed）的对照本身即结论：OE 可学性来自组合共享成分，KD 单敲低的可学性需要更多数据或更结构化目标，而非更强特征。

## 4. 协议守卫记录

- 评估契约新增 `feature_encoding` 分派（`identity-onehot` 旧键集逐位不动；`geneformer-embedding` 新键集：嵌入表 digest/维度/覆盖数/质心漂移回执）；未知编码 fail-closed。
- 嵌入臂的质心核验改为从 profile 目标重算覆盖-训练质心（1e-12 护栏）；旧臂的全量质心交叉核验不变。
- 发现并修正训练脚本设计缺陷：不得对覆盖子集重切拆分（否则与 ADR-0039 拆分不可比）——角色一律继承 profile 冻结拆分。
- ADR-0039 记录中的"候选方向"（Geneformer 嵌入）已按本 ADR 执行并关闭；下一步若要继续，需新的数据维度（如 Tahoe 药物扰动响应），而不是再次更换特征。

## 5. 下一步候选

- A3 GEO 原生矩阵交叉校验 Stage 1（纯复核，低成本）。
- OE 链路多单元/组合调度扩展（ADR-0029 schedule 复用，已验证的 passed 资产）。
- L3 calibration 参数选择预注册（回应空间"未锚定"）。
