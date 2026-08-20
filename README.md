# M-GBA

M-GBA（Multi-scale Graph Biological Architecture）是一个跨尺度数字生命研究原型。项目的核心是用可运行模型表达生命状态从微观调控到宏观表型的逐层生成：

```text
L0 基因/转录调控
  → L1 分子/蛋白状态
  → L2 细胞个体行为
  → L3 组织、环境场与动态拓扑
  → L4 有机体宏观表型
```

多智能体用于表达 L2 的细胞个体，STEN 用于解决 L3 的语义通信和拓扑演化；它们是跨尺度架构的子问题，不是项目本体。

本项目验证的是跨层计算、局部交互和宏观状态生成，不宣称已经制造真实生命、完成 DNA 设计或具备临床预测能力。

## 当前状态

- 已完成可行性评估、核心原则、跨尺度架构与五层纵向 MVP 计划。
- 已初始化一个只依赖 Python 标准库的 L0→L4 契约演示器。
- 已验证一次 L0 修复表达敲低能够依次改变 L1、L2、L3 和 L4。
- 已冻结五层 DTO/Protocol、相邻层转换事件和确定性实验 manifest。
- 已建立纯 JSON/NDJSON artifact 骨架，原始事件采用追加写入。
- L0 已升级为六节点抽象离散 GRN，支持逐 tick 轨迹、损伤输入和可审计硬钳制扰动。
- 参考 L0 轨迹已通过 200 tick 稳定性与损伤剂量方向测试。
- L1 已升级为六类粗粒度分子动力学，支持翻译、降解、受体门控与可关闭局部信号入口。
- 参考 L1 轨迹已通过 200 tick 稳定性、单调性、降解和反馈开关测试。
- L2 已升级为五态 Cell 状态机，支持局部压力/资源/信号感知、修复动作与死亡吸收态。
- L2 已通过环境依赖、修复/应激分离、死亡动作归零和 Cell 身份隔离测试。
- L3 已升级为固定有向图上的节点级压力、资源和信号动力学，并能生成下一步 Cell 局部环境。
- L3 已通过边方向、局部资源、修复/凋亡压力效应、固定拓扑和配置指纹测试。
- L4 已升级为只消费 `TissueState` 的配置驱动观察器，区分即时表型、时间窗口摘要和最终结局。
- L4 已通过健康/失败极端状态、指标方向性、四类结局、时间顺序和配置指纹测试。
- 多速率 Runner 已支持 100 tick 确定性轨迹、L0/L4 慢时钟、相邻快速反馈、事件预算和纯 JSON 断点恢复。
- WP8 已完成 7 条件 × 3 seed 的配对矩阵，保存 21 份完整 raw trace、逐层效应和传播 tick。
- WP9 已完成 raw-only 报告链：重算 5 份 CSV、4 张 SVG 和无 JavaScript 的只读 HTML，并用 SHA-256 manifest 固定输出。
- WP10 已冻结为 0.1.0：中英文报告、full/fallback 演示、wheel 安装复现和发布清单已就绪；项目所有者已接受 E0–E2 发布范围。
- v0.2 已增加首个 CAR-M 场景包：从旧 TCGA-BRCA 预测重算 752 个样本的去标识化聚合 profile，并以 63 个 Cell 的固定图贯通 CAR 信号程序 L0→L4。
- CAR-M 21-run 矩阵已验证群体 L0 钳制、L2/L3 适配器、三层消融、checkpoint 恢复和 raw-only 报告；当前高剂量结果是炎症上升且最终负担代理略升的负面基线。
- `mgba demo-export` 已提供自包含离线 HTML 演示：seed-42 的 4 剂量条件组织动画、L4 曲线与逐细胞 L0→L4 检查器，负面基线在页脚原样保留。
- 主运行链已重构为 agent 中心：每细胞一个 `CellAgent` 持有 L0/L1/L2 状态并经 `CellModel` 协议决策；trace、checkpoint 与冻结矩阵行为与重构前逐字节一致。
- 默认与三档 repair 钳制均为 `FAILED`；L2 静态替换产生最大差异并转为 `RECOVERED`，因此当前优先诊断五态 L2 累积规则。
- 主运行链已增加可选 L4→L3 稳态反馈控制器（离散 PI + 反饱和 + 安全屏障，ADR-0012）：仅约束 L3 环境场、慢时钟触发、逐 tick 哈希链留痕；无反馈注入时所有冻结基线位级不变。
- `mgba feedback-experiment` 已实现 E4 三条件对照（无反馈/固定反馈/状态反馈）；`scripts/synthetic_feedback_benchmark.py` 生成确定性仿真场景集并运行基准。
- L2 已增加可选主动推理（Active Inference / 变分自由能）Cell 策略（ADR-0013）：以预期自由能最小化（风险+歧义分解、确定性 argmin、无采样）选择相位；规则状态机原样保留为默认与永久基线，策略替换仅隔离"决策规则"这一个变量。
- `mgba policy-experiment` 已实现规则 vs 主动推理的 L2 策略配对对照；`scripts/synthetic_policy_benchmark.py` 在仿真场景集上运行该基准。
- L3 已增加可选动态拓扑治理（ADR-0014）：应激回避 T1 式边交换，提案→授权→提交治理链、每 tick 交换预算、入度守恒；静态固定图模型原样保留为默认，E5 静态 vs 动态对照可执行（`mgba topology-experiment`）。
- L0 已增加可选种子化转录噪声模型（ADR-0015）：确定性右端位级不变 + 有界乘性噪声，噪声流由 `sha256(seed|cell|time)` 派生（checkpoint 精确恢复）；确定性 GRN 原样保留为默认。
- `mgba e3-experiment` 已实现 W14/M9 的 E3 群体统计协议：多种子噪声集合按预注册判据（CV 稳定性、微观驱动解耦、持续性）分级为 aggregation / group_dynamics / emergence_candidate；`scripts/synthetic_e3_benchmark.py` 运行仿真基准。
- 现有 STEN 代码保留为 L3 子系统 smoke test。
- 默认确定性链的多 seed 轨迹仍然相同；可选噪声 L0（ADR-0015）已使不同 seed 形成可统计的分布，E3 预注册判据可执行，但尚未达到 validated result 所需的冻结协议、统计检验与层级消融。
- E4×E3 组合已实现为随机闭环实验（ADR-0016）：`mgba closed-loop-experiment` 组合反馈控制器与噪声 L0，按预注册稳定性判据（震荡/锁死/恢复/恶化/不定）分级每 run 的慢时钟稳态序列；`scripts/synthetic_closed_loop_benchmark.py` 运行仿真基准。
- 分层异构神经网络已作为冻结权重契约演示器接入（ADR-0017）：纯标准库神经基元 + 可选 L0 MLP GRN 与 L3 消息传递 GNN 变体，权重由显式种子确定性派生（非训练模型）；`mgba neural-experiment --layer l0|l3` 运行单层替换配对对照，`scripts/synthetic_neural_benchmark.py` 运行仿真基准。

关键文档：

- [Agent 项目守则](AGENTS.md)
- [核心原则](docs/设计文件/核心原则.md)
- [可行性评估](docs/计划文件/可行性评估.md)
- [架构设计](docs/设计文件/架构设计.md)
- [MVP 计划](docs/计划文件/MVP计划.md)
- [MVP 实施计划](docs/计划文件/MVP实施计划.md)
- [ADR-0001：WP0–WP1 基础契约](docs/决策记录/ADR-0001-WP0-WP1-基础契约.md)
- [ADR-0002：L0 第一版离散 GRN](docs/决策记录/ADR-0002-L0-离散GRN.md)
- [ADR-0003：L1 第一版粗粒度分子动力学](docs/决策记录/ADR-0003-L1-粗粒度分子动力学.md)
- [ADR-0004：L2 第一版 Cell 状态机](docs/决策记录/ADR-0004-L2-Cell状态机.md)
- [ADR-0005：L3 第一版组织与微环境](docs/决策记录/ADR-0005-L3-组织与微环境.md)
- [ADR-0006：L4 第一版宏观表型](docs/决策记录/ADR-0006-L4-宏观表型.md)
- [ADR-0007：WP7 多速率运行器与检查点](docs/决策记录/ADR-0007-WP7-多速率运行器.md)
- [ADR-0008：WP8 扰动、消融与模型内因果路径](docs/决策记录/ADR-0008-WP8-扰动消融与因果路径.md)
- [WP8 reference matrix 实验记录](docs/实验记录/WP8-reference-matrix-2026-08-18.md)
- [ADR-0009：WP9 可重建报告与可视化](docs/决策记录/ADR-0009-WP9-可重建报告与可视化.md)
- [ADR-0010：WP10 交付冻结](docs/决策记录/ADR-0010-WP10-交付冻结.md)
- [CAR-M v0.2 实施记录](docs/计划文件/CAR-M-v0.2实施计划.md)
- [ADR-0011：CAR-M 场景包与群体扰动](docs/决策记录/ADR-0011-CAR-M场景包与群体扰动.md)
- [ADR-0012：L4→L3 稳态反馈控制器](docs/决策记录/ADR-0012-L4-L3-稳态反馈控制器.md)
- [ADR-0013：L2 主动推理 Cell 策略](docs/决策记录/ADR-0013-L2-主动推理Cell策略.md)
- [ADR-0014：L3 自适应拓扑治理](docs/决策记录/ADR-0014-L3-自适应拓扑治理.md)
- [ADR-0015：L0 转录噪声与 E3 群体统计](docs/决策记录/ADR-0015-L0-转录噪声与E3群体统计.md)
- [ADR-0016：噪声闭环与稳定性判据](docs/决策记录/ADR-0016-噪声闭环与稳定性判据.md)
- [ADR-0017：分层异构神经网络契约演示器](docs/决策记录/ADR-0017-分层异构神经网络契约演示器.md)
- [CAR-M v0.2 实验记录](docs/实验记录/CAR-M-vertical-slice-2026-08-19.md)
- [0.1.0 中文设计报告](docs/报告/M-GBA-MVP-中文设计报告.md)
- [0.1.0 English technical report](docs/报告/M-GBA-MVP-English-Technical-Report.md)
- [0.1.0 复现说明](docs/复现/MVP-0.1.0-复现说明.md)
- [0.1.0 发布清单](docs/发布/MVP-0.1.0-发布清单.md)

## 快速开始

要求 Python 3.11 或更高版本。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\mgba run --config configs/multiscale_demo.json
.\.venv\Scripts\mgba simulate --ticks 100 --trace-out artifacts/run.json
.\.venv\Scripts\mgba run-report --run artifacts/run.json
.\.venv\Scripts\mgba experiment --artifact-root artifacts
.\.venv\Scripts\mgba report --matrix-root artifacts/matrix-7da4137aa39d5122
.\.venv\Scripts\mgba carm-import --legacy-root "..\car-m-virtual-cell-main\car-m-virtual-cell-main" --output data/carm/tcga_brca_high_immune.json
.\.venv\Scripts\mgba carm-experiment --artifact-root artifacts/carm
.\.venv\Scripts\mgba demo-export
.\.venv\Scripts\mgba feedback-experiment --artifact-root artifacts/e4
.\.venv\Scripts\python scripts/synthetic_feedback_benchmark.py generate
.\.venv\Scripts\python scripts/synthetic_feedback_benchmark.py run
.\.venv\Scripts\mgba policy-experiment --artifact-root artifacts/policy
.\.venv\Scripts\python scripts/synthetic_policy_benchmark.py run
.\.venv\Scripts\mgba topology-experiment --artifact-root artifacts/topology
.\.venv\Scripts\python scripts/synthetic_topology_benchmark.py run
.\.venv\Scripts\mgba e3-experiment --artifact-root artifacts/e3
.\.venv\Scripts\python scripts/synthetic_e3_benchmark.py run
.\.venv\Scripts\mgba closed-loop-experiment --artifact-root artifacts/closed-loop
.\.venv\Scripts\python scripts/synthetic_closed_loop_benchmark.py run
.\.venv\Scripts\mgba neural-experiment --layer l3 --artifact-root artifacts/neural
.\.venv\Scripts\python scripts/synthetic_neural_benchmark.py run
.\.venv\Scripts\mgba sten-smoke --config configs/demo.json
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python scripts/mvp_demo.py --mode full --artifact-root artifacts/mvp-demo
```

Linux / WSL：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/mgba run --config configs/multiscale_demo.json
.venv/bin/mgba simulate --ticks 100 --trace-out artifacts/run.json
.venv/bin/mgba run-report --run artifacts/run.json
.venv/bin/mgba experiment --artifact-root artifacts
.venv/bin/mgba report --matrix-root artifacts/matrix-7da4137aa39d5122
.venv/bin/mgba carm-import --legacy-root ../car-m-virtual-cell-main/car-m-virtual-cell-main --output data/carm/tcga_brca_high_immune.json
.venv/bin/mgba carm-experiment --artifact-root artifacts/carm
.venv/bin/mgba demo-export
.venv/bin/mgba feedback-experiment --artifact-root artifacts/e4
.venv/bin/python scripts/synthetic_feedback_benchmark.py generate
.venv/bin/python scripts/synthetic_feedback_benchmark.py run
.venv/bin/mgba sten-smoke --config configs/demo.json
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/mvp_demo.py --mode full --artifact-root artifacts/mvp-demo
```

`mgba run` 保留单 tick 契约演示。`mgba simulate` 默认执行 100 个新增 tick，可用 checkpoint 暂停恢复。`mgba experiment` 运行冻结 WP8 矩阵；只有显式给出 `--artifact-root` 才保存完整 raw/derived JSON。`mgba report` 验证并从该 raw artifact 重建 WP9 只读报告，默认写入矩阵内的 `derived/report/`。`mgba run-report` 从单个保存的 run artifact（`simulate --trace-out` 或矩阵 raw run）重建逐 tick 的 L0–L4 轨迹记录：6 张 SVG 折线图、6 个 CSV、只读 HTML 摘要和 SHA-256 manifest，默认写入 run 文件旁的 `<名称>-report/`；默认输出落在 raw 目录内会拒绝，需显式 `--output-dir`。`mgba carm-import` 只输出 cohort 聚合，不复制患者级记录；`mgba carm-experiment` 运行 CAR-M 7 条件 × 3 seed 矩阵，显式提供 artifact root 时同时保存数据溯源并重建报告。`mgba demo-export` 在内存中回放冻结 CAR-M 矩阵（去掉消融、取 seed 42），向 `artifacts/demo/` 写出自包含单文件 HTML 演示（4 个剂量条件的组织动画、L4 曲线与 L0→L4 细胞检查器）、playbook JSON 和 SHA-256 manifest；内容为冻结配置的字节级确定函数，保留负面基线表述，不写任何 raw artifact。`scripts/mvp_demo.py` 仍冻结为 0.1.0 full/fallback 演示。五层命令可用分层配置替换参考模型；`mgba sten-smoke` 只验证独立的 L3 通信与拓扑不变量。

## 当前目录

```text
M-GBA/
├── data/carm/                # 去标识化 TCGA 代理聚合 profile
├── configs/
│   ├── layers/              # 版本化层模型配置
│   ├── experiments/         # 冻结批量实验矩阵
│   ├── scenarios/carm/      # CAR-M 场景、角色、环境与模型参数
│   ├── runner_reference.json # 多速率时钟与预算
│   ├── multiscale_demo.json # 默认五层纵向契约场景
│   └── demo.json            # L3 STEN 子系统场景
├── docs/
├── scripts/
│   ├── mvp_demo.py          # 冻结 full/fallback 演示
│   ├── synthetic_feedback_benchmark.py # 仿真场景生成与 E4 基准
│   ├── synthetic_policy_benchmark.py # 规则 vs 主动推理 L2 策略基准
│   ├── synthetic_topology_benchmark.py # E5 静态 vs 动态拓扑基准
│   ├── synthetic_e3_benchmark.py # E3 多种子噪声集合基准
│   ├── synthetic_closed_loop_benchmark.py # E4×E3 噪声闭环稳定性基准
│   └── synthetic_neural_benchmark.py # L0/L3 神经变体替换基准
├── src/mgba/
│   ├── layers/              # 五层 DTO 与模型 Protocol
│   │   ├── contracts.py     # 五层 DTO 与 Protocol
│   │   ├── l0.py            # 离散 GRN、静态基线、轨迹与扰动事件
│   │   ├── l1.py            # 翻译/降解模型、静态基线与分子轨迹
│   │   ├── l2.py            # 五态 Cell 模型、静态基线与 Cell 轨迹
│   │   ├── l3.py            # 固定图微环境模型、静态基线与组织轨迹
│   │   └── l4.py            # 宏观表型观察器、窗口结局与静态基线
│   ├── experiment.py        # manifest、实验 ID、事件与 artifact 协议
│   ├── experiments.py       # 配对扰动/消融、逐层效应与矩阵 artifact
│   ├── reporting.py         # raw-only CSV/SVG/HTML 报告重建
│   ├── run_report.py        # 单 run 逐 tick L0–L4 轨迹可视化记录
│   ├── multiscale.py        # 五层参考实现、runner 与 trace
│   ├── runner.py            # 多速率调度、逐 tick trace、checkpoint 与恢复
│   ├── feedback.py          # L4→L3 稳态反馈控制器（PI+反饱和+安全屏障）与固定策略
│   ├── feedback_experiments.py # E4 三条件对照矩阵与 artifact
│   ├── policy_experiments.py # 规则 vs 主动推理 L2 策略对照矩阵与 artifact
│   ├── layers/l2_active_inference.py # 主动推理（EFE）L2 策略与配置
│   ├── topology_experiments.py # E5 静态 vs 动态拓扑对照矩阵与稳定性指标
│   ├── layers/l3_adaptive.py  # 受治理的动态拓扑 L3 模型
│   ├── e3_statistics.py      # E3 预注册判据与分级阶梯
│   ├── e3_experiments.py     # E3 多种子集合运行与 artifact
│   ├── layers/l0_noisy.py   # 种子化转录噪声 L0 模型
│   ├── neural.py            # 纯标准库神经基元（种子化矩阵/MLP/消息传递）
│   ├── layers/l0_neural.py  # 冻结权重 MLP L0 GRN 变体
│   ├── layers/l3_gnn.py     # 冻结权重消息传递 L3 GNN 变体
│   ├── neural_experiments.py # 参考 vs 神经单层替换对照矩阵与 artifact
│   ├── scenarios/carm/      # 数据导入、场景编译、L2/L3 适配器与工作流
│   ├── models.py            # Genome、消息与拓扑协议
│   ├── sten.py              # L3 路由、拓扑、约束和事件
│   ├── simulation.py        # L3 规则 Agent smoke runner
│   └── cli.py
└── tests/
```

## 开发顺序

1. 已完成：六节点离散 GRN 替换默认 L0 占位表达。
2. 已完成：粗粒度翻译/降解模型替换默认 L1 恒等映射。
3. 已完成：由 L1 和局部环境共同驱动的五态 Cell 状态机。
4. 已完成：固定组织图上的局部压力、资源、信号更新与组织聚合。
5. 已完成：只从 L3 聚合的 L4 即时表型、时间窗口和最终结局。
6. 已完成：多速率五层 Runner、相邻快速反馈、检查点和可回放轨迹。
7. 已完成：多强度钳制、L1–L3 静态替换、逐层效应和传播 tick。
8. 已完成：从冻结 raw artifact 字节级重建结果表、逐层效应图、时间序列图和只读报告。
9. 已完成：WP10 的中英文报告、full/fallback 演示、空虚拟环境 wheel 复现和 0.1.0 发布冻结。
10. 已完成：项目所有者于 2026-08-19 接受 E0–E2 范围并授权首次 Git commit、`v0.1.0` tag 与 GitHub 推送。
11. 已完成：CAR-M 真实数据代理锚定场景、群体 L0 扰动、L2/L3 适配器与 21-run 纵向矩阵。
12. 建立有效随机重复和统计协议后，再重新训练层内模型并引入空间 L3、L4 慢反馈、STEN 增强和 LLM Policy。

每次只升级一层，当前标准库参考模型长期保留为可复现基线。
