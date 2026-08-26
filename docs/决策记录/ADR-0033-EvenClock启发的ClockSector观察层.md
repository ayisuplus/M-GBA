# ADR-0033：EvenClock 启发的 ClockSector 空间观察层

- 状态：已接受并实现观察器；真实 Target 表示比较待数据到位后另行预注册
- 日期：2026-08-25
- 影响范围：生成链外 L3 空间观察 artifact
- 不影响：L0–L4 DTO/Protocol、空间 L3 动力学、坐标/场/边、Cell 行为、checkpoint 和 history digest

## 1. 背景与准入判断

OCellus 的 EvenClock 表示提示了一种结构化读取空间邻域的方法。它属于 L3 生成链外观察，不替换 ADR-0023 的 `SpatialCarmTissueModel`，也不回答“哪个编码更真实”。当前要回答的窄问题是：能否从正式空间状态和同 tick 可见的 L0 状态生成顺序、尺度和 checkpoint 稳定的 6×3 邻域摘要，而不回写生成链？

保留的基线是固定图 L3、空间半径邻域和 12×12 场。当前成功条件仅是观察契约与可重建性；Wu/Jackson 真实 Target 尚未到位，因此本 ADR 不比较效果、不选择赢家。

## 2. 决策

新增只读 `ClockSectorObserver`，输入为一个正式 `SpatialTissueState` 和该 tick 可见的全部 `TranscriptState`。Cell id 必须一一对齐；慢时钟下 L0 logical time 可以早于但不能晚于 L3 tick，来源时间和 digest 完整写入 artifact。

对每个 focal Cell：

1. 用全体 Cell 的“各自最近邻距离”的中位数作为无量纲尺度；单 Cell 固定回退为 1.0，重合坐标拒绝。
2. 将相对角度分到以 0°、60°、120°、180°、240°、300° 为中心的六个方向；精确角边界归入逆时针扇区。
3. 将归一化距离分到 `[0,1]`、`(1,2]`、`(2,+∞)` 三环；精确径向边界归入内环。
4. 每个邻居只携带完整、按名称排序的六个抽象 L0 节点及值；不添加真实基因名或 Cell 类型标签。

每个 focal Cell 始终显式输出 18 个 slot，包括空扇区。邻居按归一化距离和 Cell id 排序。坐标、原始距离、归一化距离、边界策略和来源身份均保存在 artifact 中，避免解释器猜测。

## 3. Artifact 与边界

独立 schema 为 `mgba-clock-sector-observation-0.1`，写入函数采用确定性 JSON 和 write-once 语义。观察器不被 runner 导入，不进入 checkpoint；它只读取已产生的状态，存在与否不能改变 trace、checkpoint 或 history digest。

该表示是无量纲 reference representation，不是物理组织坐标、空间组学重建或 EvenClock 优越性的证据。论文未提供与 M-GBA 当前半径邻域和固定网格的同预算对照，因此不预设它更好。

## 4. 真实数据到位后的门禁

Wu/Swarbrick calibration/holdout 和 Jackson external-validation Target 到位后，另立冻结评估配置，在相同输入预算下比较：

- 现有半径邻域；
- 固定网格摘要；
- ClockSector 6×3 摘要。

评估复用 ADR-0025/0027 的 calibration/holdout 分离、缺邻居/稀疏样本退化边界和生成链外指标。若 holdout 不改善，ClockSector 只保留为可视化候选，不进入 L3 模型；不得在结果出来后调整环或方向边界。

## 5. 回退与验证

删除 `clock_sector.py` 和其独立 artifact 即可回退，空间模型和所有旧 raw run 均无需迁移。

测试覆盖输入顺序不变、统一坐标缩放后编码不变、18 个空/非空 slot、精确角边界、单 Cell、来源对齐、真实空间 run 非修改，以及 checkpoint 恢复前后 artifact 字节一致。冻结 identity 门禁继续独立通过。
