# ADR-0002：L0 第一版离散 GRN

> 状态：已接受  
> 日期：2026-08-18  
> 作用范围：WP2 L0 Genome / Transcriptome reference model

## 背景与研究问题

当前 L0 只是把 `Genome.traits` 复制到 `TranscriptState`，没有调控边、时间演化或表达松弛，因此只能证明接口存在。WP2 要回答一个更窄、可证伪的问题：

> 一个受外部损伤输入驱动、含激活与抑制边的小型抽象调控网络，能否产生可复现的表达轨迹，并让修复表达的受控扰动只经 L1→L4 正式路径传播？

该模型属于 L0，只替换静态 L0 占位模型。L1–L4 继续使用现有稳定基线；STEN、GNN、LLM 和真实组学数据均不进入本工作包。

## 抽象变量

第一版固定六个归一化变量，范围均为 `[0, 1]`：

| 变量 | 抽象含义 | 不是 |
|---|---|---|
| `damage_response` | 对外部损伤输入的转录响应 | 真实损伤通路或具体基因 |
| `signal_expression` | 激活/通信相关表达程序 | 具体细胞因子 |
| `repair_expression` | 修复相关表达程序 | 真实 DNA 修复能力 |
| `metabolic_expression` | 代谢支持相关表达程序 | 真实代谢通量 |
| `death_expression` | 死亡倾向相关表达程序 | 临床死亡预测 |
| `negative_feedback_expression` | 抑制信号的反馈程序 | 某一已知抑制蛋白 |

`Genome.traits` 中的同名值表示每个虚拟 Cell 的基线表达倾向和初始表达，不代表 DNA 序列。

## 调控图

有向边的正权重表示激活，负权重表示抑制：

| 来源 | 目标 | 权重 | 设计目的 |
|---|---|---:|---|
| `repair_expression` | `damage_response` | -0.9 | 修复程序缓冲损伤响应 |
| `damage_response` | `signal_expression` | +2.0 | 损伤响应激活信号程序 |
| `negative_feedback_expression` | `signal_expression` | -1.3 | 负反馈限制持续信号 |
| `signal_expression` | `repair_expression` | +1.4 | 信号促进修复表达 |
| `metabolic_expression` | `repair_expression` | +1.0 | 代谢支持修复程序 |
| `death_expression` | `repair_expression` | -0.8 | 死亡倾向抑制修复程序 |
| `damage_response` | `metabolic_expression` | -0.8 | 压力消耗代谢支持 |
| `death_expression` | `metabolic_expression` | -0.8 | 死亡倾向抑制代谢支持 |
| `damage_response` | `death_expression` | +2.0 | 强损伤提高死亡倾向 |
| `repair_expression` | `death_expression` | -1.5 | 修复程序抑制死亡倾向 |
| `metabolic_expression` | `death_expression` | -0.6 | 代谢支持抑制死亡倾向 |
| `signal_expression` | `negative_feedback_expression` | +1.8 | 信号诱导负反馈 |
| `damage_response` | `negative_feedback_expression` | +0.3 | 损伤轻度促进反馈 |

外部 `damage_signal` 只直接作用于 `damage_response`，权重为 `+3.0`。其余变量必须通过网络边受到影响。

这些关系是为验证跨层方法构造的可解释假设，不是从真实生物数据估计出的结论。

## 更新方程

采用同步离散、第一阶泄漏更新。对节点 `i`：

```text
drive_i(t) = bias_i
             + basal_weight * (genome_trait_i - 0.5)
             + damage_weight_i * damage_signal(t)
             + Σ_j weight(j→i) * x_j(t)

target_i(t) = sigmoid(drive_i(t))

x_i(t+1) = (1 - update_rate) * x_i(t)
           + update_rate * target_i(t)
```

第一版 `update_rate = 0.35`、`basal_weight = 1.0`。旧状态占比表达有限周转速度，目标状态占比表达当前调控驱动；所有节点同步读取 `t` 时刻状态，避免更新顺序成为隐藏参数。

选择离散模型是因为它足以验证调控、稳态和扰动，同时只需要代数、sigmoid 和迭代。连续 ODE、随机转录和真实 GRN 推断留到已有数据与相应课程基础后再替换。

## 扰动语义

第一版扰动是持续硬钳制：`{abstract_gene: value}` 在每个 L0 tick 的自然更新后，把该节点精确设为 `[0, 1]` 内的目标值。

- 目标低于自然更新值：记录为 `knockdown`；
- 目标高于自然更新值：记录为 `overexpression`；
- 二者相等：记录为 `clamp-no-change`。

事件必须保存 Cell、逻辑时间、节点、自然更新值、应用值和操作类型。扰动不得直接修改 L1–L4。

## 配置与版本

模型参数存放在独立 L0 JSON 配置中。运行时模型版本由语义版本和配置摘要共同组成；即使操作者忘记修改语义版本，权重变化仍会改变 manifest 中的 L0 模型身份。

实验配置继续保存 seed、Cell 初态、损伤输入、拓扑和扰动。输出路径不进入实验身份。

## 验收与失败判据

固定配置下必须满足：

1. 同一初态、输入和扰动产生完全相同的轨迹与事件；
2. 所有表达始终位于 `[0, 1]`；
3. 运行 200 tick 后，最后一步最大绝对变化小于 `1e-8`；
4. 从 `damage_signal=0` 提高到 `1` 时，最终 `damage_response`、`signal_expression` 和 `death_expression` 上升，`metabolic_expression` 下降；
5. 修复节点硬钳制为 `0` 时每一步精确为 `0`，并记录敲低事件；
6. 在五层 Runner 中，修复敲低先改变 L0/L1，再改变 L2、L3 和 L4；
7. 缺节点、未知边、重复边、非有限参数和越界输入必须失败。

任一方向性判据不成立，都视为当前假设或参数失败，不能修改断言来迎合输出。

## 备选方案

1. 三节点网络：代码更少，但缺少死亡程序和负反馈，无法覆盖既定损伤—修复场景，拒绝。
2. 布尔网络：更容易解释，但剂量响应和渐近稳态过于粗糙，暂不采用。
3. 连续 ODE：更接近动力系统课程表达，但会提前引入积分器、步长和数值稳定性问题，推迟。
4. 随机更新：可以形成种子分布，但会混淆第一版确定性规则验证，推迟。

## 影响、局限与回退

- `TranscriptState` 将增加损伤、死亡和负反馈三个字段；现有 L1 暂时只消费信号、修复和代谢字段，WP3 再建立死亡相关分子映射。
- `GenomeModel` 需要接收前一 L0 状态和正式外部输入，才能在后续多速率 Runner 中持续推进。
- 静态 L0 占位模型继续保留，作为契约回归基线；离散 GRN 可通过构造函数整体移除。
- 当前没有随机性、细胞分裂、真实基因名或数据拟合，不能据此声称生物真实性或涌现。
