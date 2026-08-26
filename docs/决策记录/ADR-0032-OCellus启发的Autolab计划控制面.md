# ADR-0032：OCellus 启发的 Autolab 计划控制面

- 状态：已接受并实现
- 日期：2026-08-25
- 影响范围：L0–L4 之外的 Autolab 元层、CLI 与审计 artifact
- 不影响：L0–L4 DTO/Protocol、tick 循环、既有实验 evaluator、冻结参考模型和发布身份

## 1. 背景与准入判断

OCellus 的 Planner–Router–Verifier 分工适合补强 ADR-0020 的实验治理，但它不能成为 M-GBA 的中央生成模型。此次变更属于跨层生成链外基础设施，增强既有 `AutolabSession`，回答的问题是：在任何实验运行前，能否把注册表编译成一个封闭、确定、可审计的执行意图，并在运行后核验原有顺序、leader 和 history digest？

保留的基线是 ADR-0020 的注册表、注入式 evaluator、筛选→确认策略和 `mgba-autolab-artifact-0.1`。成功条件是合法计划复现原评估顺序及 L2 leader，非法 DAG、工具、层级、假设、预算、配对或种子全部 fail-closed，且计划验证本身不能构造 runner 或运行实验。

## 2. 决策

新增 `mgba.autolab_planning`，公开三个封闭对象：

- `PlanStep`：DAG 节点，只能引用固定工具清单；
- `AutolabPlan`：schema `mgba-autolab-plan-0.1`，固定 `executed: false` 和 `claim_level: reference_model`；
- `VerificationReport`：schema `mgba-autolab-plan-verification-0.1`，记录三层状态和机器可读拒绝原因。

计划编译器从人工维护的 `AutolabConfig` 注册表产生固定 DAG：

```text
priority-ordered probe
  → deterministic rank selection
  → budgeted rank-based confirmation
  → manifest/history verification
```

确认节点只保存 `selected_rank`，不能在看到 probe 结果前猜中某个假设。固定工具清单只有“配对静态层替换评估”“选择 probe leader”“验证 manifest/history”三项；计划不能扩展工具或改写注册表。

## 3. 三层验证

1. `schema_dag`：根对象和 step 均为 closed schema；校验字段类型、唯一 step id、依赖完整和 DAG 无环。
2. `architecture_policy`：校验注册表/工具 digest、已注册假设、单层 L1/L2/L3 scope、固定 ticks、完整多 seed、配对基线、预算和规范编译顺序。跳层没有可表达路径。
3. `post_result`：对既有 `AutolabSessionResult` 重算会话身份、probe/confirm 顺序、leader、逐 seed effect 与 history anchor，并与 `manifest` 对齐；结论只能是 `reference_model`，数字生命、临床、已验证涌现或自主科学发现等越界表述直接拒绝。

Verifier 只有数据参数，没有 evaluator 参数，不导入 runner，也不能修改计划或结果。没有采用依赖模型预测真值的运行时 sanity check；没有 Critic 自动修复。失败只产生确定性拒绝报告。

## 4. CLI 与执行边界

`mgba autolab-plan` 有两种输入：缺省时从冻结注册表编译；传入 `--plan` 时验证外部 closed-schema JSON。命令只输出计划和报告，可选 write-once 落盘，顶层和计划均固定 `executed: false`；拒绝计划以非零状态退出。

`mgba autolab` 仍是唯一现有执行入口，但现在先编译并通过 preflight，完成原 `AutolabSession` 后再通过 post-result 核验。只有人把假设写入注册表，规范编译器才会把它列入计划；`autolab-propose` 的 `accepted_for_registry_review` 仍不会执行。

默认注册表编译为 `autolab-plan-a36a954a5ed72012`。接线后的真实会话继续得到原 `autolab-71df3a1d06a63ce3`、原四次评估顺序和 `l2-static` leader；现有 artifact schema 与逐 run history digest 不变。

## 5. 未采用方案

- 让在线 LLM 直接调用 runner：拒绝，扩大授权范围且绕过冻结注册表。
- 让 Planner 自由发明工具或跨层实验：拒绝，不可复现且破坏相邻层约束。
- 让 Critic 自动改计划、改阈值或重跑到通过：拒绝，会造成观察后选择。
- 用预测答案检查实验“是否合理”：拒绝，模型预测不能成为实验真值。

## 6. 回退与验证

移除 `autolab_planning.py`、`autolab-plan` CLI 和 `autolab` 前后两道调用即可恢复 ADR-0020；注册表、evaluator、五层模型和旧 artifact 不依赖新控制面。

测试覆盖 closed schema、循环/缺失依赖、未知工具、未注册假设、层级 scope、配对/seed、超预算、manifest/history 篡改、leader/顺序漂移、科学表述边界、write-once 和 CLI 零执行。验证函数调用前后 evaluator call log 不变。
