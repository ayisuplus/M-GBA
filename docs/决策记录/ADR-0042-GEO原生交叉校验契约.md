# ADR-0042：Stage 1 的 GEO 原生交叉校验契约

- 状态：契约已接受（2026-08-29，计算前预注册）
- 日期：2026-08-29
- 影响范围：生成链外复核；产物落 `data/aivc/derived/` 与登记表
- 不影响：ADR-0036 Stage 1 身份与全部冻结产物；任何运行时模型

## 1. 背景与准入

ADR-0036 的 Stage 1 实证锚定建立在 scPerturb 调和版 h5ad 上。A3（GEO 原生处理文件，GSE133344）已到位。本 ADR 冻结同数据集、独立源格式的端到端交叉校验：若两条独立管线产出高度一致的六节点响应，Stage 1 管线的格式处理可信。六问：层外复核基础设施（不改层模型）；研究问题为"同数据两源格式的六节点响应是否一致"；指标与一致性判据计算前冻结；失败记 inconsistent 并触发调查（不静默通过）；全部映射规则冻结。

## 2. 冻结格式事实（已盘点）

- `filtered_matrix.mtx.gz`：MatrixMarket，33,694 基因 × 111,668 细胞（gene×cell 定向）；`genes.tsv` 两列 Ensembl/symbol；`barcodes.tsv` 细胞条形码（含 `-N` gemgroup 后缀）。
- `cell_identities.csv.gz`：cell_barcode、guide_identity、good_coverage、number_of_cells 等。guide_identity 形如 `KLF1_NegCtrl0__KLF1_NegCtrl0`（双 guide 成对）、`DUSP9_ETS2__DUSP9_ETS2`（组合）、`NegCtrl10_NegCtrl0__NegCtrl10_NegCtrl0`（纯对照）。

## 3. 冻结归并与处理规则

- QC：与 ADR-0036 相同，`good_coverage == True`（该数据集原生携带）。
- genes.tsv 符号歧义：34 个 symbol 各有两行 Ensembl（盘点事实，如 FAM231C/PIK3R3）；冻结规则为**整组剔除重复 symbol**（33,660 唯一行保留），不做"取第一行"的任意选择。
- guide → 单元归并：两部分按 `__` 切分后按 `_` 取 token；以 `NegCtrl` 开头的 token 为对照标记；纯对照 → 单元 `control`；其余按**首次出现序**去重的基因 token 以 `_` 连接成单元名（与 scPerturb 基因级命名对齐，事后逐一核对交集）。
- 归一化/log2FC/≥50 细胞/桥宇宙规则与 ADR-0036 逐条相同；dataset_id = `norman-weissman-2019-geo-native`；参数集加入核心白名单。
- 拆分 salt = `mgba-aivc-norman-geo-anchor-2026-08-29`（本 profile 内部完整性用；比较不依赖拆分）。

## 4. 一致性判据（计算前冻结）

在两条管线共享单元上比较六节点向量：

- 报告：共享单元数、逐单元 MAE 分布、展平向量的 Spearman、方向一致率。
- 判定：**Spearman > 0.8 且方向一致率 > 0.8 → consistent**；否则 inconsistent（触发调查，不允许静默通过）。
- 两者细胞集与过滤细节不同（111,445 vs 111,668、QC 语义差异），允许小的数值漂移；判据只管方向与秩结构。

产物 `mgba-aivc-crosscheck-0.1`（write-once，登记 registry）。

## 5. 未采用方案与回退

未采用：逐细胞级比较（桥设计为聚合层）、把 GEO 版替换为主源（scPerturb 版已冻结入链）、对不一致单元做静默剔除。回退：删除本 ADR 产物与比较模块；Stage 1 链路与全部冻结实验不受影响。

## 6. 验证

测试覆盖：guide 归并规则（纯对照/单基因/组合/多 guide 对）、MatrixMarket 流式读取数值（合成 gzip fixture 手算值）、共享单元交集、一致性判据真/假分支、write-once、CLI 往返；既有全套测试与 `mgba data-check` 绿色。
