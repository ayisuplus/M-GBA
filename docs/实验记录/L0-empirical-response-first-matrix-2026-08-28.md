# 实证响应接入 L0 首次配对实验记录（ADR-0038）

- 日期：2026-08-28
- 契约：`docs/决策记录/ADR-0038-实证响应表接入L0契约.md`（实现前冻结单元/节点/剂量/语义）
- 响应表：`l0-response-table-60c838d81d379f17`（由 ADR-0037 passed 评估门禁蒸馏，236 单元）
- 矩阵：`empirical-l0-6a202fa1b24f1617`，artifact `artifacts/empirical-l0/empirical-l0-6a202fa1b24f1617/`
- 场景：`configs/multiscale_demo.json`，30 tick，seeds 41/42/43（确定性重放门禁）
- 模型级别：`reference model`（语义对照，不是生物验证）

## 1. 冻结设置

- 单元 `BAK1`（train、单基因、桥并集内、1,349 QC 细胞）经 `EmpiricalResponseGrnModel` 以 `applied_i = clamp01(natural_i × 2^(1.0 × log2fc_i))` 施加到 cell-a；
- 参考臂：cell-a 的 `damage_response` 硬钳制到 1.0（桥映射规则：P53/TNFA 平手按冻结序取 damage_response）；
- 身份门禁：empirical runner 无扰动轨迹与参考 baseline 逐值一致（已验证 True）。

## 2. 结果（三 seed 逐值相同，只作重放门禁）

| 比较 | L0 | L1 | L2 | L3 | L4 | 结局 |
|---|---:|---:|---:|---:|---:|---|
| reference_clamp vs baseline | 0.061508 | 0.044662 | 0.001969 | 3.0e-06 | 5.1e-06 | failed→failed |
| empirical vs baseline | 0.001711 | 0.001377 | 0.000358 | 4.0e-05 | 1.96e-04 | failed→failed |
| empirical vs reference_clamp | 0.062056 | 0.045051 | 0.002326 | 4.3e-05 | 2.01e-04 | failed→failed |

传播 tick：reference_clamp 为 L0@1→L1@1→L2@2→L3@2→L4@11；empirical 两臂均为逐 tick 1 起传播。

判读（reference-model 级）：

- 硬钳制在 L0 的扰动强度约为经验模式的 36 倍，但两者到 L4 都被 demo 场景的动力学衰减到很小；这是当前参考动力学的性质，不是经验模式"无效"的证据。
- 经验模式虽小却沿 L0→L1→L2→L3→L4 完整传播，且 L3/L4 相对距离大于硬钳制臂（4.0e-05 vs 3.0e-06）——多节点协变模式比单节点钳制更深地进入组织层聚合。
- 全部条件保持 `failed`，与 100 tick `FAILED` 负面基线家族一致；未为展示效果调参。

## 3. 边界与下一步

- 链路已验证"训练产物可以纯数据形式进入 L0 并驱动跨层传播"；语义差异幅度受 K562 CRISPRa 单背景与 BAK1 单单元限制，不能外推。
- 下一步候选：KD 语义（需 B2 Replogle 到位）、多单元/群体扰动调度（复用 ADR-0029 schedule）、把经验响应臂接入 CAR-M 场景（需该场景的预注册方案）。
