# M-GBA 0.1.0 答辩自测与人工验收

> 用途：完成 Gate D“用户知识所有权”的人工证据  
> 原则：不要背代码；要能说清假设、信息边界、方向性和局限

## 1. 验收方法

1. 不看“合格答案要点”，先用自己的话回答每道题。
2. 在源码或 ADR 中找到直接证据，不以 README 摘要代替代码。
3. 对不能解释的部分做标记，先补理论或跟踪一次实际运行。
4. 能在不使用“AI 是这么写的”作为理由时，才标记通过。

## 2. 一句话项目定义

**问题：** M-GBA 的核心是什么？为什么不能说它只是一个多智能体系统？

**合格答案要点：** 核心是生命状态从 L0 调控、L1 分子、L2 细胞、L3 组织到 L4 表型的逐层生成。多智能体是 L2/L3 的可选实现问题，STEN 是 L3 子系统；它们都不能代替五层主线。

## 3. L0：离散调控网

**问题：** L0 如何从上一时刻表达、Genome 基线、损伤和调控边生成下一状态？

**答案要点：** 每个抽象节点先计算

```text
drive = bias
      + basal_weight * (genome_trait - 0.5)
      + damage_weight * damage_signal
      + Σ(edge_weight * previous_source_expression)
target = sigmoid(drive)
natural_next = (1 - update_rate) * previous + update_rate * target
```

所有节点同步读取上一状态，`update_rate=0.35`。硬钳制在 natural update 之后应用并记录事件，所以扰动可审计。这些节点是抽象变量，不是真实基因。

**源码：** `src/mgba/layers/l0.py`，配置：`configs/layers/l0_reference_grn.json`。

## 4. L1：粗粒度分子周转

**问题：** L1 为什么不是 L0 的空包装？

**答案要点：** 每个分子物种具有合成率和降解率：

```text
next_species = (1 - degradation_rate) * previous_species
             + synthesis_rate * transcript_drive
```

`signal_protein` 另受上一时刻 `feedback_inhibitor` 抑制，并通过 `MolecularInput.local_signal` 接受上一 L2 激活。因此 L1 有独立时间常数和反馈计算，L2 不能直接读 L0。

**源码：** `src/mgba/layers/l1.py`，配置：`configs/layers/l1_reference_molecular.json`。

## 5. L2：局部 Cell 状态机

**问题：** 同一个 `MolecularState` 为什么能在不同局部环境下产生不同行为？

**答案要点：** L2 先从 L1 与 `LocalEnvironment` 联合计算 `stress_load`、`activation_drive`、`repair_drive` 和 `death_drive`。存活率沿上一状态累积，修复提高它，压力与死亡驱动降低它。相位优先级为：

```text
DEAD > REPAIRING > STRESSED > ACTIVATED > QUIESCENT
```

Cell 只能读本 Cell 的 L1、本地环境和自己上一状态。`DEAD` 是吸收态，死亡 Cell 的分泌、消耗和修复动作归零。

**追问：** 为什么 `l2_static` 改善结局不能证明静态 L2 更真实？

**答案要点：** 这只说明当前五态活力累积、死亡阈值或资源消耗是 baseline 失败的主要敏感点；它是模型内诊断，不是真实性比较。

## 6. L3：固定有向组织图

**问题：** 有向边 `(A, B)` 在当前 L3 中表示什么？

**答案要点：** A 的上一局部压力和当前分泌可影响 B 的下一压力/信号，不反向影响 A。每个节点同步更新：资源会恢复并被本 Cell 消耗；压力保留、接受入边压力、资源短缺与凋亡增益，并被修复降低；信号保留并接受入边分泌。

```text
tissue_damage = 0.6 * mean_stress + 0.4 * (1 - mean_viability)
```

拓扑在 0.1.0 中固定；STEN 的 rewiring 尚未进入五层主链。

## 7. L4：宏观观察者

**问题：** L4 如何保证没有把期望结果直接写入 Cell？

**答案要点：** `PhenotypeObserverModel.step` 的唯一模型输入是 `TissueState`。它计算：

```text
vitality = viability * (0.4 * resource + 0.6 * (1 - damage))
inflammation = 0.5 * damage + 0.3 * activation + 0.2 * signal
homeostasis = 0.45 * vitality + 0.3 * (1 - inflammation) + 0.25 * (1 - dead_fraction)
recovery = viability * (0.5 * repair + 0.3 * resource + 0.2 * (1 - damage))
```

结局优先级为 `FAILED`，然后 `RECOVERED`、`DETERIORATING`、`STABLE`。失败阈值是活力 `<=0.2` 或损伤 `>=0.8`。这些无量纲阈值在 WP8 之前冻结，不是临床阈值。

## 8. 多速率与反馈边界

**问题：** 哪些层每 tick 更新，哪些是慢时钟？当前闭合了哪些反馈？

**答案要点：** L1/L2/L3 每 tick 更新；L0 每 5 tick，L4 每 10 tick，都从 tick 1 锚定。上一 L2 的 activation 通过 `MolecularInput` 进入下一 L1，上一 L3 通过 `LocalEnvironment` 进入下一 L2。尚无 L4→L3 反馈，也尚无 L1→L0 的内生下行调控，所以不能声称完整反馈闭环。

## 9. WP8 配对反事实

**问题：** 为什么每个扰动/消融必须与“同 seed baseline”配对？

**答案要点：** 配对保持场景、seed 和未被替换的层级身份一致，将差异定位到指定扰动或层替换。当前 3 个 seed 的数值轨迹完全相同，因为模型没有随机动力学；因此它们是三个实验身份，却不是三个独立统计样本。

**需要记住的身份：**

- 100 tick baseline：`mgba-66654d1710f94556`；
- history digest：`7edbf3b897983ae4d24e1537bcc6b6d8850f3933adfeb6cc78b215c56d1350dc`；
- WP8 matrix：`matrix-7da4137aa39d5122`；
- baseline 结局：`FAILED`；
- `l2_static` 在当前模型中效应最大，但不等于更真实。

## 10. 科学表述防线

对下列问题必须能直接回答“不能”，并说明缺少什么证据：

1. 当前结果是否证明了数字生命？
2. 是否证明了涌现？
3. 是否可以做药物、疗效或临床预测？
4. 是否证明了 STEN 或 GNN 对表型有帮助？
5. 三个 seed 是否支持 p 值和置信区间？
6. `FAILED` 是否说明架构失败？

最后一题的要点：`FAILED` 是冻结 L4 阈值下当前参数轨迹的结局，不是软件执行错误。它恰好证明系统能保留负面结果并通过消融定位敏感层级。

## 11. 十分钟人工演示

1. 执行 `python scripts/mvp_demo.py --mode full --artifact-root artifacts/manual-acceptance`。
2. 指出输出中两个 experiment ID、history digest、matrix ID 和 report 路径。
3. 打开 `report.html`，解释 `repair_kd_000` 的 L0→L4 衰减路径。
4. 指出 `l2_static` 和 `l3_static` 对损伤/稳态的不同影响。
5. 说明 report 为什么只信任 raw JSON，以及为什么删除 `derived/report/` 后可以重建。

## 12. 人工验收记录

以下项目由用户手动勾选，AI 不代填：

- [ ] 我能不借助“AI 这么写”解释项目核心。
- [ ] 我能说明 L0–L4 各层的输入、输出、公式和简化假设。
- [ ] 我能说明为什么不存在跳层主生成流。
- [ ] 我能解释多速率时钟、checkpoint 和当前两条快反馈。
- [ ] 我能解释 WP8 的同 seed 配对、层效应和 `FAILED` 基线。
- [ ] 我能明确列出 E3–E5、有效随机重复、L4 反馈和外部校准等未完成项。
- [ ] 我亲自运行过 full demo 并检查过一份 raw run 与 report manifest。

验收人：____________  
日期：____________  
结论：通过 / 需要继续学习
