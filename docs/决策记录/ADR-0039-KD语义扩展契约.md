# ADR-0039：KD 语义扩展（Replogle CRISPRi）契约

- 状态：契约已接受（2026-08-29，计算前预注册）
- 日期：2026-08-29
- 影响范围：生成链外 KD 实证锚定 + L0 训练 + 配对实验；产物落 `data/aivc/derived/` 与 `artifacts/empirical-l0-kd/`
- 不影响：ADR-0036/0037/0038 全部冻结产物与身份、五层 DTO/Protocol、核心零依赖、参考基线

## 1. 背景与准入

ADR-0038 接链只覆盖过表达（OE）语义（Norman CRISPRa）。敲低（KD）数据 B2 已到位并核验：`ReplogleWeissman2022_K562_essential.h5ad`（scPerturb 调和版，Zenodo 10.5281/zenodo.7041849，CC BY 4.0，MD5 对齐）。本 ADR 冻结 KD 臂的全部规则。六问同 ADR-0035–0038 框架：L0 层外锚定 + 层内可选变体；研究问题为 KD 响应是否同样可学且可接链；指标与通过规则沿用 ADR-0037 冻结形状；失败保留负面结果并可整体回退。

## 2. 冻结数据契约（计算前预注册，格式事实已盘点）

- 源：310,385 cells × 8,563 genes，dense float32 原始 UMI 计数；control 10,691 细胞；perturbation 类别 2,058，≥50 细胞的单元 1,833 个。
- QC：该调和发布版无 `good_coverage` 字段——冻结为**不再额外过滤**（与 A2 的 QC 规则差异显式记录）。
- 归一化与 log2FC：与 ADR-0036 逐条相同（library-size 1e4 → log2(1+x) → 单元均值 − 对照均值）。
- 基因宇宙：Hallmark v2026.1 50 集并集 ∩ var.gene_name = 2,377 基因（盘点事实）；六节点桥覆盖：190/161/133/304/85/38（负反馈最弱，延续已标注缺口）。
- 拆分：同 digest 规则，salt = `mgba-aivc-replogle-kd-anchor-2026-08-29`，train 80% / holdout 20%。
- bundle schema 复用 `mgba-aivc-empirical-log2fc-0.1`，dataset_id = `replogle-2022-k562-essential-scperturb`；核心装载器按 dataset_id 白名单校验各自的冻结参数集（Norman 集不变）。

## 3. 训练与核验

- 训练协议**逐字沿用 ADR-0037 冻结超参**（架构、Adam lr 1e-3、weight_decay 1e-4、MSE、3000 epoch、种子 42、CPU 单线程）；拆分 salt 随 profile 携带（修正 ADR-0037 脚本中 split 回执硬编码为模块常量的实现偏差）。
- 通过规则不变：holdout MAE 严格低于质心与 ridge（margin >1e-12）；失败原样保留。

## 4. 接链与配对实验

- 响应表构建复用 ADR-0038 门禁（verdict==passed + digest 交叉一致），产出独立 KD 表 `mgba-l0-response-table-0.1`（units 为 KD 单元命名空间，与 OE 表分离存放）。
- `EmpiricalResponseGrnModel` **零代码改动**：2^x 规则方向自洽（负 log2FC 即下调）。
- 配对实验复用 ADR-0038 矩阵与场景（30 tick、seeds 41/42/43、cell-a），两处差异冻结：参考臂为**硬钳制映射节点到 0.0**（KD），经验臂为 KD 表单元 dose 1.0。
- 实验单元选择规则与 ADR-0038 同族（train 角色 ∧ 单基因 ∧ 基因 ∈ 十集桥并集 ∩ var ∧ 细胞数最多 ∧ 字典序），在 KD profile 生成后确定性计算并写入实验记录。
- 配置兼容：新增 `EmpiricalKDComparisonConfig`（显式 `reference_value` 字段）；v0.1 配置类与其冻结矩阵身份**逐位不动**——装载器按 `reference_value` 键存在性分派。

## 5. 未采用方案与回退

未采用：合并 OE/KD 单表（命名空间污染）、修改 ADR-0038 配置类（破坏冻结矩阵身份）、对 B2 加自造 QC 阈值（看结果定阈值的风险）、GPU 训练。回退：删除 KD 各 artifact、`scripts/aivc_replogle_empirical.py` 与实验配置即可。

## 6. 验证

测试覆盖：dense-X 实证段数值（合成 h5ad fixture 手算值）、dataset_id 白名单与参数集分派、salt 传递、KD 训练评估通过/失败分支复用、KD 实验配置（reference_value=0.0 合法性、v0.1 配置无该键时行为不变）、L0 模型 KD 语义（负 log2FC → 下调事件）、全套既有测试与 `mgba data-check` 绿色。
