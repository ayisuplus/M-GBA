# M-GBA 0.1.0 发布清单

> 冻结日期：2026-08-18  
> 接受日期：2026-08-19  
> 状态：项目所有者已接受 E0–E2 范围，并授权首次 commit、`v0.1.0` tag 与 GitHub 推送

逐项证据与 E3–E5 边界见 [MVP 0.1.0 完成度审计](MVP-0.1.0-完成度审计.md)。

## 交付内容

- [x] L0–L4 五层参考模型与相邻层契约
- [x] 多速率 Runner、trace 哈希链、checkpoint 与精确恢复
- [x] WP8 的 7 条件 × 3 seed 配对扰动/消融矩阵
- [x] WP9 的 raw-only CSV/SVG/HTML 报告与 SHA-256 manifest
- [x] 冻结 full/fallback 演示脚本
- [x] 中文设计报告和英文技术报告
- [x] 配置索引、复现说明、CHANGELOG 和已知限制

## 冻结身份

| 对象 | 值 |
|---|---|
| Python package | `m-gba==0.1.0` |
| release wheel SHA-256 | `ddb2f636afb3228ec51dfd8b7b8d93e6a0649bf9c0219f964254baec0329f48c` |
| 单 tick experiment | `mgba-023f543fb5a130ab` |
| 100 tick experiment | `mgba-66654d1710f94556` |
| 100 tick history | `7edbf3b897983ae4d24e1537bcc6b6d8850f3933adfeb6cc78b215c56d1350dc` |
| WP8 matrix | `matrix-7da4137aa39d5122` |
| 基线结局 | `FAILED` |
| 报告数据文件 | 5 CSV |
| 报告图表 | 4 SVG |
| 报告页面 | 1 static HTML |

## 质量门禁

- [x] 单元与端到端测试通过
- [x] `mgba run` 通过
- [x] `mgba simulate --ticks 100` 通过
- [x] `mgba experiment` 复现冻结 matrix ID
- [x] `mgba report` 复现 10 个报告文件
- [x] `mgba sten-smoke` 通过
- [x] full demo 在当前开发虚拟环境通过
- [x] 全新虚拟环境 wheel 安装、60 项测试和 full demo
- [x] 项目所有者审查并接受 E0–E2 发布范围
- [x] 项目所有者授权首次 Git commit、`v0.1.0` tag 与 GitHub 推送

## 发布边界

- 无量纲、未校准的确定性 reference model；
- 没有有效随机重复或统计推断；
- 没有 L4 下行反馈；
- 固定 L3 拓扑，STEN 仅为独立 smoke；
- 不宣称生物真实性、临床预测、群体动力学或涌现。

## 下一阶段候选（不进入 0.1.0）

1. 对 L2 死亡/活力与 L3 资源/压力方程做参数敏感性分析。
2. 引入有明确机制意义的随机源，重新设计 seed 与统计协议。
3. 以可关闭慢时钟实现 L4→L3 反馈，保持相邻逐层下行。
4. 在静态图基线之上对比 GNN、动态拓扑与 STEN。
5. 只在明确的 L2 policy 学习问题中评估 ML/RL/LLM，不用其取代五层主线。
