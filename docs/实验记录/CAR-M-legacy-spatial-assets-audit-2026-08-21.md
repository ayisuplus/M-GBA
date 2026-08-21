# CAR-M 旧项目空间资产审计（2026-08-21）

## 1. 目的

复查用户提供的 `D:\car-m-virtual-cell`，判断其中是否已有可直接作为 M-GBA L3 外部锚点的真实细胞坐标、空间场、病理区域或空间组学处理结果；只读审计，不修改旧项目，不下载数据。

## 2. 发现的本地数据

旧项目包含体量可观的非空间数据缓存：

| 路径/类别 | 观察到的体量 | 与当前 L3 锚定的关系 |
|---|---:|---|
| `python/data_cache/external/tahoe/metadata/obs_metadata.parquet` | 约 2.19 GB | 药物扰动 metadata；可服务未来 L0/L1 调查，不含本任务所需组织空间坐标 |
| `python/data_cache/TCGA-BRCA_expression.tsv` | 约 178.9 MB | bulk 表达；现有 CAR-M 聚合 profile 的上游同类资产，不提供空间邻域 |
| `python/data_cache/TCGA-BRCA_cnv.tsv` / mutation 等 | 数十 MB | bulk 多组学；不提供 L3 空间真值 |
| `python/external/omnipath/` | 大型网络/注释表 | 可作 L1 通路候选，不能校准空间距离或场异质性 |

结论：这些文件不是 Wu Visium 或 Jackson IMC，也没有发现 `.h5ad`、空间 barcode/position、单细胞成像 location/mask 等可用于 ADR-0025 指标的组合。

## 3. 发现的空间代码与证据边界

- `app/src/lib/simulation/field.ts`：800×600 域、40 空间单位 grid，初始化使用中心—边缘解析先验和随机扰动；十通道为 oxygen、lactate、TGF-β、IFN-γ、IL4、IL10、VEGF、CXCL9、SPP1、ECM。更新规则、扩散系数和边界均为手工模拟规则。
- `scripts/run-trajectories-entry.ts` / bundle：可运行六个固定 seed 场景，终末输出 `cellPositions` 和 snapshot；预期写入 `paper/figures/data/trajectories.json`。
- 仓库当前不存在上述 `trajectories.json`；Figure 4 只有渲染后的 PNG/SVG/TIFF/PDF，不能逆向当作 source data。
- `archive/paper/CAR-M-Simulator-paper.md` 明确说明 LCG 是为重放而非统计质量选择，单 seed 空间模式不应作统计解释；同时承认封闭边界、统一扩散系数和 40-unit 场量化限制。

## 4. 可迁移与不可迁移

可迁移：

- grid field 与 agent positions 的中间数据形状；
- 旧十通道到 M-GBA 三代理通道的候选语义桥，例如 oxygen/resource、lactate/TGF-β/stress、IFN-γ/CXCL9/signal；该映射仍需真实数据与敏感性分析；
- headless exporter 的“输入场景 + 输出统计 + 终末位置”审计形式。

不可作为外部证据：

- 旧 ABM 生成的坐标、场值和 Figure 4；
- 旧固定 seed 的空间聚集；
- TCGA/Tahoe/OmniPath 非空间缓存对细胞距离、邻接或局部场梯度的任何推断。

## 5. 决策

不从旧项目生成“真实 L3 target”。它只作为 ADR-0026 observation-bundle 字段与兼容适配器的参考。真实 target 仍须来自 ADR-0025 的 Wu/Jackson 权威数据，并经过用户授权、许可复核、SHA-256 和 calibration/holdout 门禁。
