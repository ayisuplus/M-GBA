# ADR-0026：CAR-M 空间锚点聚合契约

- 状态：已接受并实现
- 日期：2026-08-21
- 所属层级：L3 数据锚定基础设施（生成链外）
- 关联：ADR-0025、ADR-0024、ADR-0021

## 1. 问题

ADR-0025 已冻结候选数据和指标，但外部资源的原始格式不同：Wu Visium 是 spot 表达矩阵/空间坐标/病理注释，Jackson IMC 是细胞坐标/分群/肿瘤基质掩膜。若让运行时模型或标定代码直接读取这些格式，会把重依赖、患者/样本标识和格式偶然性带进核心，并诱发“拿到数据后再挑指标”。

在等待用户授权下载期间，还需要证明后半段管线本身能运行、能去标识、能拒绝篡改，而不是只写一份数据愿望清单。

## 2. 决策

增加生成链外模块 `mgba.spatial_anchors`，建立两段式边界：

1. **Observation bundle（raw/intermediate，不入库）**：原始格式适配器只负责输出统一 JSON，保留临时 sample/spot/cell ID 和归一化坐标；每个源文件必须登记 SHA-256、字节数、许可，并显式 `rights_verified=true`。
2. **Spatial anchor target（可登记聚合 artifact）**：核心聚合器计算预注册指标，把 sample ID 变成带固定 salt 的不可逆别名，只保存每样本统计量和 calibration/holdout/external-validation 分布。spot/cell ID、坐标、图像和原始标签不得进入输出。

配置 `configs/experiments/carm_spatial_anchor_protocol.json` 冻结：

- field dataset：`wu-swarbrick-brca-visium`，必须恰好六个样本；
- 用固定摘要排序选四个 calibration、两个 holdout，不读取指标值决定划分；
- field 采用 4-NN；
- neighborhood dataset：`jackson-brca-imc`，半径为样本中位最近邻距离的 2 倍；
- 模型侧 pathology-region 代理在读取真实 target 前冻结为“到最近 tumor Cell 距离的 0.5 分位数” proximal/distal 划分；
- Jackson 全部只标为 `external_validation`，不得参与参数选择。

命令：

```powershell
mgba spatial-anchor-build `
  --field-bundle <field-bundle.json> `
  --neighborhood-bundle <neighborhood-bundle.json> `
  --output <derived-target.json>
mgba spatial-anchor-check --target <derived-target.json>
```

`spatial-anchor-build` 的输出是 write-once；同路径相同内容幂等，不同内容拒绝覆盖。`spatial-anchor-check` 重算 target digest，并拒绝出现 raw identifier/observation 字段。

## 3. 冻结指标

### Field（每个 stress/resource/signal 代理通道）

- coefficient of variation；
- 4-NN binary-weight Moran's I；
- 邻接梯度幅度的 50%/95% 分位数；
- 病理区域解释的总方差比例。

三个通道共 15 个样本级指标。代理通道必须由上游适配器按另行冻结的基因集映射归一化到 `[0,1]`；这里不把基因表达直接解释成物理场。

### Neighborhood

- immune→tumor 最近邻距离 25%/50%/75% 分位数（按单位方形对角线归一化）；
- 数据自适应但预注册的邻接半径；
- immune–tumor 跨类型邻接富集；
- 至少接触一个 tumor 邻居的 immune 比例（mixing score）；
- 度均值、CV、95% 分位数。

共 9 个样本级指标。距离和拓扑只属于 L3；细胞类型标签不会进入 L1–L4 DTO。

## 4. 本地旧项目审计对本决策的影响

`D:\car-m-virtual-cell` 中存在 TCGA、Tahoe metadata 和 OmniPath 缓存，但没有真实空间组学/成像坐标：

- `field.ts` 是中心—边缘先验、随机扰动和手工十通道反应扩散场；
- `run-trajectories-entry.ts` 可导出合成 `cellPositions`，但目标 `trajectories.json` 当前不存在；
- 旧论文明确说明单 seed 空间快照不可作统计解释。

因此旧项目的字段命名、grid/agent 数据形状可作为 observation adapter 的兼容参考，但其合成输出不能进入 external anchor target，不能伪装成真实空间证据。完整审计见对应实验记录。

## 5. 有效性门禁

- 输入 schema exact-key、数值有限性、单位方形、唯一 ID/坐标、两病理区域、immune+tumor 存在均 fail-closed；
- 未显式核验 Rights 的任何源文件拒绝处理；
- 输入样本/观测顺序变化不改变 input digest、target ID 或输出字节结构；
- target 中不出现 source `file_id`、sample/spot/cell ID、坐标或观测数组；
- calibration=4、holdout=2，neighborhood 只能 external validation；
- target digest 篡改检测、write-once 冲突拒绝、`data/raw` 输出拒绝；
- 模块不 import runner 或任何 L0–L4 模型，不进入 tick 循环。

## 6. 科学边界

当前实现只证明“预注册统计和去标识 artifact 管线能够运行”。测试数据是合成 fixture；尚无 Wu/Jackson 文件下载或真实统计结果。target 未来只能把 ADR-0023 升级为 externally anchored reference model，不能证明临床效力、真实组织重建或数字生命。

## 7. 回退

删除 `src/mgba/spatial_anchors.py`、两条 CLI、协议配置、测试和本文档即可回到 ADR-0025。运行时模型、固定图/空间 reference、冻结矩阵和现有 artifact 均不依赖本模块。
