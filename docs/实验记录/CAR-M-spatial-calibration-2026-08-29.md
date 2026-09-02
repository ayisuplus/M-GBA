# CAR-M 空间 L3 calibration 参数选择记录（ADR-0043）：协议偏差，探索性

- 日期：2026-08-29
- 契约：`docs/决策记录/ADR-0043-CAR-M空间L3标定契约.md`（搜索前预注册）
- Target：`spatial-anchor-29c87ba1411d4fc8`（真实 Wu/Jackson 锚定 target）
- 标定 artifact：`artifacts/carm-spatial-calibration/calibration-summary.json`，calibration_id `carm-spatial-calibration-d234af7af4172305`
- 确认评估：`carm-spatial-anchor-eval-2f1ead4bb7705f96`（完整 39 距离，一次确认）
- 模型级别：探索性 `reference model` 参数诊断（不改任何冻结配置）

## 0. 2026-09-01 后审计

ADR-0043 冻结上限为 89 次，实际 artifact 记录 105 次，构成协议偏差。下文的 `improved` 是历史程序输出，科研解释已按 ADR-0044 降级为探索性；不能据此声称确认改善或泛化。该 target 的 holdout 已查看并消费，禁止用同一 target 重跑确认。

## 1. 冻结设置回顾

参数 4 个（neighbor_radius / field_retention / field_diffusion / node_field_coupling）+ 冻结界；目标 = −calibration 均 NAE（20 tick 完整轨迹投影）；ADR-0018 核心（种子扫描 24 + top-4 坐标细化，incumbent=参考配置不劣保证）；确认规则：holdout 均 NAE 严格低于 12.146142329407688（margin > 1e-12），只跑一次。

## 2. 结果

搜索 105 次评估（含 incumbent 与细化），最佳配置：

| 参数 | 参考值 | 标定值 |
|---|---:|---:|
| neighbor_radius | 0.16 | 0.1894 |
| field_retention | 0.82 | **0.98（顶到盒上界）** |
| field_diffusion | 0.28 | 0.0113 |
| node_field_coupling | 0.35 | 0.138 |

确认评估（一次）：

| 角色 | 参考 | 标定后 | 变化 |
|---|---:|---:|---:|
| calibration（15 场指标） | 10.3478 | 7.3902 | −28.6% |
| holdout（15 场指标） | 12.1461 | 8.7083 | **−28.3% → improved** |
| external_validation（9 邻域指标） | 1.3274 | 1.5437 | +16.3%（不进门控，如实报告） |

## 3. 判读（reference-model 级）

- calibration 子集学到的参数化在两个已消费 Visium holdout 上也降低了误差；但因评估次数超过预注册上限，这只是探索性信号，不能将"未锚定"翻转为确认性的 `improved`，也不能称为泛化证据。
- 场物理形状变化方向一致：更低扩散 + 更高保持（更锐利、更持久的局部场）+ 更弱节点耦合。
- `field_retention` 顶到盒上界（0.98）——按 ADR-0018 先例记录，扩盒属下一轮预注册协议，本次不外推。
- 邻域指标略升提示场参数与邻域定义存在此消彼长；external_validation 不参与拟合，该上升不改变判定。
- 标定配置只存于 artifact（完整溯源），`configs/layers/l3_carm_spatial.json` 未动；是否采纳为新 reference 需另行 ADR 与矩阵重跑。

## 4. 下一步候选

- 新建未查看的空间 target，重新预注册 split、89 次硬预算与一次确认；在此之前不采纳标定配置。
- B1 Tahoe 药物扰动锚定协议。
- OCellus 权重公开后的 ADR-0034 真实对照。
