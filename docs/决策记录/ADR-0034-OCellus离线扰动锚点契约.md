# ADR-0034：OCellus 离线扰动锚点契约

- 状态：契约与验证器已接受并实现；OCellus 代码/权重推理待公开、许可、预算和逐条授权
- 日期：2026-08-25
- 影响范围：生成链外 L0/L1 扰动预测评估和待人审 L0 schedule 候选
- 不影响：确定性 GRN、粗粒度 L1、runner、在线依赖、冻结基线和真实数据 Target

## 1. 背景与准入判断

OCellus 的基因表示和 PPI GNN 未来可能成为扰动假设来源，但当前论文是 bioRxiv v1，代码、权重、GNN 和 Agent 仍待公开。本阶段不能下载、猜测或重现未公开模型，只能先冻结一个可移除的离线评估边界。

该能力锚定 L0/L1：它不替换层模型，而是比较“外部模型预测的 gene-level log2FC”与真实 Perturb-seq target，再投影为六个抽象 L0 代理。它回答 OCellus 是否在 held-out 数据上优于透明基线；失败不改变任何生成模型。

## 2. 身份与输入门禁

新增 `mgba.ocellus_anchors`，artifact schema 为 `mgba-ocellus-perturbation-anchor-0.1`。构建前必须提供：

- empirical source 的 dataset/version/SHA-256/license/rights；
- OCellus model/version/weights SHA-256/license/rights，且明确 `offline_inference: true`、`network_used: false`；
- 本地 Hallmark collection/version/SHA-256/license/rights；
- cell background、control state、dose、timepoint、KO gene 和显式 split；
- 分栏保存、同一 gene universe 的 `predicted_gene_log2fc` 与 `empirical_gene_log2fc`。

任何缺失身份、未核验许可、网络推理、非有限值、重复 observation、预测/真值 gene universe 混淆，均 fail-closed。模块只接收已经离线生成的数值，不含下载器、模型加载器、PyTorch、Qwen 或 runner import。

## 3. 六节点桥与对照

复用 `data/aivc/README.md` 中的冻结 Hallmark 代理：p53/UV→损伤，NF-κB/KRAS/IL6-JAK-STAT→信号，DNA repair→修复，OXPHOS/glycolysis→代谢，apoptosis→死亡，TGF-β→弱负反馈代理。每节点先取多个集合的去重基因并集，再对可见 gene-level log2FC 做无权均值；任一节点无覆盖即拒绝。

split unit 固定为 `context_id + knockout_gene`，train 与 holdout 不能重叠。透明基线只从 train empirical 六节点向量计算质心，并原样用于 train/holdout；不得读取 holdout 来拟合基线。

主指标为六节点 MAE，次指标为节点方向一致率和 Spearman。第一版通过规则只允许：holdout OCellus MAE 严格低于 train-only centroid baseline（实现以 `improvement > 1e-12` 作为浮点确定性护栏判定"严格低于"，build 与重算验证器共用同一 `_EPSILON`。）次指标完整保存但不在观察后加入通过规则。无论通过或失败，逐记录 prediction、empirical target、baseline、coverage、metrics 和 split 汇总都 write-once 保存；验证器从 gene-level 字段重算桥、指标、质心、decision 和 digest。

## 4. Schedule 候选的人审边界

通过 anchor 也不能进入 tick。只有以下条件同时成立，才可生成 `mgba-l0-perturbation-review-candidate-0.1`：

- 引用 holdout observation；
- 人工批准精确 `anchor_digest`，留下 reviewer 和理由；
- 人工显式给出抽象节点、目标 Cell、L0 时钟 tick 和 `[0,1]` clamp。

输出的 `perturbation_schedule` 与 runner 现有映射兼容，但固定 `executed: false`。gene-level log2FC 不会被自动换算为 clamp；候选仍须由人纳入正式、预注册的 L0 实验。OCellus 不直接调用 runner、不绕过 L1，也不能修改 GRN 参数。

## 5. 当前结果、未采用方案与回退

当前只有合成 fixture 的契约证据，没有 OCellus 权重、真实预测或外部验证结果，不能宣称模型优于 centroid、能预测治疗或描述单细胞时序动力学。论文的 pseudo-bulk top-DE 任务不等于 M-GBA tick 动力学，自然语言解释也不作为 GNN 机制忠实性证据。

未采用在线 API、统一 Qwen 主干、核心包深度学习依赖、预测充当真值、自动 schedule 执行和失败后扩参。未来权重公开后仍须先核验许可、磁盘预算并获得用户授权，在独立环境执行同 split、同指标对照。

删除 `ocellus_anchors.py` 及独立 artifacts 即可回退。L0/L1、PerturbationSchedule、真实 Target 和冻结实验不依赖本模块。

## 6. 验证

测试覆盖许可/SHA-256/模型身份、Hallmark 完整覆盖、prediction/empirical 分栏、train/holdout 泄漏、train-only centroid、MAE/方向/Spearman、负面结果保存、严格 schema、篡改后重算拒绝、write-once，以及只有“通过 + 精确人审 + holdout”才生成未执行且 runner-compatible 的 schedule 候选。
