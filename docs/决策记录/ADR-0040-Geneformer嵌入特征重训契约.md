# ADR-0040：Geneformer 基因嵌入特征的扰动响应重训契约

- 状态：契约已接受（2026-08-29，计算前预注册）
- 日期：2026-08-29
- 影响范围：生成链外训练评估；产物落 `data/aivc/derived/`、`models/`、`artifacts/`
- 不影响：ADR-0036–0039 全部冻结产物与身份、五层契约、核心零依赖、参考基线

## 1. 背景与准入

ADR-0039 的 KD 训练按冻结规则失败，记录在案的结构根因：1,832 个单敲低单元的身份 one-hot 无跨单元共享结构。本 ADR 冻结修复路径：用 C1 Geneformer V2-104M_CLcancer 的**输入 token 嵌入表**作扰动基因特征（纯查表，无推理前向），重训同一任务。六问：L0 层外评估（不改层模型）；增强对象为 ADR-0037 任务的特征编码；研究问题为"基因语义嵌入是否使 KD 响应可学"；指标与通过规则与 ADR-0037/0039 完全相同；失败保留负面结果；全部映射与覆盖规则计算前冻结。

## 2. 冻结事实（已盘点 C1 文件）

- 权重 `Geneformer-V2-104M_CLcancer/model.safetensors`：202 张量；嵌入表 `bert.embeddings.word_embeddings.weight` [20,275 × 768]（SHA-256 `82773813…4357`，与 HF X-Linked-ETag 一致）。
- 映射链：扰动基因 symbol → `gene_name_id_dict_gc104.pkl` → Ensembl → `token_dictionary_gc104M.pkl` → token id → 嵌入行（768 维）。
- 覆盖规则：任一映射步骤缺失即从本任务**排除**该单元（fail-closed，覆盖数写入报告）；组合单元取成分嵌入均值（仅 OE 臂存在组合）。
- 提取产物 `mgba-gene-embedding-table-0.1`：纯查表（不跑模型前向），含全部源文件 SHA-256 与"input token embeddings only"声明。

## 3. 冻结协议

- 任务与 ADR-0037 相同：单元 → 六节点 log2FC；特征 = 768 维基因嵌入（+ 组合均值池化）。
- 数据集两臂：**KD 主臂**（Replogle profile，salt `mgba-aivc-replogle-kd-anchor-2026-08-29`，与失败 run 同盐可比）与 **OE 描述臂**（Norman profile，salt 沿用 Stage 1，与通过 run 同盐可比；仅描述性，不进通过判定）。
- 超参与 ADR-0037 逐字相同：MLP 768→32 tanh→6；Adam lr 1e-3、weight_decay 1e-4、MSE、全批量 3000 epoch、种子 42、CPU 单线程；ridge λ=1.0 闭式（嵌入特征下无退化）。
- 通过规则不变：holdout MAE 严格低于质心与 ridge（margin >1e-12）；方向/Spearman 只报告。
- 评估契约：`mgba-l0-response-predictions-0.1` 增加按 `feature_encoding` 分派的键集（`identity-onehot` 旧键集不动；`geneformer-embedding` 携带嵌入表 digest/维度/覆盖数），未知编码 fail-closed；核验段其余逻辑不变。

## 4. 接链条件（仅在 passed 时）

KD 臂 passed 才允许：构建 KD 响应表（ADR-0038 门禁）→ 运行 KD 配对实验。实验配置差异冻结：参考臂硬钳制映射节点到 **0.0**（KD），经验臂 dose 1.0；单元选择规则同 ADR-0038 同族（train ∧ 单基因 ∧ 桥并集 ∧ 最多细胞 ∧ 字典序），在 KD 表生成后确定性计算。配置装载新增 `reference_value` 键分派（存在即新类；缺失则 ADR-0038 v0.1 行为逐位不变）。

## 5. 未采用方案与回退

未采用：跑 Geneformer 前向取细胞嵌入（任务只需基因身份特征）、微调 104M 模型（236–1,832 样本欠定）、改 KD 失败 run 的通过规则追认、借 holdout 选特征。回退：删除嵌入表、预测、评估与本 ADR 产物；既有链路与冻结实验不受影响。

## 6. 验证

测试覆盖：嵌入表提取的门禁与确定性（合成 safetensors fixture）、映射缺失排除规则、组合均值池化、评估契约双编码分派、通过/失败分支、KD 实验配置分派（v0.1 不变性）、write-once、CLI 往返；既有全套测试与 `mgba data-check` 绿色。
