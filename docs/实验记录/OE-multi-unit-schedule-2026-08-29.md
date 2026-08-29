# OE 链路多单元与调度扩展实验记录（ADR-0041）

- 日期：2026-08-29
- 契约：`docs/决策记录/ADR-0041-OE链路多单元与调度扩展契约.md`（实现前冻结单元/映射/时序）
- 响应表：`l0-response-table-60c838d81d379f17`（ADR-0037 passed 资产）
- 矩阵：`empirical-l0-schedule-f562ddbcb6d71d44`，artifact `artifacts/empirical-l0-schedule/empirical-l0-schedule-f562ddbcb6d71d44/`
- 场景：`configs/multiscale_demo.json`，30 tick，seeds 41/42/43（确定性重放门禁，三 seed 逐值相同）
- 模型级别：`reference model`（语义对照，不是生物验证）

## 1. 冻结设置

五条件：baseline / reference_multi_clamp（cell-a damage、cell-b signal、cell-c damage 硬钳制 1.0 常量）/ empirical_multi_constant（BAK1@a、ETS2@b、TGFBR2@c 常量 1.0）/ empirical_multi_scheduled（同上映射，L0 tick 16 onset）/ empirical_combo_constant（cell-a `BCL2L11_BAK1` @1.0）。身份门禁与 L0-only 构造门禁均通过。

## 2. 结果（seed 41；三 seed 逐值相同）

| 比较 | L0 | L4 | 传播 tick（L0/L1/L2/L3/L4） | 结局 |
|---|---:|---:|---|---|
| reference_multi_clamp vs baseline | 0.171160 | 1.83e-04 | 1/1/1/1/1 | failed→failed |
| empirical_multi_constant vs baseline | 0.003128 | 1.41e-04 | 1/1/1/1/1 | failed→failed |
| empirical_multi_constant vs reference_multi_clamp | 0.171955 | 3.24e-04 | 1/1/1/1/1 | failed→failed |
| empirical_multi_scheduled vs empirical_multi_constant | 0.002614 | 1.41e-04 | 1/1/1/1/1 | failed→failed |
| empirical_combo_constant vs baseline | 0.000781 | 9.72e-05 | 1/1/1/1/1 | failed→failed |

判读（reference-model 级）：

- **多单元放大语义差异**：三细胞并行时经验臂 vs 参考臂的 L4 距离（3.24e-04）大于单单元 ADR-0038 的 2.01e-04——扰动规模在两种语义间系统性放大差异，且经验臂以 ~1/55 的 L0 强度达到同量级 L4 效应。
- **时序主效应可见**：晚 onset（tick 16）与常量的 L4 距离 1.41e-04，与"经验臂 vs baseline"同量级——在该场景里 30 tick 窗口内早/晚施加的终末效应可区分。
- **组合单元**（BCL2L11_BAK1 真实组合测量）单独施加的效应最弱（L0 0.00078），与两成分单独响应的粗略叠加不可直接比——组合携带自身测量值，不是成分相加。
- 全部条件保持 `failed`；onset 前调度臂与 baseline 逐位一致（tick 1–15），tick 16 起差异可见——ADR-0029 调度不变量在经验语义下同样成立。

## 3. 边界与下一步

- 多单元并行的语义为"各自经验模式并存"（无交互项）；组合单元携带真实组合测量。均来自 K562 CRISPRa，不外推。
- 下一步候选：A3 交叉校验 Stage 1；L3 calibration 预注册；CAR-M 场景的实证响应调度（需单独预注册）；B1 Tahoe 药物扰动进入锚定管线。
