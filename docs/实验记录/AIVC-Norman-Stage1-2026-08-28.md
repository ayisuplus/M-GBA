# AIVC Stage 1 首次实证锚定记录（Norman Perturb-seq → 六节点）

- 日期：2026-08-28
- 契约：`docs/决策记录/ADR-0036-AIVC-Norman实证锚点契约.md`（计算前预注册）
- 数据：A2 scPerturb `NormanWeissman2019_filtered.h5ad`（Zenodo 10.5281/zenodo.7041849，CC BY 4.0）+ A1 MSigDB v2026.1 Hallmark 50 集（不随仓库分发）
- Profile：`data/aivc/derived/norman-perturbation-profile.json`，profile_id `norman-perturbation-profile-0a0aa914dc9fb080`（已登记 registry）
- 模型级别：`reference model`（实证描述；无预测模型，不是验证结论）

## 1. 管线与产物

两段管线按 ADR-0036 冻结参数执行：

```text
scripts/aivc_norman_empirical.py（.venv-train，h5py）
  → mgba-aivc-empirical-log2fc-0.1：236 单元 × 4,267 桥基因 log2FC
    （QC good_coverage 93.77%；对照 11,183 细胞；≥50 细胞单元全保留；原始计数 → 1e4 → log2(1+x) → 单元均值 − 对照均值）
mgba aivc-perturbation-anchor（核心，纯标准库）
  → mgba-aivc-perturbation-profile-0.1：六节点向量 + digest 拆分 + train-only 质心 + 描述性指标
```

六节点桥身份 `mgba-hallmark-six-node-bridge-0.1`（digest 见模块常量）；拆分为 `sha256(salt|unit)` 排序取前 80%：train 188 / holdout 48，无重叠。

## 2. 结果（描述性）

train-only 质心（六节点，188 单元均值）：

| 节点 | 质心 | 全 236 单元范围 |
|---|---:|---|
| damage_response | +0.00008 | [-0.0139, +0.0190] |
| signal_expression | +0.00554 | [-0.0131, +0.0528] |
| repair_expression | -0.03326 | [-0.1182, +0.0246] |
| metabolic_expression | -0.03644 | （见 profile） |
| death_expression | -0.00229 | （见 profile） |
| negative_feedback_expression | +0.01135 | （见 profile） |

相对质心的描述性距离（MAE / 方向一致率 / Spearman）：

| 角色 | 单元数 | MAE | 方向一致率 | Spearman |
|---|---:|---:|---:|---:|
| train | 188 | 0.01347 | 0.718 | 0.682 |
| holdout | 48 | 0.01287 | 0.701 | 0.790 |

判读边界：多数 CRISPRa 过表达对六个 Hallmark 代理节点的扰动较小且方向相似（repair/metabolic 平均略降），单元间差异存在但有限；train 与 holdout 距离同量级，说明质心是这个空间里不弱的透明基线。这是 L0 训练必须超越的实证基线，**不是**任何模型通过验证的证据。

示意单元（illustrative，非结果选择）：单基因过表达中 repair_expression 最高为 MAP2K3（+0.0199，530 细胞），最低为 CEBPA（-0.1029，427 细胞，同时 signal_expression +0.0407）。单细胞背景为 K562，CRISPRa 过表达语义，不得外推至敲低或其他细胞背景。

## 3. Stage 1 完成判据核对

- 六抽象节点映射冻结：✅ HALLMARK_BRIDGE 由真实 MSigDB v2026.1 文件支撑（10 集命中；修正 `HALLMARK_TGF_BETA_SIGNALING` 官方名）。
- 真实扰动方向性锚定到 L0 语义：✅ 236 个真实扰动（含 105 单基因）已表达为六节点方向向量，入册 profile。
- CAR-M 式去标识聚合 profile artifact：✅ 只含公开扰动名与聚合数值（无 barcode/guide/单细胞值），write-once，已登记 `data/registry.json` 并通过 `mgba data-check`。

## 4. 下一步

- A3（GEO 原生矩阵）到学校网络下载后做端到端复核（ADR-0036 §5 的 A2/A3 交叉校验）。
- ADR-0035 L0 训练实验：以本 profile 为 target，训练版 L0 变体 vs 参考 GRN vs 冻结权重 MLP，同 split、同指标；通过规则沿用 ADR-0034 形状（holdout MAE 须严格低于 train-only 质心基线）。
