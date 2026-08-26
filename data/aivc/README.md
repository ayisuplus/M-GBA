# AIVC 数据对接清单（待授权下载区）

> 建立：2026-08-21 · 关联：ADR-0019（L2 连续潜状态虚拟细胞策略）
> 状态：**纯调查，全部条目"待授权"，未下载任何数据。**

## 这个文件夹是什么

- 本文件夹是"AIVC 真实数据/模型锚定 M-GBA"的**唯一清单与未来下载着陆区**，防止资源散落各处找不到。
- 当前为空（只有本清单）。经用户逐条授权后，数据下载到本文件夹对应位置。
- 本机约束：**不训练任何模型**。所有资源只用于离线聚合锚定，走 CAR-M 既有先例：外部产物 → 去标识聚合 profile → 确定性场景适配器；核心 L0–L4 DTO/Protocol 与 `ReferenceCrossScaleRunner` 不动，适配器不进生成热路径。
- 每条资源遵循 AGENTS.md §6：明确用途、磁盘预算、用户授权，三齐才下载。下载后立刻登记来源 URL、日期、SHA-256 与许可（本文件末尾的登记表）。
- 层级纪律：AIVC 资源只锚定 **L0/L1**（细胞内在状态与扰动响应），禁止让任何层跳过 L1 直读基因数据；L2 规则状态机基线不动。

## 六抽象节点 ↔ 真实基因功能的语义桥（Stage 1 的前提）

M-GBA L0 是六个抽象节点（损伤响应/信号/修复/代谢/死亡/负反馈，见 `src/mgba/layers/l0.py` 的 `ABSTRACT_GENE_NAMES`，**抽象变量，不是真实 DNA**）。要用真实扰动数据锚定 L0/L1，需要一张"真实基因集 → 抽象节点"的代理映射。候选桥是 MSigDB Hallmark 基因集（50 个，人工整理、广泛引用）：

| 抽象节点 | 候选 Hallmark 基因集 | 代理强度 |
|---|---|---|
| 损伤响应 | `HALLMARK_P53_PATHWAY`、`HALLMARK_UV_RESPONSE_DN` | 中 |
| 信号 | `HALLMARK_TNFA_SIGNALING_VIA_NFKB`、`HALLMARK_KRAS_SIGNALING_UP`、`HALLMARK_IL6_JAK_STAT3_SIGNALING` | 中 |
| 修复 | `HALLMARK_DNA_REPAIR` | 强 |
| 代谢 | `HALLMARK_OXIDATIVE_PHOSPHORYLATION`、`HALLMARK_GLYCOLYSIS` | 强 |
| 死亡 | `HALLMARK_APOPTOSIS` | 强 |
| 负反馈 | 无直接对应；最近似 `HALLMARK_TGFBETA_SIGNALING`（抑制性信号） | **弱，须标注为缺口** |

映射必须在对应 ADR 中标注为代理假设，并接受灵敏度检查（换一组基因集结论是否还成立）。

## Stage 1：MB 级，笔记本可直接处理（优先，建议顺序 A1→A2→A3）

| # | 资源 | 回答的研究问题（§2 预答） | 磁盘预算 | 来源 | 格式 | 笔记本可行性 | 许可 | 授权状态 |
|---|---|---|---|---|---|---|---|---|
| A1 | MSigDB Hallmark 基因集 | 提供上表的语义桥——没有它，真实数据无法映射到六抽象节点 | <5 MB | [gsea-msigdb.org](https://www.gsea-msigdb.org/gsea/msigdb/)（需免费注册）或 R 包 `msigdbr` | `.gmt` 文本 | 直接可用 | 遵守 MSigDB 条款；**不随仓库分发原始文件** | 待授权 |
| A2 | scPerturb 统一扰动资源（Nature Methods 2024, Peidli et al.） | L0 扰动响应方向锚定：真实敲低/过表达 → 表达变化方向，对照 E1 扰动传播实验 | ≤2 GB（先取预计算统计表，单数据集几十 MB 起） | [scperturb.org](https://scperturb.org)、[sanderlab/scPerturb](https://github.com/sanderlab/scPerturb) | h5ad / 预计算 DE、E-distance 表 | 预计算表可直接用；单个 h5ad 需 scanpy | 各数据集许可不一，逐条核对 | 待授权 |
| A3 | Norman et al. 2019 Perturb-seq | 最小可复现 Perturb-seq 入口，验证 A1 映射 + A2 流程端到端可行 | ≤2 GB（处理矩阵数百 MB；原始测序不取） | GEO [GSE133344](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE133344)（配套代码 [thomasmaxwellnorman/Perturbseq_GI](https://github.com/thomasmaxwellnorman/Perturbseq_GI)） | 处理表达矩阵 | 可行 | GEO 公共数据 | 待授权 |

Stage 1 完成判据：六抽象节点映射冻结 + 一条真实扰动（如某修复基因敲低）方向性地锚定到 L0 扰动语义，并产出 CAR-M 式聚合 profile artifact。只验证"锚定流程工作"，不宣称生物真实。

## Stage 2：GB 级（Stage 1 证明有用后再做）

| # | 资源 | 研究问题 | 磁盘预算 | 来源 | 可行性 | 授权状态 |
|---|---|---|---|---|---|---|
| B1 | Tahoe-100M **教学/筛选子集**（勿全量） | 药物扰动场景锚定（1 亿+ 细胞、~10 万药物处理）；M-GBA 可取单细胞系单药物的响应子集聚合 | ≤5 GB；教学子集（如 `plate3_2k-obs.h5ad`）MB 级；单板完整 h5ad 1–3 GB | [Arc Virtual Cell Atlas](https://virtualcellatlas.org) / [Lamin 文档](https://docs.lamin.ai/arc-virtual-cell-atlas)（按 `sample_id` 筛选下载；[Tahoe 官方说明](https://www.tahoebio.ai/news/open-sourcing-tahoe-100m)） | 子集可行；需 h5ad 工具链 | 待授权 |
| B2 | Replogle et al. 2022 全基因组 Perturb-seq（处理版） | 全基因组尺度扰动对照（最大的 CRISPR 扰动单细胞数据集） | ≤5 GB | 经 scPerturb 统一版或论文配套 Figshare | 可行但偏重 | 待授权 |

## Stage 3：预训练权重 + 独立推理环境（最重，最后考虑；与 Stage 1/2 无依赖关系）

| # | 资源 | 研究问题 | 磁盘预算 | 来源 | 可行性 | 授权状态 |
|---|---|---|---|---|---|---|
| C1 | Geneformer 预训练权重 | 离线生成细胞状态嵌入 → 聚合进场景 profile（零样本 in silico 扰动）；对应 L0/L1 数据驱动替换的"真实版" | ≤3 GB 权重 + 独立 venv（torch/transformers，**不进项目核心依赖**） | HuggingFace [ctheodoris/Geneformer](https://huggingface.co/ctheodoris/Geneformer)（[模型说明](https://virtualcellmodels.cziscience.com/model/geneformer)） | 小批量 CPU 推理可行；批量推理不现实 | 待授权 |
| C2 | STATE（Arc Institute） | 扰动转移预测 oracle：给 M-GBA 的 L0 扰动提供数据驱动对照 | 权重 GB 级 + torch 环境 | 代码 [ArcInstitute/state](https://github.com/ArcInstitute/state)，权重经 HuggingFace 分发（见其 README） | 依赖重，笔记本仅适合极小批量尝试 | 待授权 |
| C3 | OCellus | gene-level KO pseudo-bulk 预测候选：按 ADR-0034 与真实 Perturb-seq target、train-only centroid 做同 split 六节点对照 | 未知；代码/权重/许可公开后先核算，独立环境且不进核心依赖 | [bioRxiv v1](https://www.biorxiv.org/content/10.64898/2026.07.08.737248v1)；当前代码、权重、GNN/Agent 发布仍待确认 | 当前不可执行；只实现 `mgba-ocellus-perturbation-anchor-0.1` 离线输入契约 | 待公开、预算与授权 |

## 明确不下载

- Tahoe-100M 全集（14 个 h5ad 约 24.7 GB）与 Arc Virtual Cell Atlas 全集（约 41 TB）。
- 任何原始测序数据（BAM/FASTQ）。
- 任何以"训练"为目的的资源：本机不训练，只离线推理/聚合。

## 下载后统一规矩（每条必做）

1. 文件放本文件夹，按清单编号命名子目录（如 `data/aivc/A1-msigdb-hallmark/`）。
2. 在下方登记表补一行：编号、文件、来源 URL、下载日期、SHA-256、许可、磁盘占用。
3. 去标识与聚合在本文件夹内完成，聚合 profile 才允许进入 `src/mgba/scenarios/` 适配器；原始数据不进 git。
4. 每次接入新增一层只动一层，配对新 ADR 与对照实验（复用 WP8 配对指标），负面结果保留。

## 下载登记表

| 编号 | 文件 | 来源 URL | 日期 | SHA-256 | 许可 | 占用 |
|---|---|---|---|---|---|---|
| （空） | | | | | | |
