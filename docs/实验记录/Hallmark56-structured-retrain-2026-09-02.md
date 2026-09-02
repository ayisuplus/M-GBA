# Hallmark 结构化目标重训实验记录（ADR-0046）：KD 主臂 failed，KD 可学性钉死

- 日期：2026-09-02
- 契约：`docs/决策记录/ADR-0046-Hallmark结构化目标重训契约.md`（计算前预注册）
- 靶标：`replogle-kd-hallmark-target-33eba3f656c18adb` / `norman-hallmark-target-7046ba6157559791`（各 56 维 = 50 个 Hallmark 集合维 + 冻结六节点并集头；两臂零集合因零覆盖被剔除）
- 评估：KD 主臂 `hallmark-training-eval-d6549b41f73ad50c`；OE 描述臂 `hallmark-training-eval-30997ad89ff86614`（均已登记 registry）
- 模型级别：`reference model`；**KD 主臂 verdict：failed（冻结规则）；OE 臂 verdict：descriptive（不产生 pass 主张）**

## 1. 协议执行

- 构建期门禁：两臂每单元六节点头与 profile 的 `six_node_vector` 逐维差 ≤1e-12（构建零超差）；角色逐字继承 profile 冻结拆分，未重切。
- 覆盖：KD 1,780/1,832（52 个映射缺失单元 fail-closed 剔除，与 ADR-0040 artifact 一致）；OE 226/236（剔除 10，与 ADR-0040 `norman-emb-predictions.json` artifact 的 `covered_units: 226 / excluded_units: 10` 逐位一致；计划与 ADR-0040 记录正文所写"OE 229/236、剔除 7"与该 artifact 不符，以冻结 artifact 为准，见 §5）。
- 质心 1e-12 交叉核验（全量 train 行重算 vs artifact 内嵌值）：KD 6.2e-17、OE 2.8e-17。
- 确定性双跑：两臂预测 JSON 与 `.npz` 权重 SHA-256 两跑完全相同（KD 预测 `ec6fc23f…`、权重 `6516f046…`；OE 预测 `8ae09409…`、权重 `1674d1bb…`），`.tmp/hallmark56-determinism/` 已删除。
- 训练损失（末态 MSE）：KD 7.592e-04；OE 2.686e-04。

## 2. 结果（冻结通过规则，六节点头）

KD 主臂（holdout n=354）：

| 预测器 | MAE | 方向一致率 | Spearman |
|---|---:|---:|---:|
| centroid | 0.014819 | 0.627 | 0.335 |
| ridge | 0.014181 | 0.628 | 0.317 |
| MLP | 0.014219 | 0.636 | 0.333 |

margin：+0.0006005（过质心）/ **−0.0000374（未过 ridge）** → **failed**

OE 描述臂（holdout n=46；仅描述，不进通过判定）：

| 预测器 | MAE | 方向一致率 | Spearman |
|---|---:|---:|---:|
| centroid | 0.012572 | 0.714 | 0.820 |
| ridge | 0.010691 | 0.808 | 0.862 |
| MLP | 0.011287 | 0.783 | 0.834 |

margin：+0.001285 / −0.000596 → `descriptive`（字段为冻结字面量；margin 如实报告）。

train 侧（描述）：KD ridge 0.013453 < MLP 0.015847 < centroid 0.017166（n=1,426）；OE ridge 0.008152 < MLP 0.008273 < centroid 0.013506（n=180）。MLP 在 train 上也不优于 ridge——不是过拟合形态。

集合维描述性均值 MAE（50 维，不进门控）：KD holdout centroid 0.016998 / ridge 0.016874 / MLP 0.016516；OE holdout 0.014166 / 0.012426 / 0.012871。描述性观察：KD 上 MLP 的集合维误差略低于 ridge，但六节点头相反；OE 上 MLP 两侧均不优于 ridge。

## 3. 历史对照（核验锚，逐维等价性核验）

- **ridge 六节点头 holdout MAE 与 ADR-0040 逐位一致**：KD 0.014181388150748738 = ADR-0040 的 0.014181388150748738（差恰为 0，预注册容差 1e-6）；OE 0.010690561525935232 同样逐位一致。方向/Spearman 亦逐位一致（0.628060/0.317191；0.807971/0.862112）。56 维扩展没有移动逐维独立的闭式基线——构建与聚合路径无漂移。
- **质心六节点头 holdout MAE 实测 0.014819327207889445**，与 ADR-0046 §3.5 计算前预注册的确定性推导值完全一致（全量 train 质心 × 354 覆盖 holdout）。与 ADR-0039 的 0.014820588320777628 差 1.26e-6（同一质心向量、评估集 367 vs 354 之差）；与 ADR-0040 的 0.014804580121758868 差 1.5e-5（同评估集、但 ADR-0040 用覆盖-train 质心）。定义差异已预注册，非构建缺陷。
- 计划原引对照值 0.014821/0.014418 经核算为 ADR-0039 one-hot 臂数值（367 全量 holdout；该臂 ridge 已结构退化，方向/Spearman 均为 0.0），**不是**本臂的逐维等价参照；正确参照为同特征同覆盖的 ADR-0040 嵌入臂。该偏差按"超差须调查而非静默通过"条款在计算前调查并写入 ADR-0046 §3.5，此处如实对照。

## 4. 结论（reference-model 级）

- **结构化监督未恢复 KD 可学性**：把监督目标从六节点升级为 50 Hallmark 集合 + 并集头后，KD 主臂 MLP 在冻结通过规则下仍 failed（六节点头不优于 ridge，margin −3.7e-05；train 侧同样不优于 ridge）。结合 ADR-0039（one-hot 结构退化）与 ADR-0040（基因语义空间近似线性），KD 单敲低响应在 1,832 单元规模下的可学性按记录正式**关闭**：更强特征（ADR-0040）与更结构化目标（本 ADR）两条药方均已执行并证伪。
- 按规则：不生成 KD 响应表、不进链路。接链（若未来 passed）仍须另立 ADR（ADR-0037→0038 先例）。
- 下一方向（各需独立 ADR，不在本阶段）：B1 Tahoe 完整单板可行性核查（ADR-0035 授权额度内，网络依赖）或 B2 rpe1 跨背景复核。

## 5. 协议守卫记录

- **OE 剔除计数调查**：计划预期 OE=7，实测 10。核查确认 ADR-0040 的冻结 predictions artifact 即为 covered 226 / excluded 10（同一张嵌入表，SHA-256 `34785e7a…` 不变），记录正文"229/236"系 prose 笔误；本阶段与冻结 artifact 逐位一致，无构建缺陷。KD=52 与预期一致。
- **源码指纹迁移（ADR-0045 门禁的既定更新通道）**：新增 `hallmark_targets.py` / `hallmark_training_evaluation.py` 使 `src/mgba` 源码树指纹移动，单 tick ID `mgba-824e1bade49a7fc3` → `mgba-4437aaca98878890`、100 tick ID `mgba-98f5aeecf88e3d9e` → `mgba-46de31d8b18fd252`、100 tick history digest `0dff4544…` → `16235a28…`。数值 trace digest `20f95784…` 与 WP8 `matrix-7da4137aa39d5122` 不变，证明五层运行时零行为漂移。按冻结门禁自身条款（deliberate change + 新 ADR + 文档同步）更新期望常量：`tests/test_frozen_identity.py`、`test_multiscale.py`、`test_closed_loop.py`、`test_e3_statistics.py`、`test_neural.py`、`test_demo.py` 与 `scripts/mvp_demo.py`；registry 计数守卫按注释约定 14→18；`artifacts/mvp-demo/`（git-ignored 生成物）已在新身份下重新生成（full demo 通过，结局仍 `FAILED` 负面基线）。
- 评估器修正（实现期发现并修复）：`write_json_once` 的 canonical sort_keys 落盘使 artifact 内 dict 键序为字母序，loader 原按 dims 顺序校验键序会在真实 artifact 上误报——改为键集合校验、按 dims 顺序取值；评估器对预测契约中 `excluded_units` 的核验允许为 0（与 ADR-0040 评估契约的非负语义一致）。两处均为 loader/validator 修复，不影响任何 artifact 数值。
- 门禁状态：pytest 全套 605 通过（基线 568 + 新增 37，零失败）；`mgba data-check` 绿色（18 条目）；`mgba run --config configs/multiscale_demo.json` 与 `mgba sten-smoke --config configs/demo.json` 绿色；coverage 总量 91%（12,651 语句；新模块 hallmark_targets 84%、hallmark_training_evaluation 86%，缺行均为防御性 raise 分支）。
- 权重 `models/replogle_kd_hallmark_mlp.npz` / `models/norman_hallmark_mlp.npz` 不入 Git、不进运行时（`models/` 已在 .gitignore）。
