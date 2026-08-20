# ADR-0013：L2 主动推理（Active Inference）Cell 策略

> 状态：Accepted
> 日期：2026-08-20

## 背景

1. MVP 计划为 L2 预留的升级槽位是"ML policy、RL、轻量 LLM"，核心原则 §3 L2 规定规则基线必须长期保留，LLM/ML 只能作为 `CellModel` 协议的实现，不改变五层协议。当前五态规则状态机是阈值优先级策略：它不评估候选行为的后果，只按固定顺序触发。
2. 2024–2026 前沿调研（检索时间 2026-08-20）：
   - 离散时间主动推理的标准化数学表述已经成熟：van Oostrum, Langer & Ay, *A Concise Mathematical Description of Active Inference in Discrete Time*, arXiv:2406.07726v4（2025 修订）给出策略后验 $P(\pi)\propto\sigma(-\gamma G(\pi))$ 与预期自由能的风险—歧义分解；配套极简 Python 实现（jessevoostrum/active-inference，兼容 pymdp）。
   - EFE 的形式等价性与规划—变推断统一：Sweeney et al. 2025（PMC12840411）；*Expected Free Energy-based Planning as Variational Inference*, arXiv:2504.14898（2025）；价值—信息权衡综述 arXiv:2408.06542（2024）。
   - 多尺度形态发生与集体智能的主动推理框架：Friston/Levin 谱系的 morphogenesis 模拟（变分自由能跨尺度最小化）、Kaufmann et al. *An Active Inference Model of Collective Intelligence*（2021，2024 年持续被引）；Pio-Lopez et al. 2022 将其用于细胞命运与精神病学计算模型。
   - 开源生态：pymdp（ActiveInferenceInstitute 维护，2026 年仍在更新）是离散 AIF 的事实标准实现；其优势是矩阵化的 A/B/C/D 生成模型与 EFE 策略评估，劣势是依赖 numpy/scipy 且面向神经科学实验范式，不能直接进入本项目零依赖热路径。
3. 结论：融合 pymdp 的矩阵化离散生成模型结构（A/B/C/D 四元组）与 arXiv:2406.07726 的风险—歧义 EFE 分解，用纯标准库实现一个确定性 `CellModel`：`ActiveInferenceCellModel`。它不采样（确定性 argmin + 配置化平局优先级），因此满足项目"显式种子/可复现"不变量。

## 决定

1. 新增 `mgba.layers.l2_active_inference.ActiveInferenceCellModel`，实现既有 `CellModel` 协议；`configs/layers/l2_active_inference.json` 为独立冻结配置。规则状态机 `CellStateMachineModel` 与静态基线 `StaticCellModel` 不做任何修改。
2. 生成模型四元组（全部离散、闭式、确定性）：
   - 隐状态与观测均为五相集合 $S=O=\{$quiescent, activated, repairing, stressed, dead$\}$；
   - 似然 $A(o|s)$：相位保真矩阵（配置冻结）；
   - 转移 $B_a(s'|s)$：五个候选动作 $a\in\{$quiesce, activate, repair, stress-response, apoptose$\}$ 各一张行随机矩阵，由 L1 驱动量（修复能力、死亡效应器、代谢能力）与局部环境（压力、资源、传入信号）按冻结公式构造；
   - 先验 $D(s)$：上一状态相位点质量（首 tick 均匀）；
   - 偏好 $C(s)$：相位效用向量的 softmax（配置冻结），不含任何 L4 指标——偏好是层内冻结常数，不是从宏观表型反写的"上帝参数"。
3. 感知（状态推断）：细胞由四个内感受标量 $x=(\text{stress\_load}, \text{activation\_drive}, \text{repair\_drive}, \text{death\_drive})$ 形成相位似然 $\ln A(x|s)\propto -\|x-\mu_s\|^2/(2\tau^2)$，后验 $q(s_t)\propto D(s_t)A(x|s_t)$。
4. 行动选择（预期自由能最小化）：

   $$\hat q(s'|a)=\sum_s B_a(s'|s)\,q(s_t)$$

   $$G(a)=\underbrace{\sum_{s'}\hat q(s'|a)\bigl[\ln\hat q(s'|a)-\ln C(s')\bigr]}_{\text{risk（风险）}}+\underbrace{\sum_{s'}\hat q(s'|a)\,H\bigl[A(\cdot|s')\bigr]}_{\text{ambiguity（歧义）}}$$

   $$a^*=\arg\min_{a} G(a)\quad\text{（平局按配置动作优先级确定性裁决）}$$

   即策略后验 $P(a)\propto\sigma(-\gamma G(a))$ 在 $\gamma\to\infty$ 的确定性极限；不采样、无随机源。
5. 状态簿记与规则模型同构：活力、压力负荷、激活驱动使用同一族一阶方程（AIF 配置自带速率），修复努力仅在 REPAIRING 相位非零，DEAD 为吸收态并输出凋亡动作。这保证 L3 消费的 `CellState/CellAction` 契约与规则基线完全一致，层替换实验只隔离"决策规则"这一个变量。
6. 数值安全：全部对数运算经 log-sum-exp 与 $\epsilon$ 下限保护；配置构造时做有限性/值域/随机性（行和为 1）校验，非法输入 fail-fast。
7. 新增 `mgba policy-experiment` CLI 与 `mgba.policy_experiments`：同场景同种子配对运行 `rule_policy`（规则状态机）与 `active_inference_policy`（AIF）两个 runner，复用 WP8 的 `_compare_runs` 逐层距离、L4 有向差值与首次传播 tick，保存 raw/derived artifact。这是 E2 层替换协议的 L2 政策维度实例。
8. 新增 `scripts/synthetic_policy_benchmark.py`：复用 `synthetic_feedback_benchmark.generate_dataset` 的确定性场景集，对每个场景运行规则 vs AIF 对照并汇总 CSV/JSON。

## 结果

- L2 第一次拥有"评估候选行为后果再行动"的推理型策略，且规则基线原样保留：二者共享 L1 驱动语义，差异只来自决策规则，E2 式消融可以定位决策层贡献。
- 默认 `mgba run` / `simulate` / 冻结矩阵不使用 AIF 模型；无注入时所有 0.2.0 身份位级不变。
- AIF 参数未经拟合；对照结果（无论哪个策略占优）都是 reference model 内的诊断证据，不构成"主动推理更生物真实"的宣称。科学等级不变（contract demonstrator / reference model）。

## 回退

删除 `mgba/layers/l2_active_inference.py`、`policy_experiments.py`、对应配置/CLI/测试/脚本与文档条目即可回到 ADR-0012 状态；规则状态机与全部冻结基线不依赖本次新增代码。
