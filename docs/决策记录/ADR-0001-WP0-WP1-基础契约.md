# ADR-0001：冻结 WP0–WP1 基础契约

> 状态：已接受；L0–L4 DTO 与 Protocol 已由 ADR-0002/0003/0004/0005/0006 增量修订  
> 日期：2026-08-18  
> 作用范围：WP0 实验骨架、WP1 五层 DTO 与接口

## 背景

初始化版本的 `multiscale.py` 已能演示 L0→L4 单次传播，但 DTO、参考公式和调度器位于同一文件，也没有正式的实验身份与层间事件。继续直接实现 L0 调控网络会让生物规则依赖临时接口，因此先冻结最小工程契约。

本决定不改变科学主张：当前系统仍是 `contract demonstrator`，不是生物学 reference model。

## 决定

### 五层状态

所有运行时状态都使用不可变 DTO，并携带相同的 `StateMetadata`：

- `logical_time`：本状态对应的逻辑时间；
- `model_version`：生成状态的模型版本；
- `source_digest`：正式输入的确定性摘要。

冻结的第一版 DTO 为：

| 层级 | DTO | 第一版业务字段 |
|---|---|---|
| L0 | `TranscriptState` | cell ID、信号/修复/代谢表达 |
| L1 | `MolecularState` | cell ID、信号/修复蛋白、代谢能力 |
| L2 | `CellState` | cell ID、激活、存活 |
| L2 | `CellAction` | cell ID、分泌动作 |
| L3 | `TissueState` | Cell 数、边密度、群体均值、协调信号、组织损伤 |
| L4 | `OrganismState` | 活力、炎症、稳态 |

`LocalEnvironment` 是 L3 暴露给单个 L2 Cell 的边界 DTO；第一版只含局部压力。它不允许 Cell 读取完整组织状态。

后续 L0 时间演化所需的三个新增表达字段、`RegulatoryInput` 和 `GenomeStepResult` 见 [ADR-0002](ADR-0002-L0-离散GRN.md)；其余 WP1 契约不变。

后续 L1 时间演化所需的三个新增分子字段、`MolecularInput` 和上一状态入口见 [ADR-0003](ADR-0003-L1-粗粒度分子动力学.md)。

后续 L2 五态状态机所需的 phase、局部环境字段、动作字段和上一状态入口见 [ADR-0004](ADR-0004-L2-Cell状态机.md)。

后续 L3 固定图环境动力学所需的节点状态、图快照、组织聚合字段和上一状态入口见 [ADR-0005](ADR-0005-L3-组织与微环境.md)。

后续 L4 即时指标、窗口摘要和最终结局所需的字段见 [ADR-0006](ADR-0006-L4-宏观表型.md)。

### 层模型接口

使用 Python `Protocol` 定义 `GenomeModel`、`MolecularModel`、`CellModel`、`TissueModel` 和 `PhenotypeModel`。`ReferenceCrossScaleRunner` 通过构造函数接收五个实现，因此替换某一层时不修改场景和其他层。

运行时参考实现同时检查关键 DTO 类型。例如 Cell 模型收到 `TranscriptState` 时必须失败，不能依靠类型注解掩盖 L0→L2 跳层。

### 转换事件

一次契约运行必须按顺序产生四条 `LayerTransitionEvent`：

```text
L0→L1、L1→L2、L2→L3、L3→L4
```

事件保存逻辑时间、源/目标层、执行模型版本、输入/输出摘要、时间尺度和转换理由。事件构造器拒绝非相邻层；`LayerTrace` 拒绝缺层、乱序或 Cell 身份不一致的轨迹。

### 实验 manifest

`ExperimentManifest` 第一版保存：schema 版本、实验名称、随机种子、代码版本、完整配置摘要和各层模型版本。实验 ID 是这些字段规范化 JSON 的 SHA-256 前 16 位，因此：

- 相同输入得到相同 ID；
- seed、扰动、模型版本或配置变化会得到不同 ID；
- 时间戳和 artifact 保存路径不参与实验身份。

### 配置边界

- 实验配置：seed、初始 Cell、环境压力、初始拓扑和扰动；
- 层配置：某一层模型自己的参数与模型版本；
- 输出配置：artifact 根目录和展示选项，不得改变运行结果。

当前 `multiscale_demo.json` 暂时同时承载实验初态和占位层参数。WP2 引入真正 GRN 时再拆出 L0 层配置；在此之前不为一次使用增加配置框架。

### Artifact 规则

标准库 helper 初始化以下纯文本目录：

```text
artifacts/<experiment-id>/
├── manifest.json
├── raw/
│   ├── events.ndjson
│   └── states/
└── derived/
```

`manifest.json` 已存在时只能与当前 manifest 完全相同；事件只通过追加 API 写入 NDJSON。`derived/` 可重建，不视为原始证据。核心数据不依赖 UI 或 Notebook 才能读取。

## 备选方案

1. 继续使用单文件 dataclass：代码更少，但无法独立替换层模型，也无法自动阻止跳层，拒绝。
2. 使用抽象基类：可以约束继承，但会把模型绑定到框架基类；当前只需要结构契约，选择 `Protocol`。
3. 引入 Pydantic/JSON Schema：验证能力更强，但 WP0–WP1 的字段很少，标准库 dataclass 已满足门禁；后续遇到外部数据交换需求再评估。

## 影响与限制

- CLI 输出新增 metadata、L2 action、转换事件和 manifest，旧命令不变，但摘要 digest 会更新。
- 当前逻辑时间固定为 0，`timescale` 为 `contract-step`；多速率推进属于 WP7。
- L0/L1 公式仍是显式占位映射；本决定只保证接口真实性，不保证层内生物真实性。
- 配置文件本体的归档和完整 state artifact 写入将在 ExperimentRunner 阶段补齐。

## 回退方式

保留 `ReferenceCrossScaleRunner` 的依赖注入入口和标准库 DTO。若某个字段或事件设计被后续实验否定，新增 schema/model 版本并提供显式适配器；不得静默修改既有 artifact 的解释。
