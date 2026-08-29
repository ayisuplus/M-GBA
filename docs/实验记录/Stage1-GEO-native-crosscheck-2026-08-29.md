# Stage 1 GEO 原生交叉校验记录（ADR-0042）：consistent

- 日期：2026-08-29
- 契约：`docs/决策记录/ADR-0042-GEO原生交叉校验契约.md`（计算前预注册，含判据阈值）
- 数据：A3 GEO 原生四文件（GSE133344；主矩阵 1,130,430,845 B，gzip 全流解压验证）
- 产物：GEO profile `norman-geo-perturbation-profile-101f1145faa49694` + crosscheck `aivc-crosscheck-0a62229c8d964655`（均登记 registry）
- 性质：复现性检查（两源格式一致性），不是生物验证

## 1. 管线差异（两源独立路径）

| 环节 | scPerturb 调和版（A2） | GEO 原生（A3） |
|---|---|---|
| 矩阵 | CSC h5py，111,445 细胞 | MatrixMarket 流式（3.62 亿条目），111,668 细胞 |
| 单元标注 | 调和 `perturbation` 类别 237 | guide_identity 归并（`__`/`_` 切分、NegCtrl 对照标记）→ 240 |
| QC | good_coverage=True | good_coverage=True（原生携带，11,183 对照细胞两源一致） |
| 基因歧义 | 无 | 34 个双 Ensembl symbol 整组剔除（冻结规则） |

## 2. 交叉校验结果（冻结判据：Spearman > 0.8 且方向一致率 > 0.8）

| 指标 | 值 | 阈值 | 判定 |
|---|---:|---:|---|
| 共享单元 | 234 / 236+240 | — | — |
| 展平 Spearman | **0.99993** | >0.8 | ✅ |
| 平均方向一致率 | **0.9986** | >0.8 | ✅ |
| 平均 MAE | 2.98e-05 | — | 极小漂移 |

**verdict：consistent。** Stage 1 管线在两个独立源格式上产出秩结构几乎完全一致的六节点响应——格式处理（CSC/MatrixMarket、QC、归一化、桥投影）可信。未共享的 6 个单元是 `_1`/`_2` 技术重复命名差异（scPerturb 合并、GEO 原生保留），已记录，不影响结论。

## 3. 过程记录

- NCBI 对本机按连接限流：主矩阵经 14 路 Range 并行 + 停滞检测续传完成；中途发现代理重试往分片追加重复字节（curl `--retry` + stdout append 的已知交互），用 zlib 消费偏移精确定位损坏分片（part-0/11）并重下修复，最终解压验证通过。
- 两源的微小数值漂移（MAE 2.98e-05）来自细胞过滤细节差异（111,445 vs 111,668），在判据允许范围内。
- 主源不变：scPerturb 版 profile 仍是唯一冻结入链来源；GEO 版仅作复现性证据。

## 4. 下一步

- L3 calibration 参数选择预注册（回应空间"未锚定"）——队列中科学权重最高的一项。
- B1 Tahoe 药物扰动锚定（教学子集已在手，按 ADR 队列另行预注册）。
