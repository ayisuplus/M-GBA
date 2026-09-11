# ADR-0049：OE 成分外推边界契约（component-disjoint 重分层判决）

- 状态：实验已完成——判据不成立（failed），OE 成分外推方向按 §4 正式关闭（2026-09-11；契约于计算前预注册）
- 日期：2026-09-11
- 影响范围：生成链外确认性评估；新脚本落 `scripts/`，产物落 `artifacts/extrapolation-boundary/`，实验记录落 `docs/实验记录/`
- 不影响：ADR-0001–0048 全部冻结产物与身份、五层契约、核心零依赖、参考基线；`src/`、`tests/`、`configs/`、已有 `artifacts/` 一律不修改；本 ADR 不做接链、不撤销任何历史 verdict（含 ADR-0037 passed——本实验只标定其外推证据边界）

## 1. 背景与准入

ADR-0037 是项目唯一通过的 ML 结果：Norman OE 236 单元六节点扰动响应，holdout MLP MAE 0.009494280866924337，双胜质心（0.012872174640087454）与 ridge（0.012279782258477557）。事后重分层诊断发现：该优势集中在"组合成分全部在训练单元中出现过"的 holdout 单元（插值区）；在成分全部未见的 10 个 holdout 单元上 MLP 0.013225 不优于质心 0.012533——ADR-0037 的 passed 疑为**插值证据而非外推证据**。

本 ADR 在任何计算之前，预注册一个确认性判决实验：用与 ADR-0037 逐位相同的训练（同一 split、同一特征、同一超参），只把评估按"成分是否全部在训练中出现过"重分层，回答一个问题——**MLP 在成分未见的 holdout 单元上是否仍双胜两个透明基线**。这与 ADR-0047 的 No-Go 不冲突：0047 关闭的是"低秩交互模型 × 四细胞背景"路线，本实验测的是更弱的"单背景（K562）OE 成分外推"。

六问：L0 层外评估（不改任何层模型与 runner）；增强对象为 ADR-0037 主张的证据边界；研究问题为"单背景 OE 成分外推是否成立"；指标与通过规则见 §3（成分未见层上的六节点 MAE 双胜门禁 + 1e-6 对照锚）；失败保留负面结果并按 §4 关闭方向；分层规则、判据阈值、对照锚、schema 全部计算前冻结。

## 2. 冻结事实（输入锚）

- profile `data/aivc/derived/norman-perturbation-profile.json`（SHA-256 `35860c026c11968ec84036810f8f7c04d31096e143de494a99bf22640afe318a`，236 单元，train 188 / holdout 48，salt `mgba-aivc-norman-anchor-2026-08-28`）。split 身份逐字复用 ADR-0036/0037：本实验**只重分层，不改 split 成员**；脚本加载时用 `assign_splits` 重算并逐单元对拍 profile 的 `role` 字段（不一致即 fail-closed）。
- ADR-0037 历史结果（对照锚，非本实验产物）：全量 holdout 48 单元六节点 MAE 质心 0.012872174640087454、ridge 0.012279782258477557、MLP 0.009494280866924337。
- ADR-0037 冻结训练配置（逐字沿用）：特征 = 全 236 单元成分词表的 one-hot 均值 + combo 标志；SEED=42（torch+numpy）、HIDDEN=32、Adam lr=1e-3、weight_decay=1e-4、MSE 全批量、EPOCHS=3000、CPU 单线程（`torch.set_num_threads(1)`）、ridge λ=1.0 闭式无截距、质心 1e-12 交叉核验、PASS_EPSILON=1e-12。
- 训练管线锚：`scripts/train_l0_perturbation_response.py`（ADR-0037 原始脚本）；`scripts/train_l0_label_shuffle_control.py`（ADR-0048 对照 1，同骨架的打乱版）已验证该管线双跑字节级一致、完整 3000 epoch 实跑约 3.4 秒。

## 3. 冻结协议

### 3.1 重分层规则（确定性，无手工挑选）

- 成分集合：单元名按 `_` 切分（与 ADR-0037 特征编码同规则），单元 u 的成分集合 `parts(u) = tuple(u.split("_"))`。
- 训练成分词表：`train_vocab = sorted(⋃ parts(u) for u in 188 个 train 单元)`（train 成员由冻结 split 决定，profile 顺序遍历）。
- 分层标记（对每个 holdout 单元，确定性、无随机数）：
  - **component-seen（插值层）**：`parts(u)` 中每个成分都 ∈ `train_vocab`。
  - **component-unseen（外推层）**：`parts(u)` 中**至少一个**成分 ∉ `train_vocab`。
- 描述性子层（只报告、不进门控）：`all-components-unseen` = `parts(u)` 中**全部**成分 ∉ `train_vocab`；单基因 holdout 单元的成分未见情况单列计数。
- 全部 236 单元的成分集合、分层标记、train_vocab 成员资格逐单元写入产物，供第三方复算。

### 3.2 训练（仅 `.venv-train`，与 ADR-0037 逐位相同）

- 脚本 `scripts/train_l0_component_disjoint.py`：加载、特征编码、质心交叉核验、ridge 闭式解、MLP 训练循环与 ADR-0037 原始脚本逐行同构；**唯一差异**是评估段按 §3.1 分层并逐单元输出。无任何标签打乱、无特征修改、无超参修改、不降 epoch。
- 质心 1e-12 交叉核验保留（训练与 ADR-0037 相同 ⇒ 必须仍通过；不通过 = 脚本缺陷，停手调查）。

### 3.3 判据（预注册，不因结果调整）

令 U = component-unseen holdout 子集，n = |U|。逐层六节点 MAE = 该层全部 (单元 × 6 节点) 绝对误差的均值。

- 若 **n < 8**：判据自动记 **`insufficient`**（证据不足），不记 failed；分层统计原样登记，OE 外推方向保持"无确认性证据"状态，不据此关闭也不据此扩展。
- 若 n ≥ 8：MLP 六节点 MAE 同时严格低于质心 **且** 严格低于 ridge（两处 margin = 基线 MAE − MLP MAE 均 > 1e-12）→ **`passed`**；否则 **`failed`**。
- component-seen 层与 all-components-unseen 子层的 MAE 与 margin 只作描述性报告，不进门控。

### 3.4 对照锚（防管线漂移，预注册核验期望）

同一实现、同一 holdout 全集（48 单元）重算 ADR-0037 三模型六节点 MAE，必须与 §2 历史值逐一在 **1e-6** 内吻合（质心 0.012872174640087454、ridge 0.012279782258477557、MLP 0.009494280866924337）。任一超差 = 管线漂移或实现缺陷，**停手调查**，分层判据结果不得先行登记。

### 3.5 确定性与双跑核验

产物写入前连跑两遍（独立输出目录），results.json 与 weights.npz 的 SHA-256 两跑完全相同（np.savez 固定时间戳先例，ADR-0037/0048），临时第二跑目录随后删除；不一致即停手调查。

## 4. 早停与诚实登记规则

- 判据 `failed` → OE 成分外推方向**正式关闭**，与 KD（ADR-0039/0040）并列登记为证伪关闭方向，永久回归 evidence-governed 软件路线；ADR-0037 的 passed 不撤销，但其证据等级登记为"插值证据"。
- 判据 `passed` → 仅登记为"**有限外推证据**"（单背景、单 split、n 个成分未见单元），不接链、不扩展、不升级任何历史主张的证据等级。
- 判据 `insufficient` → 如实登记子集过小，不作方向性结论。
- **不得**为使判据成立而调整分层规则、阈值、split 或超参；负面结果原样登记——这正是本实验要的确定性答案。

## 5. 产物 schema（`mgba-extrapolation-boundary-0.1`）

产物目录 `artifacts/extrapolation-boundary/`：

- `results.json`：schema_version、adr="ADR-0049"、created_date、inputs（profile 路径+SHA-256+角色、原始训练脚本锚）、stratification（规则逐字记录、train_vocab 大小、逐单元明细：unit、role、components、stratum、all_components_unseen、单基因标志）、anchors（质心交叉核验偏差、对照锚三模型全量 holdout MAE 重算值、与历史值逐项偏差、1e-6 容差核验通过标志）、training（冻结超参逐字段、final_train_loss_mse、torch 版本）、per_unit（每个 holdout 单元三模型逐单元六节点 MAE）、strata（component-seen / component-unseen / all-components-unseen 各层的单元数、三模型 MAE、margin）、criteria（§3.3 判据文本逐字拷贝）、verdict（passed / failed / insufficient）、scientific_boundary（"确认性边界判决：标定 ADR-0037 主张的外推证据边界；不构成任何生物主张，不撤销历史 verdict，passed 也仅登记为有限外推证据、不接链"）。
- `weights.npz`：MLP 权重（np.savez，字节确定）。
- `manifest.json`：同一 schema 族，登记 results.json、weights.npz、脚本、profile 的 SHA-256 与字节数，并记录 determinism（双跑各自 SHA-256 与 byte_identical 标志；manifest 最后写入以避免自引用）。

## 6. 未采用方案与回退

未采用：重新 split 或按成分重切拆分（破坏与 ADR-0037 的逐位可比性，split 身份冻结于 ADR-0036）；改特征或超参（本实验唯一变量是评估分层）；Geneformer 768-d 嵌入臂（ADR-0040/0046 已记录该特征族结论，且引入第二变量）；对 component-seen 层设门禁（插值层已被 ADR-0037 覆盖，诊断价值在外推层）；抽样成分子集（全枚举免随机性）。回退：删除脚本、`artifacts/extrapolation-boundary/`、实验记录与本 ADR 即可；核心链与全部历史 artifact 不变。

## 7. 验证

- 训练前：本 ADR 已冻结分层规则、判据阈值（含 n<8 → insufficient 分支）、对照锚与 schema；脚本只在 ADR 接受后编写运行。
- 运行：质心 1e-12 交叉核验通过；对照锚三值与 ADR-0037 历史值逐项 ≤1e-6；逐单元分层标记确定性复算一致。
- 确定性：results.json 与 weights.npz 双跑 SHA-256 完全相同（manifest `determinism.byte_identical = true`）。
- 登记：verdict ∈ {`passed`,`failed`,`insufficient`} 原样写入产物、实验记录与本 ADR §8；阶段完成不以 passed 为条件——预注册的诚实负结果是合法交付物。

## 8. 结果段（2026-09-11 计算完成后如实填写）

实验完成，双跑字节级一致（manifest `determinism.byte_identical = true`；results SHA-256 `8da7e65b…6290`，weights SHA-256 `1d5ba70f…1389`，临时第二跑目录已删除）。实验记录：`docs/实验记录/OE成分外推边界-2026-09-11.md`。

- **分层统计**：train_vocab 95 成分；holdout 48 单元 = component-seen 37 + component-unseen 11（ARID1A、CITED1、CKS1B、EGR1、FOXO4、IER5L、LYL1_IER5L、MAML2、MIDN、PTPN1、RREB1；其中 10 个单基因成分全部未见、1 个组合 LYL1_IER5L 部分未见）。n = 11 ≥ 8，不触发 insufficient 分支。
- **判据层结果**：component-unseen 层六节点 MAE 质心 0.012213936050950084、ridge 0.019118529463066355、MLP 0.012717192518673622；margin 对质心 **−0.0005032564677235375**、对 ridge +0.006401336944392733。双胜 >1e-12 不成立 → **verdict = failed**。
- **判据结论**：OE 成分外推方向按 §4 **正式关闭**，与 KD 方向（ADR-0039/0040）并列登记为证伪关闭，后续永久回归 evidence-governed 软件路线。ADR-0037 的 passed 不撤销，其证据等级登记为"插值证据"（双胜优势由 component-seen 层承载：该层 margin +0.004531749250183 / +0.001710523254223）。描述性子层 all-components-unseen（10 单元）MLP 0.013224552458336297 亦不优于质心 0.012533444116126090，与事前重分层诊断一致。
- **对照锚核验**：全量 holdout 48 单元重算三模型 MAE 与 ADR-0037 历史值逐项偏差 0.0 / 0.0 / 0.0（容差 1e-6），管线零漂移。
- **附带观察（描述性）**：ridge 在外推层退化至 0.0191（差于质心），MLP 对 ridge 的正 margin 主要反映 ridge 退化而非外推能力；双胜门禁两腿在外推层不对称，与 ADR-0048 对照 1 记录的腿级边界同型。
- 训练核验：质心交叉核验偏差 0.0（< 1e-12）；final train loss 5.7523258874425665e-05；冻结超参逐字段与 ADR-0037 一致，无任何调整。
