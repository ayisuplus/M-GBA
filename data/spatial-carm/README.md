# CAR-M 空间 L3 数据锚定执行清单

> 建立：2026-08-21 · 关联：ADR-0023、ADR-0024、ADR-0025、ADR-0028  
> 状态：**最小包已于 2026-08-28 下载并完成 MD5/字节数核验**（五文件 241,284,013 bytes，与 Zenodo 公布值一致）；source manifest、observation bundle 与去标识 target 均已生成，首次同指标评估见 `docs/实验记录/CAR-M-spatial-anchor-first-target-2026-08-28.md`。

## 1. 为什么建立这份清单

ADR-0024 的 2×2×2 机制审计显示，当前 CAR-M 空间 reference model 的 L4 差异主要来自**局部场耦合**和**空间邻域定义**；仅移动会改变显示坐标，却不会改变公共 L0–L4 数值。因此下一步不先拟合移动轨迹，也不下载大模型，而是用两类外部聚合统计锚定 L3：

1. 空间转录组：约束局部信号/压力代理场的异质性、梯度和病理区域差异；
2. 单细胞空间成像：约束巨噬/免疫细胞与肿瘤细胞的距离、邻接富集和组织混合度。

这些资源只属于 **L3 数据锚定基础设施**。它们不得向 L4 写入临床结局，不得让 L2 读取空间真值，也不得改变固定图 `CarmTissueModel`、五层 DTO/Protocol 或冻结 CAR-M 矩阵。

## 2. Stage S1：最小、互补、优先授权

| # | 资源与最小文件 | 回答的研究问题 | 压缩下载预算 | 许可状态 | 授权状态 |
|---|---|---|---:|---|---|
| S1 | Wu/Swarbrick 乳腺癌 Visium：`filtered_count_matrices.tar.gz`（155,703,418 bytes）+ `spatial.tar.gz`（54,282,871 bytes）+ `metadata.tar.gz`（217,533 bytes） | 六例原发乳腺癌中，spot 级局部表达场的 CV、空间自相关、梯度和病理区域间差异处于什么范围？ | **210,203,822 bytes**；不取 raw counts 与 image PDF | Zenodo/DataCite：**CC BY 4.0**，已于 2026-08-21 核验 | 已授权；2026-08-28 已下载核验 |
| S2 | Jackson 等乳腺癌 Imaging Mass Cytometry：`singlecell_locations.zip`（23,191,397 bytes）+ `singlecell_cluster_labels.zip`（7,888,794 bytes） | 细胞级免疫—肿瘤邻接富集、最近邻距离分位数和接触混合度处于什么范围？ | **31,080,191 bytes**；不取 48.3 GB 全量数据 | DataCite：**CC BY 1.0 Generic**，已于 2026-08-21 核验 | 已授权；2026-08-28 已下载核验 |

权威来源：

- Wu 等： [Nature Genetics 论文](https://www.nature.com/articles/s41588-021-00911-1)、[作者 Zenodo 数据记录（DOI 10.5281/zenodo.4739739）](https://zenodo.org/records/4739739)、[作者分析代码](https://github.com/Swarbricklab-code/BrCa_cell_atlas)。论文和作者仓库将空间数据指向该 Zenodo 记录；`GSE176078` 主要是单细胞/批量处理数据，不作为本清单的空间文件源。
- Jackson 等： [Nature 论文](https://www.nature.com/articles/s41586-019-1876-x)、[作者 Zenodo 数据记录（DOI 10.5281/zenodo.4607374）](https://zenodo.org/records/4607374)。

S1 与 S2 修正后的五文件合计为 **241,284,013 bytes（230.11 MiB）**。原计划的 `TumorStroma_masks.zip` 不被 ADR-0026 当前九个 neighborhood 指标消费，已在下载前按 ADR-0028 移出最小清单；未来若要增加 mask-based compartment 指标，须另行预注册。解压、临时索引和聚合输出的本地总预算仍为 **≤2 GB**。未经新授权不得扩大文件列表或预算。

## 3. Stage S2：仅在 S1/S2 流程有效后考虑

| # | 候选资源 | 用途 | 预算上限 | 当前缺口 | 授权状态 |
|---|---|---|---:|---|---|
| S3 | Keren 等 TNBC MIBI | 以独立 TNBC 队列复核 immune-mixed / compartmentalized 空间统计 | **≤1 GB，仅处理后的细胞表** | 官方资源门户的精确文件、体量和许可尚未完成审计 | 待调查；未申请授权 |
| S4 | 10x Visium HD Human Tissue Array（含乳腺浸润性导管癌） | 单供体、不同平台的技术性 holdout；只检查统计量能否计算，不作为主要生物锚点 | **≤5 GB，仅必要处理输出** | 精确文件清单与体量待冻结；癌样本的参考注释性能有官方警告 | 待调查；未申请授权 |

来源：[Keren 实验室资源页](https://www.weizmann.ac.il/mcb/Keren/resources)、[Keren 等 Cell 论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC6132072/)、[10x 官方数据集](https://www.10xgenomics.com/datasets/visium-hd-cytassist-11mm-human-TA)。10x 页面明确给出 CC BY 4.0；S3 的具体许可仍须按下载文件核对。

## 4. 预注册统计量与数据角色

下载前冻结以下数据变换，不用看结果后再挑指标：

### 4.1 邻域/拓扑锚点（S2）

- immune/macrophage-like ↔ tumor 最近邻距离的 25%、50%、75% 分位数；
- 固定半径下跨类型邻接富集：观测跨类型边比例 / 标签置换期望；
- 每图像的 tumor–stroma mixing score；
- 邻接度分布的均值、变异系数与 95% 分位数。

这些统计量只约束 `SpatialCarmConfig.interaction_radius` 和空间邻域诊断目标；细胞标签不得写入 L1–L4 DTO。

### 4.2 局部场锚点（S1）

- 预注册基因集分数的 spot 间 CV；
- 邻接 spot 的 Moran's I 或等价置换空间自相关；
- 标准化局部梯度幅度分位数；
- 病理区域内/区域间方差比。

基因集用于构造“压力/资源/信号”的**代理统计**，不是把真实表达直接当成模型三通道，也不宣称无量纲场具有物理单位。

### 4.3 校准、确认与失败判据

- S1 样本按排序后的公开样本标识经固定摘要规则划分为 4 个 calibration、2 个 holdout；摘要规则和样本列表在第一次计算前写入 manifest。
- 只在 calibration 子集选择有限个 L3 参数；S1 holdout 只做一次确认，不回流调参。
- S2 是跨模态外部核验，不参与场参数拟合。
- 若 holdout 的预注册统计误差没有优于当前 reference，结论记为“未锚定”，保留负面结果；不得继续增加自由参数直到变好。
- 任何数据映射都必须能作为可选 L3 adapter 删除；删除后固定图和 ADR-0023 reference model 必须原样运行。

## 5. 下载与落盘门禁

每条资源必须同时满足以下条件才可下载：

1. 用户明确授权具体编号与预算（S1/S2 最小包已满足）；
2. 在权威页面确认具体文件的许可/使用条款；
3. 只下载本清单列出的文件，原始文件放 `data/raw/spatial-carm/<编号>/`，不入 Git；
4. 立即记录来源 URL、下载日期、字节数和 SHA-256；
5. 去标识聚合统计写到 `data/spatial-carm/derived/`，单细胞坐标、样本 ID 和图像不进入场景包；
6. 聚合 artifact 进入 `data/registry.json` 后，`mgba data-check` 必须通过；
7. 接入时只替换/校准 L3，并运行固定图、空间 reference、校准模型三条件配对；L0/L1/L2/L4 保持相同。

### 5.1 已实现的源适配与聚合契约（无需下载即可验证）

`src/mgba/spatial_source_adapters.py` 与 `configs/experiments/carm_spatial_source_protocol.json` 已冻结前半段“原始格式 → observation bundle”：

- Wu：流式读取 10x MatrixMarket/feature/barcode/position/pathology 文件；按冻结的 stress/resource/signal 八基因代理，经 library-size normalization → `log1p` → per-gene z-score → module mean → logistic 得到 `[0,1]` 代理分数；每通道至少命中四个基因；
- Jackson：位置表与 cluster 表按显式 sample/cell 键连接；所有原始 cluster 必须通过 manifest exact map 映射到 `immune|tumor|other`，未知标签直接失败；
- 下载归档和适配器读取的每个解压文件都必须在本地 source manifest 登记 path、SHA-256、bytes、license 与 `rights_verified=true`；所有路径被限制在 manifest 目录内。

真实文件下载、解压 inventory 和原始 label inventory 完成后先运行：

```powershell
.\.venv\Scripts\mgba.exe spatial-source-adapt-field `
  --manifest data/raw/spatial-carm/S1/wu-source-manifest.json `
  --output data/raw/spatial-carm/S1/field-bundle.json
.\.venv\Scripts\mgba.exe spatial-source-adapt-neighborhood `
  --manifest data/raw/spatial-carm/S2/jackson-source-manifest.json `
  --output data/raw/spatial-carm/S2/neighborhood-bundle.json
```

`src/mgba/spatial_anchors.py` 与 `configs/experiments/carm_spatial_anchor_protocol.json` 已冻结“observation bundle → 去标识 target”的后半段管线：

- field bundle 必须提供六个样本、归一化 spot 坐标、病理区域和 stress/resource/signal 代理分数；
- neighborhood bundle 提供归一化 cell 坐标和 `immune|tumor|other` 聚合标签；
- bundle 只在 `data/raw/spatial-carm/` 或临时目录存在，不入 Git；
- target 只保留不可逆 sample alias、样本级指标和角色分布，不保留 ID/坐标/图像；
- 未设置 `rights_verified=true` 的源文件直接拒绝处理。

实际数据获授权并完成格式适配后，运行：

```powershell
.\.venv\Scripts\mgba.exe spatial-anchor-build `
  --field-bundle data/raw/spatial-carm/S1/field-bundle.json `
  --neighborhood-bundle data/raw/spatial-carm/S2/neighborhood-bundle.json `
  --output data/spatial-carm/derived/carm-spatial-anchor-target.json
.\.venv\Scripts\mgba.exe spatial-anchor-check `
  --target data/spatial-carm/derived/carm-spatial-anchor-target.json
.\.venv\Scripts\mgba.exe carm-spatial-anchor-evaluate `
  --target data/spatial-carm/derived/carm-spatial-anchor-target.json `
  --artifact-root artifacts/carm-spatial-anchor
```

第三条命令把正式 `SpatialTissueState` 投影到同一 24 个指标，并输出 calibration 15、holdout 15、external validation 9 共 39 个对照及完整 raw run。两个 bundle 与 target 已于 2026-08-28 生成并登记，首次评估为未锚定；后续标定结果因 ADR-0044 所述预算偏差仅作探索性记录，不表示模型已获生物验证。

## 6. 明确不下载/不实施

- Jackson 48.3 GB 全量数据、原始成像通道或整套图像；
- Wu 的原始 count 包与大图 PDF；
- FASTQ、BAM、受控 EGA 人类原始数据；
- 为“以后可能有用”下载的预训练大模型；
- 以临床结局为目标直接调参，或把患者结局写进 L4/L2；
- 未冻结指标前进行结果驱动的数据筛选。

## 7. 下载登记表

| 编号 | 文件 | 来源 URL | 日期 | SHA-256 | 许可 | 字节数 | 状态 |
|---|---|---|---|---|---|---:|---|
| S1 | `filtered_count_matrices.tar.gz` | Zenodo 10.5281/zenodo.4739739 | 2026-08-28 | 57531d348b7c2ae9c5cd6b6c3bf36ce2850945565f8aa381c7edc5b7fc4e4e1e | CC BY 4.0 | 155,703,418 | 已下载，MD5 对齐公布值 |
| S1 | `spatial.tar.gz` | Zenodo 10.5281/zenodo.4739739 | 2026-08-28 | bc3168535172c0970add12a9c13ab797dc5fee79fc42c392b9bea30c8f99a20a | CC BY 4.0 | 54,282,871 | 已下载，MD5 对齐公布值 |
| S1 | `metadata.tar.gz` | Zenodo 10.5281/zenodo.4739739 | 2026-08-28 | beb8c05063f279fef805349ee8cc0714957576fbfb4af7c119dc46ec5cc8bea3 | CC BY 4.0 | 217,533 | 已下载，MD5 对齐公布值 |
| S2 | `singlecell_locations.zip` | Zenodo 10.5281/zenodo.4607374 | 2026-08-28 | 8b7a42c373840983dd1c768512dbb2a651a5009e0e2964cd722119be23cedc24 | CC BY 1.0 Generic | 23,191,397 | 已下载，MD5 对齐公布值 |
| S2 | `singlecell_cluster_labels.zip` | Zenodo 10.5281/zenodo.4607374 | 2026-08-28 | c026694a83f28dc5081d7ac05558ea904df072d16ebe73feb3f967ae71ed4984 | CC BY 1.0 Generic | 7,888,794 | 已下载，MD5 对齐公布值 |
