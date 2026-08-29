# CAR-M 空间 L3 首次真实数据锚定评估记录

- 日期：2026-08-28
- 协议：`configs/experiments/carm_spatial_source_protocol.json`（ADR-0028）、`configs/experiments/carm_spatial_anchor_protocol.json`（ADR-0026）、`configs/experiments/carm_spatial_anchor_evaluation.json`（ADR-0027）
- 数据：Wu/Swarbrick Visium（Zenodo 10.5281/zenodo.4739739，CC BY 4.0）+ Jackson IMC（Zenodo 10.5281/zenodo.4607374，CC BY 1.0 Generic）
- Target：`data/spatial-carm/derived/carm-spatial-anchor-target.json`，target_id `spatial-anchor-29c87ba1411d4fc8`
- 评分：score_id `spatial-score-f693c3da106acdc5`
- Artifact：`artifacts/carm-spatial-anchor/carm-spatial-anchor-eval-e4557bd18b08ebff/`（raw run + manifest + summary）
- 模型级别：`reference model`（首次真实同指标描述性对照，不是验证结论）

## 1. 数据获取与核验

2026-08-28 经网络代理下载 ADR-0025/0028 预注册最小包五文件，共 241,284,013 bytes，与冻结清单逐字节一致；MD5 全部对齐 Zenodo 公布值，SHA-256 逐文件登记于 `data/raw/spatial-carm/S1/wu-source-manifest.json` 与 `S2/jackson-source-manifest.json`，并回填 `data/spatial-carm/README.md` §7 下载登记表。原始文件与 observation bundle 留在 `data/raw/spatial-carm/`，不入库；去标识 target 已登记 `data/registry.json`（`carm-spatial-anchor-target`，`mgba data-check` 通过）。

## 2. 真实源格式与预冻结适配器的偏差及处理

真实文件与 ADR-0028 合成 fixture 存在三处格式偏差，全部以机械派生处理（`data/raw/spatial-carm/derive_inputs.py`，逐文件 SHA-256 登记），**未改动任何冻结配置、适配器代码或协议**：

1. **伪 .gz 后缀**：`filtered_count_matrices.tar.gz` 内 18 个 `.gz` 文件实为纯文本（无 1f8b magic）。派生为同名无后缀硬链接（内容不变）。
2. **单列 features**：真实 `features.tsv` 为单列基因符号，而冻结协议 `feature_symbol_column=1` 面向三列 10x 格式。派生为两列重写（符号原样复制两列），不改协议。
3. **未命名索引列**：Wu metadata CSV 首列（spot barcode）无表头名，无法通过非空列名校验。派生时将首列表头命名为 `Barcode`，其余字节不变。

区域聚合（field 侧 `region_map`）在下载后、首次计算前冻结为两区域：

- `tumor`：Invasive cancer（全部四种组合）、DCIS、Cancer trapped in lymphocyte aggregation；
- `non_tumor`：Stroma、Lymphocytes、Necrosis、TLS、Adipose tissue、Normal glands/duct 各组合；
- 有意不映射（适配器跳过）：`Artefact`、`NA`、`Uncertain`、空值。

Jackson 侧（neighborhood）：标签表只有 `(id, cluster)`，位置表 855,668/433,127 行多于标签 844,498/379,913 行。派生为按 cell `id` 精确内连接，标签表派生 `core` 列用于按 TMA 核心分组；冻结 27-metacluster 映射（1–6 immune、7–13 other、14–27 tumor，来自 `Metacluster_annotations.csv`）只写入 manifest `label_map`。映射后缺少 immune 或 tumor 的核心按确定性规则剔除：Basel 376→371、Zurich 332→325，剔除清单见派生脚本输出。

## 3. 管线执行

```text
spatial-source-adapt-field        → field bundle：6 样本、15,324 spot 观察
spatial-source-adapt-neighborhood → neighborhood bundle：696 样本、1,223,961 cell 观察
spatial-anchor-build + check      → target spatial-anchor-29c87ba1411d4fc8（ok）
                                    角色：calibration 4 / holdout 2 / external_validation 696
carm-spatial-anchor-evaluate      → score spatial-score-f693c3da106acdc5（20 tick，seed 42）
```

## 4. 首次真实同指标评估结果

当前 reference 空间 L3（`carm-spatial-l3-reference-0.1+8e3b3f9ff23e`）投影到同一 24 指标后，与真实聚合分布的描述性距离：

| 角色 | 指标数 | 平均归一化绝对误差 | 最大归一化绝对误差 | 落入观测范围比例 |
|---|---:|---:|---:|---:|
| calibration（场） | 15 | 10.3478 | 18.5184 | 0.0 |
| holdout（场） | 15 | 12.1461 | 19.2821 | 0.0 |
| external_validation（邻域） | 9 | 1.3274 | 2.2594 | 1.0 |

判读边界（按 artifact 自述）：这是与观测聚合分布的描述性距离，不是似然、p 值、生物验证或疗效分数。

## 5. 结论（按预注册失败判据）

- 场（field）统计上，当前 reference 空间 L3 与真实 Visium 聚合分布差距很大（归一化误差 ~10–12，且模型值完全落在观测分布范围之外）；邻域统计上距离较小但仍有系统偏差。
- 按 ADR-0025 §4.3，结论记为**“未锚定”**，保留为负面结果；不得为改善该分数继续增加自由参数直到变好。
- 下一步（需另行预注册后才能执行）：只在 4 个 calibration 样本上选择有限个 L3 参数（候选：`SpatialCarmConfig.interaction_radius` 与场耦合强度），holdout 只做一次确认，Jackson external validation 不参与拟合。

## 6. 附带发现与修复

- `data/synthetic-feedback/` 六个文件与 `data/registry.json` 登记哈希不匹配。定位为行尾差异：本机（Windows）确定性重生成字节与登记值一致，zip 落盘文件为 LF。JSON 内容逐字节等价（`diff --strip-trailing-cr` 无差异）。已用重生成字节恢复一致性，`mgba data-check` 五条目全绿；未改动登记哈希。
- Git 与 curl 默认未走本机代理；已将 git 全局 `http.proxy`/`https.proxy` 设为 `http://127.0.0.1:7897`。
