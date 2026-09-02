# ADR-0046：Hallmark 全集结构化目标的 KD/OE 重训契约

- 状态：契约已接受（2026-09-02，计算前预注册）
- 日期：2026-09-02
- 影响范围：生成链外训练评估；产物落 `data/aivc/derived/`、`models/`
- 不影响：ADR-0036–0045 全部冻结产物与身份、五层契约、核心零依赖、参考基线；本 ADR 不做接链

## 1. 背景与准入

ADR-0040 实验记录 §3 给出记录在案的结论："OE 可学性来自组合共享成分，KD 单敲低的可学性需要更多数据或**更结构化目标**，而非更强特征。"本 ADR 执行其中的结构化目标药方：把监督目标从六节点升级为 **Hallmark 全集（≤50）+ 六节点并集头的结构化靶标**，在完全相同的数据、特征、split、超参下重训 KD/OE 双臂。

事实链：L0 OE 训练已 passed 并接链（ADR-0037/0038/0041）；KD 臂两次 failed（ADR-0039 身份 one-hot 结构退化；ADR-0040 Geneformer 768-d 嵌入修复了 ridge 退化但 MLP 不优于 ridge，结论"任务在基因语义空间近似线性"）。特征更换方向已关闭；B1 Tahoe 教学子集经实测仅 4 药 × 单剂量 × 无对照，不能支撑训练协议。

方法论核心（决定全部设计）：ridge 闭式解与质心基线对输出维逐维独立，因此 56 维基线的六节点头与同特征、同覆盖、同角色的历史六节点基线（ADR-0040 嵌入臂）**逐维等价**；唯一可能移动的只有 MLP（共享隐层）。pass/fail 直接回答"结构化监督是否恢复了 KD 可学性"，与 ADR-0039/0040 两个 failed 臂逐位可比。

六问：L0 层外评估（不改层模型）；增强对象为 ADR-0037 任务的监督目标结构；研究问题为"结构化监督是否恢复 KD 响应可学性"；指标与通过规则见 §3（六节点头 MAE 门禁不变）；失败保留负面结果；全部靶标构造与覆盖规则计算前冻结。

## 2. 冻结事实

- 双臂：**主臂** = Replogle K562 KD（bundle `data/aivc/B2-replogle2022/replogle-kd-empirical-log2fc.json`，1,832 单元 × 2,377 基因；profile `data/aivc/derived/replogle-kd-perturbation-profile.json`，train 1465 / holdout 367）；**描述臂** = Norman OE（bundle `data/aivc/A2-scperturb/norman-empirical-log2fc.json`，236 × 4,267；profile `data/aivc/derived/norman-perturbation-profile.json`，train 188 / holdout 48）。描述臂只报告、不产生 pass 主张（ADR-0040 对 OE 嵌入臂的先例）。
- Hallmark GMT：`data/aivc/A1-msigdb-hallmark/h.all.v2026.1.Hs.symbols.gmt`（MSigDB v2026.1，50 集合；SHA-256 钉死于 bundle `hallmark_source`，构建时逐字节复核）。
- 特征表：`data/aivc/derived/gene-embedding-table.json`（Geneformer V2-104M_CLcancer 输入 token 嵌入，768 维，纯查表；ADR-0040 冻结产物）。
- 历史基线（核验锚，非训练结果）：ADR-0040 KD 嵌入臂 holdout 六节点 centroid MAE 0.014804580121758868、ridge MAE 0.014181388150748738（n=354 覆盖 holdout）；ADR-0039 KD one-hot 臂 0.014820588320777628 / 0.014417835639976171（n=367 全量 holdout，ridge 已退化：方向/Spearman 均为 0）。

## 3. 冻结协议

### 3.1 靶标构造（`mgba-hallmark-target-0.1`）

- 对每个单元，靶标维 = `tuple(sorted(纳入的 Hallmark 集合名)) + ABSTRACT_GENE_NAMES`（六节点并集头固定在最后、用冻结六节点顺序）。
- 集合维 = 该集合 ∩ 数据集 gene_universe 去重后 log2fc 的无权均值（与冻结桥同一聚合规则）。
- 六节点头调用 `mgba.ocellus_anchors.aggregate_hallmark_bridge` 生成（定义级等于冻结桥）。
- 零覆盖集合（∩ universe 为空）从靶标中剔除并记录于 artifact 的 `excluded_sets`；纳入集合记录 `coverage`（每集合覆盖基因数）。
- 角色继承：单元角色逐字拷贝自对应 profile（不重新 split；profile SHA-256 记入 target 的 source）。bundle 中缺失于 profile 的单元 → fail-closed。
- **构建期门禁**：每单元六节点头与 profile 的 `six_node_vector` 逐维差 ≤1e-12，超差即 raise。
- `centroid_train_only`（D 维，target 全部 train 行均值）随 artifact 存储；因构建器不读嵌入表，质心覆盖全部 train 单元，不随训练期覆盖剔除变化。

### 3.2 特征与训练（仅 `.venv-train`）

- 特征：Geneformer 768-d 输入 token 嵌入表；组合取成分均值；成分未全解析的单元 fail-closed 剔除并计数（预期覆盖：KD 1,780/1,832、OE 229/236，与 ADR-0040 相同）。
- 冻结超参（逐字沿用 ADR-0037）：SEED=42（torch+numpy）、HIDDEN=32、Adam lr=1e-3、weight_decay=1e-4、MSE 全批量（对所有靶标维取均值）、EPOCHS=3000、CPU 单线程（`torch.set_num_threads(1)`）、ridge λ=1.0 闭式无截距、质心 1e-12 交叉核验、PASS_EPSILON=1e-12。
- 模型 `Linear(768,32)→Tanh→Linear(32,D)`，D = 靶标维数。
- 训练脚本只产出预测与权重；verdict 不在脚本内计算。

### 3.3 通过规则（仅主臂）

holdout 上 MLP 的**六节点头** MAE 严格低于质心基线**且**严格低于 ridge 基线，两处 margin 均 >1e-12 → `passed`，否则 `failed`。集合维指标只描述、不进门控。方向一致率/Spearman 只报告。描述臂 `verdict` 字段冻结为字面量 `descriptive`。

### 3.4 新 artifact schema

- `mgba-hallmark-target-0.1`：schema_version、target_id、dataset_id、dim 列表、excluded_sets、coverage、roles、centroid_train_only、units（逐单元 D 维靶标）、source{bundle_sha256, profile_sha256, hallmark_gmt}；write-once。
- `mgba-l0-hallmark-predictions-0.1`：三个预测器 centroid/ridge/mlp 的逐单元向量 + 冻结超参 + target_sha256 + embedding_table_sha256 + coverage + seed。
- `mgba-l0-hallmark-training-evaluation-0.1`：重算核验（target SHA-256、逐单元 target/role 对拍、train-only 质心重算 ≤1e-12、冻结超参逐字段比对）+ 六节点头三预测器指标 + 集合维描述性指标 + pass_rule。

### 3.5 历史对照协议（预注册的核验期望）

- ridge 六节点头 holdout MAE **必须**与 ADR-0040 嵌入臂 0.014181388150748738 在 1e-6 内吻合（逐维独立 + 同特征/同覆盖/同角色 ⇒ 数学上应近逐位一致）；超差 = 构建/聚合路径缺陷，停手调查。
- 质心六节点头 holdout MAE 期望恰为 0.014819327207889445（全量 train 质心 × 354 覆盖 holdout，计算前确定性推出）。
- 计划原引 0.014821/0.014418 经核算为 ADR-0039 one-hot 臂数值：特征空间不同（one-hot，ridge 已退化）、评估集不同（367 全量 holdout），**不是**本臂的逐维等价参照；正确参照为 ADR-0040 嵌入臂。该偏差按"超差须调查而非静默通过"条款在计算前记录于此，实验记录中如实对照两臂历史值。

## 4. 接链条件

本 ADR 不做接链。KD 臂 passed 后的接链（响应表蒸馏 + `EmpiricalResponseGrnModel`，已原生支持负 log2FC 语义）须另立 ADR（ADR-0037→0038 先例）。failed 则 KD 可学性方向按记录正式关闭，后续方向（Tahoe 完整单板可行性核查或 B2 rpe1 跨背景复核）各需独立 ADR。

## 5. 未采用方案与回退

未采用：基因级 2,377 维靶标（噪声主导，单基因 log2fc 估计在 ≥50 细胞伪bulk 下不可靠）；重新 split（破坏与 ADR-0039/0040 历史臂的逐位可比性）；one-hot 重跑（结构退化已定论，ADR-0039）；对覆盖子集重切拆分（ADR-0040 已记录此缺陷）。回退：删除新增模块（`hallmark_targets.py`、`hallmark_training_evaluation.py`）、训练脚本、4 个 derived artifact、registry 条目与本 ADR 即可；核心链与历史 artifact 不变。

## 6. 验证

- 构建：两臂 `mgba hallmark-target-build` 退出码 0，构建期 1e-12 门禁通过（六节点头复现 profile 向量）。
- 训练：确定性双跑（预测 JSON 与 npz 的 SHA-256 两跑完全相同，随后删除临时目录）；剔除计数 KD=52 / OE=7，不一致则停手调查。
- 评估：KD `verdict` ∈ {`passed`,`failed`} 且 margins 与报告一致；Norman `verdict` == `descriptive`。阶段完成不以 passed 为条件——预注册的诚实负结果是合法交付物。
- 门禁：新增手工夹具测试（56 维聚合手算对拍、六节点头桥一致性、角色/digest 门禁、零覆盖剔除、篡改 fail-closed、margin 1e-12 边界、write-once、双跑字节一致、CLI 往返）；既有全套测试、`mgba data-check`、三条最小 CLI 门禁、覆盖率 ≥80% 保持绿色。
