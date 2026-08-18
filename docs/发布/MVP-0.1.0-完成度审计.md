# M-GBA 0.1.0 完成度审计

> 审计日期：2026-08-19  
> 审计对象：`MVP计划.md` 0.8、`MVP实施计划.md` 0.7、AGENTS.md 与当前工作树  
> 结论：WP0–WP10 的 E0–E2 降级发布范围已验证并由项目所有者接受；不得将其表述为 E3–E5、完整宏观反馈闭环或已验证涌现。

## 1. 审计方法

每个要求只在存在可定位的当前证据时标记为“已验证”。文档意图、通过了无关测试或“没有看到失败”都不算完成证据。

状态含义：

- **已验证**：代码、配置、测试和/或 artifact 直接支持要求；
- **明示延后**：路线图中存在，但实施计划的降级规则明确允许延后；
- **待用户验收**：只能由项目所有者证明；
- **未完成**：当前证据与要求不符或缺失。

## 2. WP0–WP10 交付审计

| 工作包 | 状态 | 直接证据 |
|---|---|---|
| WP0 manifest、实验 ID、artifact | 已验证 | `src/mgba/experiment.py`；`tests/test_experiment.py`；ADR-0001 |
| WP1 五层 DTO/Protocol、禁止跳层 | 已验证 | `src/mgba/layers/contracts.py`；`tests/test_contracts.py`；`tests/test_multiscale.py` |
| WP2 L0 离散 GRN 与可审计扰动 | 已验证 | `src/mgba/layers/l0.py`；L0 JSON；6 项 L0 测试；ADR-0002 |
| WP3 L1 翻译/降解与信号入口 | 已验证 | `src/mgba/layers/l1.py`；L1 JSON；7 项 L1 测试；ADR-0003 |
| WP4 L2 五态 Cell 状态机 | 已验证 | `src/mgba/layers/l2.py`；L2 JSON；6 项 L2 测试；ADR-0004 |
| WP5 L3 固定图与微环境 | 已验证 | `src/mgba/layers/l3.py`；L3 JSON；6 项 L3 测试；ADR-0005 |
| WP6 L4 即时指标、窗口与结局 | 已验证 | `src/mgba/layers/l4.py`；L4 JSON；6 项 L4 测试；ADR-0006 |
| WP7 100 tick、多速率、checkpoint/恢复 | 已验证 | `src/mgba/runner.py`；7 项 runner 测试；`mgba simulate`；ADR-0007 |
| WP8 E0–E2 扰动、消融、路径 | 已验证 | `src/mgba/experiments.py`；5 项 matrix 测试；21 raw runs；ADR-0008 |
| WP9 raw-only 表格/图表/只读报告 | 已验证 | `src/mgba/reporting.py`；3 项 reporting 测试；10 个报告文件；ADR-0009 |
| WP10 报告、演示、wheel、空环境 | 已验证 | 中英文报告；`scripts/mvp_demo.py`；60 项测试；新 Python 3.12 venv full demo；ADR-0010 |
| WP10 首次 commit 与 `v0.1.0` tag | 已授权 | 项目所有者于 2026-08-19 接受 E0–E2 范围，并明确要求推送到 GitHub |

## 3. 纵向主线与 Definition of Done

| 要求 | 状态 | 证据/边界 |
|---|---|---|
| L0–L4 都有运行时状态 | 已验证 | `test_trace_contains_every_layer_in_order` 与 100-tick trace |
| 主生成流只发生在相邻层 | 已验证 | `test_trace_contains_only_adjacent_layer_transitions`、非相邻转换拒绝测试 |
| L0 扰动在 L4 产生可复现差异 | 已验证 | `repair_kd_000` 在 L0–L4 均非零；matrix `matrix-7da4137aa39d5122` |
| 层级消融改变 L4 | 已验证 | L1/L2/L3 static 配对对照；L2 效应约 `0.4984` |
| L4 未直接写入 L2 答案 | 已验证 | Cell Protocol 只接收 L1、局部环境和上一 Cell 状态；错误类型拒绝 |
| 相同 manifest 结果一致 | 已验证 | 单 tick、100 tick、checkpoint 和 matrix 确定性测试 |
| 负面结果与局限保存 | 已验证 | 100 tick `FAILED`；WP8 实验记录；中英文报告 |
| 不越界宣称生物真实性/临床/数字生命 | 已验证 | AGENTS.md、README、中英文报告保持一致边界 |

## 4. E0–E5 与路线图里程碑

| 实验/里程碑 | 状态 | 当前证据 |
|---|---|---|
| E0 跨层完整性 | 已验证 | 逐 tick 五层 trace、相邻事件与失败测试 |
| E1 L0 扰动传播 | 已验证 | 3 档 repair 钳制和五层效应 |
| E2 层级消融 | 已验证 | L1/L2/L3 static 替换与配对 L4 差值 |
| M7/E4 完整 L4→L3→L2→L1→L0 反馈 | 明示延后 | 当前只有 L3→L2、L2→L1 快反馈；实施计划降级方案允许推迟反馈实验 |
| M9/E3 群体与涌现预实验 | 明示延后 | 当前确定性 seed 轨迹相同，没有有效多种子分布 |
| E5 L3/STEN 五层对照 | 明示延后 | STEN 仅有独立 smoke，未进五层主链；路线图将其置于后续课程升级 |

E3–E5 不是已失败的结果，而是尚未执行的研究。因此不得使用“未发现涌现”、“反馈无效”或“STEN 无贡献”等伪结论。

## 5. 四类质量门禁

| Gate | 状态 | 证据/缺口 |
|---|---|---|
| A 层级真实性 | 已验证 | 每层有独立状态/计算、静态替换基线、禁止跳层 |
| B 可复现性 | 已验证 | manifest、raw trace、hash chain、checkpoint、raw-only report、新 venv full demo |
| C 可证伪性 | 已验证 | 冻结指标/对照、损坏输入闭锁失败、保留 `FAILED` 基线 |
| D 用户知识所有权 | 待人工自测 | 项目所有者已接受发布范围；是否能独立解释假设、公式、实验和局限仍须按人工验收表自证，AI 不能代替这项证据 |

## 6. 科学证据等级

当前可以宣称：

- 五层软件契约和 reference-model 计算路径已运行；
- L0 扰动可在当前模型内追踪至 L4；
- L1–L3 静态替换会改变当前模型的 L4 结果；
- 这些结果可由 raw artifact 重建。

当前不可以宣称：

- 已完成宏观反馈闭环；
- 不同 seed 形成了可统计分布；
- 已证明群体动力学或涌现；
- STEN、GNN、LLM 或动态拓扑对宏观表型有已验证贡献；
- 当前参数对真实生物、药理或临床有效。

AGENTS.md 使用的安全表述仍是 `contract demonstrator`；可将各层实现称为“确定性 reference models”，但不将整体升级为 `group dynamics` 或更高等级。

## 7. 发布治理与个人自测

1. **发布范围接受**：项目所有者已于 2026-08-19 接受当前 E0–E2 范围，并授权首次 commit、`v0.1.0` tag 与 GitHub 推送。
2. **用户知识所有权自测**：仍应按 [M-GBA 0.1.0 答辩自测与人工验收](../报告/M-GBA-0.1.0-答辩自测与人工验收.md) 阅读关键模型、复现一次 full demo，并确认能解释 L0–L4 公式/边界、WP8 配对协议、`FAILED` 基线与已知限制。

第二项是毕业论文知识所有权证据，不由代码发布动作自动完成，也不阻断已经接受的 E0–E2 软件基线发布。
