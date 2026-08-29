# AIVC 数据对接清单（待授权下载区）

> 建立：2026-08-21 · 关联：ADR-0019（L2 连续潜状态虚拟细胞策略）
> 状态：**2026-08-29 更新**：A1/A2/A3/B1/B2（K562_essential + rpe1）/C1 **全部下载并核验登记完成**。训练与锚定所需数据全部就绪。

## 这个文件夹是什么

- 本文件夹是"AIVC 真实数据/模型锚定 M-GBA"的**唯一清单与未来下载着陆区**，防止资源散落各处找不到。
- 当前为空（只有本清单）。数据按清单编号子目录落盘（如 `A2-scperturb/`），原始文件不入 Git。
- 本机约束：**训练前提已由 ADR-0035（2026-08-28）解除**——硬件 RTX 5090 32 GB + 192 GB 内存已就位；训练只在独立虚拟环境进行，PyTorch 等依赖永不进核心包，训练产物只落 `models/` 与独立环境。所有资源仍优先用于离线聚合锚定，走 CAR-M 既有先例：外部产物 → 去标识聚合 profile → 确定性场景适配器；核心 L0–L4 DTO/Protocol 与 `ReferenceCrossScaleRunner` 不动，适配器不进生成热路径。
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
| 负反馈 | 无直接对应；最近似 `HALLMARK_TGF_BETA_SIGNALING`（抑制性信号） | **弱，须标注为缺口** |

映射必须在对应 ADR 中标注为代理假设，并接受灵敏度检查（换一组基因集结论是否还成立）。

## Stage 1：MB 级，笔记本可直接处理（优先，建议顺序 A1→A2→A3）

| # | 资源 | 回答的研究问题（§2 预答） | 磁盘预算 | 来源 | 格式 | 笔记本可行性 | 许可 | 授权状态 |
|---|---|---|---|---|---|---|---|---|
| A1 | MSigDB Hallmark 基因集 | 提供上表的语义桥——没有它，真实数据无法映射到六抽象节点 | <5 MB | [gsea-msigdb.org](https://www.gsea-msigdb.org/gsea/msigdb/)（需免费注册）或 R 包 `msigdbr` | `.gmt` 文本 | 直接可用 | 遵守 MSigDB 条款；**不随仓库分发原始文件** | 已授权；2026-08-28 经官网登录态从 Broad 官方数据主机下载 `h.all.v2026.1.Hs.symbols.gmt`（48,686 B，v2026.1，50 集）；实测发现冻结桥拼写 `HALLMARK_TGFBETA_SIGNALING` 与官方名 `HALLMARK_TGF_BETA_SIGNALING` 不符，已修正（ocellus_anchors + 本表） |
| A2 | scPerturb 统一扰动资源（Nature Methods 2024, Peidli et al.） | L0 扰动响应方向锚定：真实敲低/过表达 → 表达变化方向，对照 E1 扰动传播实验 | ≤2 GB（先取预计算统计表，单数据集几十 MB 起） | [scperturb.org](https://scperturb.org)、[sanderlab/scPerturb](https://github.com/sanderlab/scPerturb) | h5ad / 预计算 DE、E-distance 表 | 预计算表可直接用；单个 h5ad 需 scanpy | 各数据集许可不一，逐条核对 | 已授权；2026-08-28 已下载 `NormanWeissman2019_filtered.h5ad`（698,680,199 B，CC BY 4.0，MD5 核验） |
| A3 | Norman et al. 2019 Perturb-seq | 最小可复现 Perturb-seq 入口，验证 A1 映射 + A2 流程端到端可行 | ≤2 GB（处理矩阵数百 MB；原始测序不取） | GEO [GSE133344](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE133344)（配套代码 [thomasmaxwellnorman/Perturbseq_GI](https://github.com/thomasmaxwellnorman/Perturbseq_GI)） | 处理表达矩阵 | 可行 | GEO 公共数据 | 已授权；NCBI 对本网络限流（~10–17 KB/s），四文件 ≈1.1 GB 移入学校学术资源批次 |

Stage 1 完成判据：六抽象节点映射冻结 + 一条真实扰动（如某修复基因敲低）方向性地锚定到 L0 扰动语义，并产出 CAR-M 式聚合 profile artifact。只验证"锚定流程工作"，不宣称生物真实。

## Stage 2：GB 级（Stage 1 证明有用后再做）

| # | 资源 | 研究问题 | 磁盘预算 | 来源 | 可行性 | 授权状态 |
|---|---|---|---|---|---|---|
| B1 | Tahoe-100M **教学/筛选子集**（勿全量） | 药物扰动场景锚定（1 亿+ 细胞、~10 万药物处理）；M-GBA 可取单细胞系单药物的响应子集聚合 | ≤5 GB；教学子集（如 `plate3_2k-obs.h5ad`）MB 级；单板完整 h5ad 1–3 GB | [Arc Virtual Cell Atlas](https://virtualcellatlas.org) / [Lamin 文档](https://docs.lamin.ai/arc-virtual-cell-atlas)（按 `sample_id` 筛选下载；[Tahoe 官方说明](https://www.tahoebio.ai/news/open-sourcing-tahoe-100m)） | 子集可行；需 h5ad 工具链 | 已下载核验：教学子集 7,253,540 B（2026-08-29，GCS 直链，MD5 对齐 x-goog-hash；无需账号） |
| B2 | Replogle et al. 2022 全基因组 Perturb-seq（处理版） | 全基因组尺度扰动对照（最大的 CRISPR 扰动单细胞数据集） | ≤5 GB | 经 scPerturb 统一版或论文配套 Figshare | 可行但偏重 | 已下载核验（2026-08-29）：`K562_essential` 1,546,729,675 B + `rpe1` 1,236,886,900 B，MD5 均对齐 Zenodo；`K562_gwps` 8.8 GB 超上限未取 |

## Stage 3：预训练权重 + 独立推理环境（最重，最后考虑；与 Stage 1/2 无依赖关系）

| # | 资源 | 研究问题 | 磁盘预算 | 来源 | 可行性 | 授权状态 |
|---|---|---|---|---|---|---|
| C1 | Geneformer 预训练权重 | 离线生成细胞状态嵌入 → 聚合进场景 profile（零样本 in silico 扰动）；对应 L0/L1 数据驱动替换的"真实版" | ≤3 GB 权重 + 独立 venv（torch/transformers，**不进项目核心依赖**） | HuggingFace [ctheodoris/Geneformer](https://huggingface.co/ctheodoris/Geneformer)（[模型说明](https://virtualcellmodels.cziscience.com/model/geneformer)） | GPU 推理可行（32 GB 显存） | 已授权，学校学术资源批次 |
| C2 | STATE（Arc Institute） | 扰动转移预测 oracle：给 M-GBA 的 L0 扰动提供数据驱动对照 | 权重 GB 级 + torch 环境 | 代码 [ArcInstitute/state](https://github.com/ArcInstitute/state)，权重经 HuggingFace 分发（见其 README） | 依赖重，笔记本仅适合极小批量尝试 | 待授权 |
| C3 | OCellus | gene-level KO pseudo-bulk 预测候选：按 ADR-0034 与真实 Perturb-seq target、train-only centroid 做同 split 六节点对照 | 未知；代码/权重/许可公开后先核算，独立环境且不进核心依赖 | [bioRxiv v1](https://www.biorxiv.org/content/10.64898/2026.07.08.737248v1)；当前代码、权重、GNN/Agent 发布仍待确认 | 当前不可执行；只实现 `mgba-ocellus-perturbation-anchor-0.1` 离线输入契约 | 待公开、预算与授权 |

## 明确不下载

- Tahoe-100M 全集（14 个 h5ad 约 24.7 GB）与 Arc Virtual Cell Atlas 全集（约 41 TB）。
- 任何原始测序数据（BAM/FASTQ）。
- 训练类资源的用途、环境与产物边界以 ADR-0035 §3 为准（独立环境、产物不进核心依赖、每次只训练替换一层）。

## 学校学术资源批次：精确下载卡（2026-08-28 核验地址）

> 落盘到 `data/aivc/<编号>/`；回来后我做 MD5/SHA-256 登记与 `data-check` 门禁。Zenodo 记录 CC BY 4.0；NCBI GEO 为公共数据；HuggingFace 遵守 Geneformer 仓库条款。

### A3 → `A3-norman2019-geo/`（≈1.1 GB，NCBI GEO）

```text
https://ftp.ncbi.nlm.nih.gov/geo/series/GSE133nnn/GSE133344/suppl/GSE133344_filtered_matrix.mtx.gz   （1.1 GB）
https://ftp.ncbi.nlm.nih.gov/geo/series/GSE133nnn/GSE133344/suppl/GSE133344_filtered_cell_identities.csv.gz （1.9 MB）
https://ftp.ncbi.nlm.nih.gov/geo/series/GSE133nnn/GSE133344/suppl/GSE133344_filtered_barcodes.tsv.gz        （420 KB）
https://ftp.ncbi.nlm.nih.gov/geo/series/GSE133nnn/GSE133344/suppl/GSE133344_filtered_genes.tsv.gz           （259 KB）
```

### B2 → `B2-replogle2022/`（主 1.44 GiB + 可选 1.15 GiB，Zenodo 10.5281/zenodo.7041849，CC BY 4.0）

```text
https://zenodo.org/records/7041849/files/ReplogleWeissman2022_K562_essential.h5ad   主（K562 CRISPRi 必需基因集，KD 语义）  1,546,729,675 B  md5:d8cba17576d1a8afc0f7d71b79cad0f7
https://zenodo.org/records/7041849/files/ReplogleWeissman2022_rpe1.h5ad             可选（RPE1 第二细胞背景，跨背景复核）  1,236,886,900 B  md5:cc7f1ec50aeb3a3e1b4a6cfa713d80fa
```

**不取**：`ReplogleWeissman2022_K562_gwps.h5ad`（8.8 GB，超 ≤5 GB 预算）。

### C1 → `C1-geneformer/`（≈425 MB，HuggingFace `ctheodoris/Geneformer`）

```text
https://huggingface.co/ctheodoris/Geneformer/resolve/main/Geneformer-V2-104M_CLcancer/model.safetensors   398 MiB（癌相关微调版权重）
https://huggingface.co/ctheodoris/Geneformer/resolve/main/Geneformer-V2-104M_CLcancer/config.json
https://huggingface.co/ctheodoris/Geneformer/resolve/main/Geneformer-V2-104M_CLcancer/generation_config.json
https://huggingface.co/ctheodoris/Geneformer/resolve/main/geneformer/token_dictionary_gc104M.pkl          416 KB（v2 分词字典，必需）
https://huggingface.co/ctheodoris/Geneformer/resolve/main/geneformer/gene_median_dictionary_gc104M.pkl    1.4 MB
https://huggingface.co/ctheodoris/Geneformer/resolve/main/geneformer/gene_name_id_dict_gc104M.pkl         1.6 MB
https://huggingface.co/ctheodoris/Geneformer/resolve/main/geneformer/ensembl_mapping_dict_gc104M.pkl      3.8 MB
```

**不取**：`Geneformer-V2-316M`（1.2 GB，本阶段用不到）；V1-10M（39 MiB）如需小号对照可捎带。

### B1 → `B1-tahoe100/`（✅ 已完成 2026-08-29）

实际无需账号：Lamin 页面标题暴露真实桶名 `arc-institute-virtual-cell-atlas`（先前猜的 `arc-ctc-tahoe100` 是旧名且拒绝匿名），直链：

```text
https://storage.googleapis.com/arc-institute-virtual-cell-atlas/tahoe100M/2025-02-25/tutorial/plate3_2k-obs.h5ad
```

已下载核验（MD5 对齐 GCS x-goog-hash）。教学子集 2,000 obs × 4 药物（Erdafitinib/Everolimus/Infigratinib/Pemigatinib）齐全。后续按 `sample_id` 筛更大子集时沿用同一桶前缀 `tahoe100M/2025-02-25/`。

合计约 **4.2 GB**（B2 两文件都下时）。

## 下载后统一规矩（每条必做）

1. 文件放本文件夹，按清单编号命名子目录（如 `data/aivc/A1-msigdb-hallmark/`）。
2. 在下方登记表补一行：编号、文件、来源 URL、下载日期、SHA-256、许可、磁盘占用。
3. 去标识与聚合在本文件夹内完成，聚合 profile 才允许进入 `src/mgba/scenarios/` 适配器；原始数据不进 git。
4. 每次接入新增一层只动一层，配对新 ADR 与对照实验（复用 WP8 配对指标），负面结果保留。

## 下载登记表

| 编号 | 文件 | 来源 URL | 日期 | SHA-256 | 许可 | 占用 |
|---|---|---|---|---|---|---|
| A2 | `A2-scperturb/NormanWeissman2019_filtered.h5ad` | Zenodo 10.5281/zenodo.7041849 | 2026-08-28 | efde6f5301fe256725dce1d980f37bd96a13481a9a16135515897368e631affc | CC BY 4.0 | 698,680,199 B（MD5 对齐公布值 c870e696…） |
| A1 | `A1-msigdb-hallmark/h.all.v2026.1.Hs.symbols.gmt` | data.broadinstitute.org/gsea-msigdb/msigdb/release/2026.1.Hs/（官网登录态） | 2026-08-28 | eecaf6dad908334ae885406ec72bdc0646d8917588ed7c219fac92fc5363f596 | MSigDB 使用条款（不随仓库分发） | 48,686 B |
| C1 | `C1-geneformer/Geneformer-V2-104M_CLcancer/model.safetensors` | HuggingFace ctheodoris/Geneformer | 2026-08-29 | 827738139bfed4bafa9d1f3df7c6146da2e3b85f7225076adc32c6eda0ba4357（与 HF X-Linked-ETag 逐字符一致） | Geneformer 仓库条款 | 417,571,156 B |
| C1 | `C1-geneformer/geneformer/`（token/median/name_id/ensembl 四字典 pkl + 两 config json） | 同上 | 2026-08-29 | 0819bcbd…/a51c53f6…/fabfa0c2…/67c445f4…/b3e1f3e7…/07f46e7e…（逐文件完整 SHA-256 见下载卡或重算） | 同上 | ≈7.0 MB |
| B2 | `B2-replogle2022/ReplogleWeissman2022_K562_essential.h5ad` | Zenodo 10.5281/zenodo.7041849 | 2026-08-29 | 412fd0df8c4ccea9f4db91cd88033c49200838b29d40945e48574be588b48789 | CC BY 4.0 | 1,546,729,675 B（MD5 对齐公布值 d8cba175…） |
| A3 | `A3-norman2019-geo/`（四文件） | NCBI GEO GSE133344 suppl | 2026-08-29 | matrix 7af10888c29be7e5be0466af100dfd6c5f1bc87f6d7cbfcb48270248d3639120（1,130,430,845 B，gzip 全流解压验证 4,968,142,597 B）；identities daf30337…、barcodes 49529cff…、genes 0dcba3cf…（完整值可重算）；NCBI 按连接限流，14 路 Range 并行 + 停滞检测续传完成 | GEO 公共数据 | 1,133,122,469 B 合计 |
| B1 | `B1-tahoe100/plate3_2k-obs.h5ad` | storage.googleapis.com/arc-institute-virtual-cell-atlas/tahoe100M/2025-02-25/tutorial/plate3_2k-obs.h5ad | 2026-08-29 | 83e6a3786ed1fe754b7285ae8018849e150d189ab7a3b5ce0cbdb2dd54fb6fc1（MD5 对齐 GCS x-goog-hash） | Arc Virtual Cell Atlas 条款 | 7,253,540 B |
| B2 | `B2-replogle2022/ReplogleWeissman2022_rpe1.h5ad` | 同上 | 2026-08-29 | 12d6a0cf9378c4f09411e27f0ce07b59f1d97731bd576d6fadf112f6f088d1a4（MD5 对齐公布值 cc7f1ec5…） | CC BY 4.0 | 1,236,886,900 B |
