# L0 扰动响应首次训练实验记录（ADR-0037）

- 日期：2026-08-28
- 契约：`docs/决策记录/ADR-0037-L0扰动响应首次训练契约.md`（训练前预注册）
- Target：`norman-perturbation-profile-0a0aa914dc9fb080`（Stage 1，ADR-0036）
- 评估 artifact：`data/aivc/derived/l0-training-evaluation.json`，evaluation_id `l0-training-eval-97216b607136bef0`（已登记 registry）
- 预测文件：`data/aivc/derived/l0-response-predictions.json`（SHA-256 `3bc831dc…`）；权重 `models/l0_response_mlp.npz`（不入库）
- 模型级别：`reference model`（离线评估；不接入 runner）

## 1. 冻结协议回顾

任务：扰动身份（成分 one-hot 均值 + combo 标志）→ 六节点 log2FC。拆分与 Stage 1 完全相同（train 188 / holdout 48）。三预测器同 split 对照：train-only 质心、ridge（λ=1.0 闭式解，无截距）、MLP（(V+1)→32 tanh→6；Adam lr 1e-3、weight_decay 1e-4、MSE、全批量 3000 epoch、种子 42、CPU 单线程）。通过规则：holdout MAE 严格低于质心**且** ridge（margin 均 >1e-12）。成分词表 105，组合单元 131。

## 2. 结果

| 预测器 | holdout MAE | 方向一致率 | Spearman |
|---|---:|---:|---:|
| centroid | 0.012872 | 0.701 | 0.790 |
| ridge | 0.012280 | 0.656 | 0.656 |
| **MLP** | **0.009494** | **0.833** | **0.852** |

- margin_vs_centroid = **+0.003378**，margin_vs_ridge = **+0.002786**（均 >1e-12）
- **verdict：passed**（按冻结规则）
- train MSE 终值 5.75e-05；质心交叉核验偏差 2.1e-17（<1e-12）

判读（reference-model 级，不外推）：在 Norman K562 CRISPRa 数据上，"扰动身份 → 六节点响应"映射可学，MLP 相对质心基线 MAE 下降约 26%，方向与秩相关也同步改善（非通过规则的描述指标同向支持）。ridge 未能超过质心，说明该映射中存在非平凡非线性成分，但样本量（188 train）极小，结论只在本数据集与冻结桥内成立。

## 3. 确定性验证

- 同种子同调用完整重跑：预测 JSON 逐字节一致（SHA-256 `3bc831dc…` 两跑相同），权重 `.npz` 逐字节一致（`1d5ba70f…`）。
- 过程中发现并修复：`torch.save` 的 zip 容器嵌入墙钟元数据导致权重字节漂移，已改用 `np.savez`（固定 1980-01-01 时间戳）；数值始终逐位一致，漂移仅限容器元数据。

## 4. 边界与下一步

- 预测向量**未**进入 runner；把通过的预测器接入 L0（如经 ADR-0034 人审 schedule 候选路径或作为 L0 层内变体）属后续单独 ADR。
- 失败分支同样受保护：核验模块对"不优于质心/不优于 ridge/平手"均判 failed 并原样保存数值（测试覆盖）。
- 下一步候选：A3 GEO 原生矩阵到位后复核实证段；B1/B2 到位后评估跨数据集泛化；预测器接链 ADR（WP8 配对指标单层替换矩阵）。
