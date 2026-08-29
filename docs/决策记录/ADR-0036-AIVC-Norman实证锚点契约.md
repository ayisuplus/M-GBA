# ADR-0036：AIVC Norman Perturb-seq 实证锚点契约（Stage 1）

- 状态：契约已接受并实现（2026-08-28，计算前预注册）
- 日期：2026-08-28
- 影响范围：生成链外 L0/L1 扰动响应实证聚合（Stage 1 完成判据）
- 不影响：五层 DTO/Protocol、`ReferenceCrossScaleRunner`、核心零依赖身份、全部冻结基线与矩阵

## 1. 背景与准入

ADR-0035 解冻训练轨道并固定首个目标为 L0 扰动响应；`data/aivc/README.md` 的 Stage 1 完成判据要求：六抽象节点映射冻结 + 真实扰动方向性锚定到 L0 语义 + CAR-M 式去标识聚合 profile artifact。A1（MSigDB v2026.1 Hallmark 50 集）与 A2（scPerturb `NormanWeissman2019_filtered.h5ad`）已到位并登记。本 ADR 在**任何表达量计算之前**冻结实证锚定管线；它只是 ADR-0034 形状的 empirical 侧落地——当前没有预测模型，不评估任何"优于基线"的结论。

六问：L0/L1 层外数据锚定（不改层模型）；增强对象为 ADR-0035 L0 训练轨道提供实证 target；研究问题为真实 Perturb-seq 响应能否经冻结 Hallmark 六节点桥表达为 L0 扰动语义；指标为 train-only centroid 对照下的 MAE/方向一致率/Spearman（描述性，无通过规则）；失败删除脚本与模块即可回退；映射与阈值全部冻结可复查。

## 2. 冻结数据契约（计算前预注册）

数据源身份（逐文件门禁）：

- A2：`data/aivc/A2-scperturb/NormanWeissman2019_filtered.h5ad`，SHA-256 `efde6f5301fe256725dce1d980f37bd96a13481a9a16135515897368e631affc`，Zenodo 10.5281/zenodo.7041849，CC BY 4.0，rights_verified；111,445 cells × 33,694 genes，原始 UMI 计数（CSC 整数值）。
- A1：`data/aivc/A1-msigdb-hallmark/h.all.v2026.1.Hs.symbols.gmt`，SHA-256 `eecaf6dad908334ae885406ec72bdc0646d8917588ed7c219fac92fc5363f596`，MSigDB v2026.1，使用条款禁止随仓库分发。

处理规则（全部冻结）：

1. QC：只取 `obs/good_coverage == True` 的细胞（93.77%）。
2. 对照：perturbation 标签严格等于 `control` 的细胞（11,183 个 QC 细胞）。
3. 单元：完整 perturbation 字符串（单基因与组合扰动均独立成单元）；仅保留 QC 细胞数 **≥50** 的单元（全部 237 个单元满足——这是冻结前的覆盖事实，不是结果选择）。
4. 归一化：每细胞 library-size 缩放至 1e4 后 `log2(1+x)`；单元得分为该单元全部 QC 细胞的均值；`log2FC = 单元得分 − 对照得分`。
5. 基因宇宙：MSigDB v2026.1 Hallmark 50 集 symbol 并集与 var 的交集（桥作用域；不输出全转录组）。
6. 六节点桥：复用 `mgba.ocellus_anchors.HALLMARK_BRIDGE`（冻结身份与 digest），节点分 = 该节点集合去重基因并集上可见 log2FC 的无权均值；节点零覆盖即拒绝该单元。
7. 拆分：单元名经 `sha256(salt|unit)` 排序，前 80% 为 train、其余为 holdout；salt = `mgba-aivc-norman-anchor-2026-08-28`。train/holdout 不重叠。
8. 基线与指标：train-only 六节点质心；报告 holdout MAE、方向一致率、Spearman（描述性，不预设通过规则，不与任何预测模型比较）。

## 3. 两段管线与边界

- **实证段（独立环境）**：`scripts/aivc_norman_empirical.py` 只在 `.venv-train`（h5py）运行，流式读取 h5ad，产出 `mgba-aivc-empirical-log2fc-0.1` JSON（留 `data/aivc/A2-scperturb/`，带源身份与冻结参数回执）。核心包永不 import h5py。
- **聚合段（核心，纯标准库）**：`src/mgba/perturbation_anchors.py` + `mgba aivc-perturbation-anchor`，复核 empirical bundle 身份，执行桥/拆分/质心/指标，产出 write-once `mgba-aivc-perturbation-profile-0.1` 到 `data/aivc/derived/` 并登记 `data/registry.json`。
- 去标识：只输出扰动名（公开扰动标签）与聚合数值；细胞 barcode、guide 序列、单细胞值不输出。
- 表述边界：profile 是 reference-model 级实证描述，不是生物拟合、虚拟细胞证据或疗效预测；Norman 是 CRISPRa 过表达数据，K562 单一背景，不得外推。

## 4. 未采用方案与回退

未采用：scanpy/anndata 进核心包、全转录组 log2FC 输出、按响应强度挑选展示单元、伪 bulk 后取 log（改用每细胞 log 后均值）、组合扰动拆分为单基因。回退：删除 `scripts/aivc_norman_empirical.py`、`src/mgba/perturbation_anchors.py` 及独立 artifacts 即可；L0–L4、ADR-0034 契约与全部冻结实验不依赖本管线。

## 5. 验证

测试覆盖：h5ad 源身份/许可/SHA-256 门禁、QC/对照/≥50 规则、归一化与 log2FC 数值（合成 CSC fixture）、桥零覆盖拒绝、拆分单元不重叠且 digest 稳定、train-only 质心不读 holdout、MAE/方向/Spearman 重算、write-once 拒绝覆盖、CLI 往返；全套既有 488 测试与 `mgba data-check` 保持绿色。
