# ADR-0028：CAR-M 空间源格式适配器与三通道代理映射

- 状态：源适配器已实现；真实下载受当前网络出口阻塞
- 日期：2026-08-21
- 所属层级：L3 数据锚定基础设施（生成链外）
- 关联：ADR-0025、ADR-0026、ADR-0027、ADR-0021

## 1. 问题

ADR-0026 从统一 observation bundle 开始工作，但 Wu Visium 与 Jackson IMC 的真实文件还缺少进入该边界的可审计转换。若临时用 Notebook 手工拼表，会留下三个问题：

1. 三个无量纲场通道的基因代理可能在看过结果后被改写；
2. Jackson 原始 cluster 可能被模糊字符串规则猜成 immune/tumor，无法审计；
3. 下载归档、解压表和 bundle 之间没有完整 SHA-256 链。

因此在下载之前先冻结源适配协议，并用小型原始格式 fixture 验证整条“10x/CSV → observation bundle → target”路径。

## 2. 新能力准入六问

1. **属于哪一层？** L3 数据锚定基础设施；只在生成链外运行。
2. **增强什么基线？** 补齐 ADR-0026 的上游格式边界，不替换任何 L0–L4 模型。
3. **回答什么问题？** 已核验的原始空间文件能否确定性地产生冻结的 L3 场/邻域代理观察？
4. **如何判断有效？** 源文件 Rights/字节数/SHA-256、exact-key manifest、流式 MatrixMarket 读取、精确标签映射、顺序不变性、篡改拒绝和现有 target checker 全部通过。
5. **失败能否移除？** 可以；删除本模块、两条 CLI 和协议配置即可，runner 与冻结实验无依赖。
6. **能否解释？** 每一步都是标准化、聚合和显式映射；不使用训练权重、隐式嵌入或 LLM 分类。

## 3. 决策

新增 `mgba.spatial_source_adapters` 和两条生成链外命令：

```powershell
mgba spatial-source-adapt-field `
  --manifest data/raw/spatial-carm/S1/wu-source-manifest.json `
  --output data/raw/spatial-carm/S1/field-bundle.json

mgba spatial-source-adapt-neighborhood `
  --manifest data/raw/spatial-carm/S2/jackson-source-manifest.json `
  --output data/raw/spatial-carm/S2/neighborhood-bundle.json
```

manifest 中的所有路径必须相对 manifest 所在目录且不能越界。下载归档以及适配器实际读取的每个解压文件都必须登记 `path/file_id/SHA-256/bytes/license/rights_verified`；适配器逐文件复核。相同内容的重复 `features.tsv` 会全部核验，但在 bundle provenance 中按内容摘要确定性去重。

bundle 仍使用 ADR-0026 的 `mgba-spatial-observation-bundle-0.1`，所以后半段聚合、去标识和模型同指标评估无须改变。

## 4. Wu Visium 三通道代理冻结

`configs/experiments/carm_spatial_source_protocol.json` 在读取真实表达值前冻结三个手工、透明的八基因代理集：

- stress：`ATF3/BAX/BBC3/CDKN1A/DDIT3/GADD45A/MDM2/TP53`；
- resource：`ALDOA/ENO1/GAPDH/LDHA/NDUFS1/PGK1/PKM/SLC2A1`；
- signal：`CCL2/CXCL8/IL6ST/NFKB1/NFKBIA/RELA/SOCS3/STAT3`。

这些集合分别近似 p53/损伤与凋亡、糖酵解与氧化代谢、NF-κB/IL6-JAK-STAT 信号。它们不是完整 Hallmark 集，也不表示真实物理压力、资源或信号。

每个样本的变换固定为：

1. spot 库大小归一化到 10,000；
2. 每基因 `log1p`；
3. 每基因在已映射组织 spot 间 z-score；
4. 通道内可用基因取均值；
5. logistic 映射到 `[0,1]`。

每通道八基因至少命中四个，否则失败。病理注释只通过 manifest 中的 exact `region_map` 聚合；未映射区域被排除，不能用结果驱动的字符串猜测补齐。

## 5. Jackson IMC 标签冻结

位置表与 cluster 表用 manifest 明确指定的 sample/cell 列做一一连接。每一个原始 cluster 名称必须在 exact `label_map` 中映射到 `immune|tumor|other`；未知标签、重复键、缺失位置或缺失标签都直接失败。映射表只能在原始文件 inventory 后、计算任何邻域统计前冻结。

原清单中的 `TumorStroma_masks.zip` 不被当前 ADR-0026 九个 neighborhood 指标消费。为遵守“没有明确用途不下载”，本轮最小下载清单移除该 6,959,435-byte 文件；若以后增加 mask-based compartment 指标，必须另行预注册后再下载。

## 6. 权利与预算核验

2026-08-21 已通过官方 Zenodo API 与 DataCite 元数据核验：

- Wu 记录 10.5281/zenodo.4739739：CC BY 4.0；三个文件共 210,203,822 bytes；
- Jackson 记录 10.5281/zenodo.4607374：DataCite 明示 CC BY 1.0 Generic；位置和 cluster 两文件共 31,080,191 bytes。

修正后的五文件总量为 241,284,013 bytes（230.11 MiB），仍受本地峰值 ≤2 GB 门禁。用户已授权该预注册最小包，但当前环境对 `zenodo.org` 的命令行和应用内浏览器访问都超时/DNS 失败，所以没有文件落盘、没有真实 bundle、没有 target 或评分。

## 7. 验证与科学边界

七项测试覆盖：协议冻结、流式 10x 读取、六样本输出、manifest 顺序不变、源字节篡改拒绝、Jackson 精确标签映射、两条 CLI 接入现有 target checker。

测试使用的是合成原始格式 fixture，只能把当前能力称为 `contract demonstrator`。真实文件到达后仍须：

1. 冻结解压 inventory、Wu 六样本路径/region_map、Jackson 全量 cluster label_map；
2. 生成真实 bundle 和 target；
3. 执行 calibration/holdout/external-validation 同指标评估；
4. 保留未锚定或变差结果。

不得据此声称模型复现真实肿瘤组织、具备临床能力或已经产生数字生命。

## 8. 回退

删除 `src/mgba/spatial_source_adapters.py`、`configs/experiments/carm_spatial_source_protocol.json`、两条 CLI、对应测试与本文档即可。ADR-0023 空间 reference、ADR-0026 target、ADR-0027 评估器、固定图基线与冻结矩阵均不受影响。
