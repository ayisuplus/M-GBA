# ADR-0044：CAR-M 空间标定协议偏差与复核门禁

- 状态：已接受
- 日期：2026-09-01
- 关联：ADR-0043、`CAR-M-spatial-calibration-2026-08-29.md`

## 1. 发现

ADR-0043 冻结的评估上限是 89 次，但 `calibration-summary.json` 实际记录 105 次。原因是搜索核心只记录预算、没有执行硬上限；预注册公式也未计入第二个 refinement sweep。该偏差发生在查看 holdout 之前，但已超出冻结协议，不能继续作为确认性结果解释。

## 2. 决策

- 原始 artifact 保持不可变，105 次结果降级为**探索性参数诊断**；其中历史 `verdict: improved` 仅表示当时代码按 holdout 阈值产生的输出，不再支持“确认改善”或“泛化到 holdout”的科研主张。
- Target `spatial-anchor-29c87ba1411d4fc8` 的 calibration、holdout 与 external-validation 结果均已查看，视为已消费。后续确认必须使用新的、未查看 target；CLI 拒绝以该 target 再次标定。
- `CalibrationProtocol.max_evaluations` 成为搜索核心的硬约束。空间标定协议升级为 `carm-spatial-calibration-0.2`，上限固定为 89；预算必须至少覆盖 incumbent 与随机扫描，否则搜索前失败。
- 不改写冻结 reference 配置，不采纳本次最佳参数，不把同一 holdout 上的重跑包装成复核。

## 3. 恢复确认性证据的条件

另行预注册新 target、固定 split 与阈值，在任何结果可见前冻结协议和源码身份；只允许一次确认。若无新数据，本项目只能保留“原 reference 未锚定”和“旧标定探索性改善”两条并列结论。

## 4. 后续迁移

该项已由 ADR-0045 完成：新 `mgba-manifest-0.2` 记录实际包源码字节的 `source_digest` 并改变新实验身份；历史 artifact 不追溯改写。
