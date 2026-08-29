# M-GBA

M-GBA（Multi-scale Graph Biological Architecture）是一个跨尺度数字生命研究原型。项目的核心是用可运行模型表达生命状态从微观调控到宏观表型的逐层生成：

比赛版网站：[M-GBA 跨尺度虚拟实验室](https://mgba-cross-scale-lab.zluo66977.chatgpt.site)

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

- 空间 L3 calibration 回应"未锚定"（ADR-0043，2026-08-29）：按 ADR-0025 §4.3 冻结框架，只在 calibration 子集搜索 4 个 L3 参数（105 次评估留痕，incumbent 不劣保证），一次确认 holdout 均 NAE 12.15→8.71（−28.3%）→ **improved**；calibration −28.6%，external 1.33→1.54 如实报告不进门控；field_retention 顶到盒上界已记录（扩盒需另行预注册）；标定配置只存 artifact，冻结配置未动，采纳为新 reference 需另行 ADR。
- Stage 1 完成双源格式交叉校验（ADR-0042，2026-08-29）：GEO 原生管线（MatrixMarket 流式 + guide 归并）与 scPerturb 调和版在 234 个共享单元上 Spearman **0.99993**、方向一致率 **0.9986**（冻结阈值 0.8/0.8），verdict **consistent**；Stage 1 格式处理获独立复现性证据，scPerturb 版仍是唯一入链主源。
- OE 链路多单元/组合/调度扩展完成（ADR-0041，2026-08-29）：配置驱动调度配对 runner 跑通冻结五条件 × 3 seed 矩阵 `empirical-l0-schedule-f562ddbcb6d71d44`——多单元并行把两种语义的 L4 差异放大到 3.24e-04（单单元 2.01e-04），经验臂以约 1/55 的 L0 强度达到同量级 L4 效应；晚 onset 时序效应可见；组合单元携带真实组合测量（最弱）；调度不变量逐位保持（onset 前与 baseline 一致）；全部条件 failed 负基线不变。
- Geneformer 嵌入重训两臂完成（ADR-0040，2026-08-29）：C1 输入 token 嵌入纯查表（1,877 基因，768 维）修复了 KD 的 one-hot 结构退化（ridge 恢复有效基线、两臂均明确优于质心），但 MLP 不优于 ridge（KD −3e-05 / OE −2e-05），两臂按冻结规则均 failed——任务在基因语义空间近似线性；KD 链路继续关闭，负面评估原样登记。结论性对照：OE 可学性来自组合共享成分，KD 单敲低需要新数据维度而非更强特征。
- KD 语义扩展完成首次实验（ADR-0039，2026-08-29）：Replogle K562 CRISPRi（310,385 细胞、1,832 单元）经同构管线产出 profile 与训练评估——**按冻结规则未通过**（holdout MLP MAE 0.014813 仅险胜质心 +7e-06、不优于 ridge −0.000396），verdict failed 原样登记，不生成响应表、不进链路；失败分析指向身份 one-hot 在单样本单元上无共享结构，候选解法是 C1 Geneformer 基因嵌入（需另行 ADR）。
- 训练成果已接入主链（ADR-0038，2026-08-28）：响应表经 passed 门禁蒸馏（`l0-response-table-60c838d81d379f17`），`EmpiricalResponseGrnModel` 作为 L0 层内可选变体（自然动力学与参考 GRN 逐位一致、抽象节点硬钳制语义不变、表内单元按冻结 2^x 规则逐节点审计）；首次配对矩阵 `empirical-l0-6a202fa1b24f1617`（baseline / 硬钳制 / 经验响应 × 3 seed）显示硬钳制 L0 强度高 36 倍但经验多节点模式在 L3/L4 的相对距离更大（4.0e-05/1.96e-04 vs 3.0e-06/5.1e-06），全部条件保持 failed 负基线。核心包仍零依赖。
- L0 扰动响应首次训练实验**通过**冻结规则（ADR-0037，2026-08-28）：种子化 CPU 单线程 MLP 预测六节点扰动响应，holdout MAE 0.009494 严格优于质心（0.012872）与 ridge（0.012280）双基线（margin +0.003378/+0.002786，规则 >1e-12），方向一致率 0.833、Spearman 0.852 同向改善；训练端到端字节级确定性已验证；评估 artifact `l0-training-eval-97216b607136bef0` 已登记（7 条目全绿）。接链由 ADR-0038 完成（见上一条）。
- AIVC Stage 1 已完成首次实证锚定（ADR-0036，2026-08-28）：Norman scPerturb 236 个真实扰动经冻结 Hallmark 六节点桥表达为 L0 语义向量，产出 write-once profile `norman-perturbation-profile-0a0aa914dc9fb080`（digest 拆分 train 188 / holdout 48，train-only 质心 + MAE/方向/Spearman 描述性基线，holdout MAE 0.0129）；已登记 registry（6 条目全绿）。这为 L0 训练提供了实证 target，不构成任何验证结论。
- "本机不训练"阶段前提已由 ADR-0035 解除（2026-08-28，硬件 RTX 5090 32 GB 到位）：训练只在独立虚拟环境、PyTorch 永不进核心零依赖包、每次只训练替换一层、规则基线永久默认；首个训练目标为 L0 扰动响应（A2 scPerturb Norman h5ad 已下载核验；A3/B1/B2/C1 移学校学术资源批次；A1 Hallmark v2026.1 已下载登记，桥拼写经真实数据修正）。
- CAR-M 空间 L3 已完成首次真实数据锚定（2026-08-28）：首次同指标评估 `spatial-score-f693c3da106acdc5` 按预注册判据记为**未锚定**（calibration 平均归一化误差 10.35、holdout 12.15、场指标全部落在观测分布外；external validation 1.33）；ADR-0043 的 calibration 子集参数选择随后按冻结确认规则把该结论翻转为 **improved**（见最新一条）。
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
- `mgba demo-export` 已升级为 CAR-M 跨尺度研究观察台（ADR-0022）：seed-42 baseline/干预双画布同 tick 对照、L3 压力/信号/资源显示投影、配对 L4 曲线、逐细胞 L0→L1→L2→局部 L3 差异和转换事件审计；旧项目 `D:\car-m-virtual-cell` 只提供交互参考，其 ABM/GAT 热路径没有迁移，负面基线原样保留。
- CAR-M 已增加可选因果空间 L3（ADR-0023）：`SpatialTissueState` 把归一化 Cell 坐标、12×12 压力/资源/信号场和半径邻域纳入正式 trace/checkpoint；`mgba carm-spatial-experiment` 运行固定图 vs 空间场的同 seed 单层配对，并报告位移、边周转、场异质性和梯度。它是无量纲 reference model，不是物理扩散或组织重建；原固定图基线与冻结矩阵不变。
- `mgba carm-spatial-ablation` 已完成 movement×field×topology 的 2×2×2 L3 内部审计（ADR-0024）：全关和仅移动均为 L3/L4 零效应负对照；20 tick 描述性主效应显示场耦合的 L4 距离最大（0.048720），空间邻域其次（0.025588），移动最小（0.000898）。这只定位当前 reference rules 的杠杆点，不是统计或疗效证据。
- CAR-M 空间 L3 的外部数据锚定已预注册（ADR-0025/0028）：Wu/Swarbrick Visium 三文件锚定场异质性，Jackson IMC 位置/聚类两文件锚定细胞邻域；Rights 已核验为 CC BY 4.0 / CC BY 1.0 Generic。未被当前指标消费的 mask 归档在下载前移出，最小包现为五文件 241,284,013 bytes、本地峰值 ≤2 GB。用户已授权；最小包已于 2026-08-28 下载核验，运行时模型未变。
- 空间锚点聚合契约已实现（ADR-0026）：`mgba spatial-anchor-build/check` 将有许可与 SHA-256 的临时 observation bundle 转成只有不可逆样本别名和预注册 L3 统计的 write-once target；Wu 4/2 calibration/holdout 和 Jackson external-validation 角色在协议中冻结。旧 `D:\car-m-virtual-cell` 的 TCGA/Tahoe/OmniPath 缓存不含空间真值，ABM 坐标/手工场只作格式参考。真实最小包已于 2026-08-28 落盘并生成首个 target。
- 模型—Target 同指标评估已实现（ADR-0027）：`mgba carm-spatial-anchor-evaluate` 把正式空间 L3 投影为同一 24 个指标，分别报告 calibration 15、holdout 15、external validation 9 共 39 个描述性距离，并保存完整 raw trace；首个真实 target 已评分（2026-08-28，未锚定）；仍无生物验证结论。
- 空间源格式适配器已实现（ADR-0028）：`mgba spatial-source-adapt-field` 流式读取已登记的 10x MatrixMarket，按下载前冻结的三个透明八基因代理生成单位区间场观察；`mgba spatial-source-adapt-neighborhood` 精确连接 Jackson 位置/cluster 表，所有 cluster 必须显式映射到 `immune|tumor|other`。适配器逐文件复核路径、Rights、bytes 和 SHA-256，真实文件已于 2026-08-28 贯通该边界（三处源格式偏差以机械派生处理，冻结配置与适配器未改）；这仍不是外部验证结论。
- AIDO 启发的状态条件序列干预已实现并完成首次实验（ADR-0029）：借鉴“初始状态 + perturbation/environment → 后续状态”的任务形状，不引入 AIDO 权重或中央跨层潜状态。`mgba carm-intervention-experiment` 对同一批 15 个 engineered macrophage 施加等剂量/等暴露次数的 early/late L0 signal pulse；晚期条件在 onset 前与 baseline 逐层零差异。60-tick 首次矩阵中 short/long timing contrast 的终末 L4 距离分别为 0.006580/0.020899；晚期干预减轻 vitality/damage 代价但增加 inflammation，所有条件仍为 `RECOVERED`。这是 reference-rule trade-off，不是疗效或真实 virtual cell 证据。
- 比赛版“跨尺度虚拟实验室”已实现（ADR-0030）：`mgba lab-export` 把三套冻结实验转换为可字节重建的 catalog、按实验延迟加载 bundle 和 SHA-256 manifest；`web/` 提供首页、双轨实验工作台、30 天分享结果页、证据页和离线 Demo。普通首页不加载或渲染黑洞；同源 `event-horizon-visual` Web Component 仅保留为站长显式嵌入或诱捕主题页使用的可选只读展示层，不读取实验数据、不发起网络请求，也不进入 L0–L4 生成链。GitHub Actions 对站点相关 PR/`main` 推送执行锁文件安装、测试、lint、生产构建和 Sites bundle 门禁，并为成功的 `main` 构建保存按 commit 标识的可部署产物；生产发布继续复用现有 Sites 项目，不在 GitHub 保存长期生产凭据。第一版在线入口只接受 CAR-M 状态条件实验的严格枚举，请求与模型版本共同生成确定性 run ID；Cloudflare Worker 负责凭证隔离、R2 保存和显式离线回退，`services/lab-api/` 提供可容器化 Python 执行边界。网站与 API 均在生成链外，不修改 L0–L4 DTO/Protocol 或冻结结果；真实空间 Target 仍明确显示为“尚未生成”。
- 群体动力学观察层已实现（ADR-0031）：`CollectiveDynamicsObserver` 和 `mgba collective-analyze` 只从正式 raw trace 重算 activation-stress reference proxy 的 direction、intensity、polarization、edge alignment、冻结状态转换、外部 cohort、Cell archetype 及 L4 时间关联。三套比赛 bundle 与工作台已加入同步双轨相图；旧 bundle 仍可读取。该能力不进入 tick、不改变 E3 阶梯，也不宣称物理相变、涌现或临床预测。
- OCellus 启发的 Autolab 计划控制面已实现（ADR-0032）：`AutolabPlan` 把冻结注册表编译为 closed-schema DAG，三层 Verifier 分别拒绝 schema/DAG、架构/预算和 manifest/history/科学表述违约；`mgba autolab-plan` 固定 `executed: false`，现有 `mgba autolab` 只有通过前后两道核验才执行和报告。默认计划继续复现原四次评估、`l2-static` leader 和全部 history digest。
- EvenClock 启发的 `ClockSectorObserver` 已实现（ADR-0033）：它从正式 `SpatialTissueState` 与同 tick 可见 L0 状态生成六方向×三归一化距离环的 `mgba-clock-sector-observation-0.1` write-once artifact，不修改坐标、场、边、Cell、checkpoint 或 trace。Wu/Jackson 真实 Target 到位前不比较或宣称该表示优于半径/网格基线。
- OCellus 离线扰动锚点契约已实现（ADR-0034）：`mgba-ocellus-perturbation-anchor-0.1` 严格分离 empirical/predicted gene-level log2FC，冻结 Hallmark 六节点桥、train-only centroid、holdout MAE/方向/Spearman 和许可/SHA-256 门禁；只有通过、精确人审且引用 holdout 的结果才能生成 `executed: false` 的 L0 schedule 候选。当前没有下载 OCellus 权重，也没有真实 OCellus 结果。
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
- L2 规则参数标定已作为预注册实验接入（ADR-0018）：`mgba.calibration` 纯搜索核心（sha256 种子扫描 + 坐标细化，参考向量恒为首个评估点）+ `scripts/calibrate_l2_cell.py`；首次运行训练 +0.385、四档 holdout 全部提升（calm/injury 结局 `failed → stable`，severe/collapse 仍 `failed`），判定 `generalized`；冻结参考配置不被修改，标定结果不进入任何冻结协议。
- L2 已增加可选连续潜状态"虚拟细胞"策略（ADR-0019）：AIVC 架构类的层内实例化——冻结种子派生权重（非训练）的嵌入 + 泄漏 tanh 递推 + 非死亡四相读出，潜状态每 tick 从正式 `CellState` 确定性重建（无隐藏记忆）；规则状态机原样保留为默认与永久基线，替换仅隔离"状态表示→相位映射"一个变量。`mgba latent-experiment` 配对对照与 `scripts/synthetic_latent_benchmark.py` 仿真基准可执行；默认场景跨层效应 ≤1e-12、结局一致（`FAILED`），保留为零结果基线。
- AIVC 真实数据/模型对接的分级下载清单在 **`data/aivc/`**（纯调查，全部待授权未下载；含六抽象节点 ↔ Hallmark 基因集语义桥与 Stage 1–3 资源表）。
- 自动实验调度器元层已接入（ADR-0020）：`mgba autolab` 在预注册假设注册表上运行冻结"筛选→确认"确定性闭环（元层，不进 tick 循环），首次会话 4 次评估内自主复现 WP8 结论（L2 最大杠杆点，30→100 tick 稳健）；`mgba autolab-propose` 提供 fail-closed 提案验证通道（永不自动执行），为未来 LLM 假设提出器预留唯一入口。
- 多数据集存放与多细胞类型约定已固化（ADR-0021）：入库数据集统一登记 **`data/registry.json`**，`mgba data-check` 为 fail-closed 校验门禁；细胞类型只由 L0 `Genome` 模板表达，跨类型交互只经 L3 边与环境场——`configs/multiscale_coculture_demo.json` 用纯配置两种群共培养场景证明了这一点（零契约变更）。

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
- [ADR-0018：L2 规则参数标定](docs/决策记录/ADR-0018-L2规则参数标定.md)
- [ADR-0022：CAR-M 跨尺度研究观察台](docs/决策记录/ADR-0022-CAR-M跨尺度研究观察台.md)
- [ADR-0023：CAR-M 可检查点因果空间 L3](docs/决策记录/ADR-0023-CAR-M因果空间L3.md)
- [CAR-M 因果空间 L3 首次实验记录](docs/实验记录/CAR-M-spatial-L3-2026-08-21.md)
- [ADR-0024：CAR-M 空间 L3 机制因子审计](docs/决策记录/ADR-0024-CAR-M空间L3机制因子审计.md)
- [CAR-M 空间 L3 机制审计记录](docs/实验记录/CAR-M-spatial-ablation-2026-08-21.md)
- [ADR-0025：CAR-M 空间数据锚定预注册](docs/决策记录/ADR-0025-CAR-M空间数据锚定预注册.md)
- [CAR-M 空间数据下载前清单](data/spatial-carm/README.md)
- [ADR-0026：CAR-M 空间锚点聚合契约](docs/决策记录/ADR-0026-CAR-M空间锚点聚合契约.md)
- [旧 CAR-M 空间资产审计记录](docs/实验记录/CAR-M-legacy-spatial-assets-audit-2026-08-21.md)
- [ADR-0027：CAR-M 空间 Target 同指标评估](docs/决策记录/ADR-0027-CAR-M空间Target同指标评估.md)
- [ADR-0028：CAR-M 空间源格式适配器与三通道代理映射](docs/决策记录/ADR-0028-CAR-M空间源格式适配器.md)
- [ADR-0029：AIDO 启发的状态条件序列干预协议](docs/决策记录/ADR-0029-AIDO启发的状态条件序列干预.md)
- [ADR-0030：比赛版跨尺度虚拟实验室](docs/决策记录/ADR-0030-比赛版跨尺度虚拟实验室.md)
- [ADR-0031：群体动力学观察层](docs/决策记录/ADR-0031-群体动力学观察层.md)
- [ADR-0032：OCellus 启发的 Autolab 计划控制面](docs/决策记录/ADR-0032-OCellus启发的Autolab计划控制面.md)
- [ADR-0033：EvenClock 启发的 ClockSector 空间观察层](docs/决策记录/ADR-0033-EvenClock启发的ClockSector观察层.md)
- [ADR-0034：OCellus 离线扰动锚点契约](docs/决策记录/ADR-0034-OCellus离线扰动锚点契约.md)
- [ADR-0035：解除不训练前提与 L0 训练轨道](docs/决策记录/ADR-0035-解除不训练前提与L0训练轨道.md)
- [ADR-0036：AIVC Norman 实证锚点契约](docs/决策记录/ADR-0036-AIVC-Norman实证锚点契约.md)
- [ADR-0037：L0 扰动响应首次训练契约](docs/决策记录/ADR-0037-L0扰动响应首次训练契约.md)
- [ADR-0038：实证响应表接入 L0 契约](docs/决策记录/ADR-0038-实证响应表接入L0契约.md)
- [ADR-0039：KD 语义扩展契约](docs/决策记录/ADR-0039-KD语义扩展契约.md)
- [ADR-0040：Geneformer 嵌入特征重训契约](docs/决策记录/ADR-0040-Geneformer嵌入特征重训契约.md)
- [ADR-0041：OE 链路多单元与调度扩展契约](docs/决策记录/ADR-0041-OE链路多单元与调度扩展契约.md)
- [ADR-0042：GEO 原生交叉校验契约](docs/决策记录/ADR-0042-GEO原生交叉校验契约.md)
- [ADR-0043：CAR-M 空间 L3 标定契约](docs/决策记录/ADR-0043-CAR-M空间L3标定契约.md)
- [CAR-M 空间 L3 calibration 记录](docs/实验记录/CAR-M-spatial-calibration-2026-08-29.md)
- [Stage 1 GEO 交叉校验记录](docs/实验记录/Stage1-GEO-native-crosscheck-2026-08-29.md)
- [OE 多单元/调度扩展实验记录](docs/实验记录/OE-multi-unit-schedule-2026-08-29.md)
- [Geneformer 嵌入重训实验记录（两臂未通过）](docs/实验记录/Geneformer-embedding-retrain-2026-08-29.md)
- [KD 首次训练实验记录（负面结果）](docs/实验记录/KD-replogle-first-training-2026-08-29.md)
- [实证响应接入 L0 首次配对实验记录](docs/实验记录/L0-empirical-response-first-matrix-2026-08-28.md)
- [L0 扰动响应首次训练实验记录](docs/实验记录/L0-perturbation-response-training-2026-08-28.md)
- [AIVC Stage 1 首次实证锚定记录](docs/实验记录/AIVC-Norman-Stage1-2026-08-28.md)
- [CAR-M 状态条件序列干预首次实验记录](docs/实验记录/CAR-M-state-conditioned-intervention-2026-08-21.md)
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
.\.venv\Scripts\mgba carm-spatial-experiment --artifact-root artifacts/carm-spatial
.\.venv\Scripts\mgba carm-spatial-ablation --artifact-root artifacts/carm-spatial-ablation
.\.venv\Scripts\mgba demo-export
.\.venv\Scripts\mgba lab-export --dose-playbook artifacts\demo\carm-playbook.json --output-dir web\public\lab-data
.\.venv\Scripts\mgba collective-analyze --input artifacts\run.json --output artifacts\collective.json
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
.\.venv\Scripts\python scripts/calibrate_l2_cell.py
.\.venv\Scripts\mgba latent-experiment --artifact-root artifacts/latent
.\.venv\Scripts\python scripts/synthetic_latent_benchmark.py run
.\.venv\Scripts\mgba autolab-plan --artifact-root artifacts/autolab-plans
.\.venv\Scripts\mgba autolab --artifact-root artifacts/autolab
.\.venv\Scripts\mgba autolab-propose --proposals <提案文件.json>
.\.venv\Scripts\mgba data-check
.\.venv\Scripts\mgba sten-smoke --config configs/demo.json
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python -B -m coverage run -m unittest discover -s tests
.\.venv\Scripts\python -B -m coverage report --fail-under=80
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
.venv/bin/mgba carm-spatial-experiment --artifact-root artifacts/carm-spatial
.venv/bin/mgba carm-spatial-ablation --artifact-root artifacts/carm-spatial-ablation
.venv/bin/mgba demo-export
.venv/bin/mgba lab-export --dose-playbook artifacts/demo/carm-playbook.json --output-dir web/public/lab-data
.venv/bin/mgba collective-analyze --input artifacts/run.json --output artifacts/collective.json
.venv/bin/mgba feedback-experiment --artifact-root artifacts/e4
.venv/bin/python scripts/synthetic_feedback_benchmark.py generate
.venv/bin/python scripts/synthetic_feedback_benchmark.py run
.venv/bin/mgba autolab-plan --artifact-root artifacts/autolab-plans
.venv/bin/mgba data-check
.venv/bin/mgba sten-smoke --config configs/demo.json
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -B -m coverage run -m unittest discover -s tests
.venv/bin/python -B -m coverage report --fail-under=80
.venv/bin/python scripts/mvp_demo.py --mode full --artifact-root artifacts/mvp-demo
```

覆盖率门禁只计量 `src/mgba` 核心包，`source` 与 `fail_under=80` 由 pyproject `[tool.coverage]` 提供；coverage 经 `pip install -e .[dev]` 装入开发环境（wheel 运行时零依赖不变）。coverage 追踪开销使全套测试约需 15–20 分钟，因此它是独立门禁，不替代上面的快速测试命令。
`mgba run` 保留单 tick 契约演示。`mgba simulate` 默认执行 100 个新增 tick，可用 checkpoint 暂停恢复。`mgba experiment` 运行冻结 WP8 矩阵；只有显式给出 `--artifact-root` 才保存完整 raw/derived JSON。`mgba report` 验证并从该 raw artifact 重建 WP9 只读报告，默认写入矩阵内的 `derived/report/`。`mgba run-report` 从单个保存的 run artifact（`simulate --trace-out` 或矩阵 raw run）重建逐 tick 的 L0–L4 轨迹记录：6 张 SVG 折线图、6 个 CSV、只读 HTML 摘要和 SHA-256 manifest，默认写入 run 文件旁的 `<名称>-report/`；默认输出落在 raw 目录内会拒绝，需显式 `--output-dir`。`mgba collective-analyze` 对一个正式 raw run 做只读群体动力学分析，可选完整的 Cell→cohort JSON 映射，并把 `mgba-collective-dynamics-0.1` report 以 write-once 方式保存；它不拟合预测模型或修改 run。`mgba autolab-plan` 只编译或验证 closed-schema 计划并固定输出 `executed: false`；现有 `mgba autolab` 在真正调用 evaluator 前后分别执行计划 preflight 和 manifest/history 核验。`mgba carm-import` 只输出 cohort 聚合，不复制患者级记录；`mgba carm-experiment` 运行 CAR-M 7 条件 × 3 seed 冻结矩阵，显式提供 artifact root 时同时保存数据溯源并重建报告。`mgba carm-intervention-experiment` 运行相同 L0 clamp 的 early/late 等暴露 schedule，审计 onset 前零差异、timing contrast 和完整 raw trace；它不导入 AIDO 权重。`mgba carm-spatial-experiment` 运行固定图与可检查点空间 L3 的 2 条件 × 3 seed 对照，单独保存 raw run、空间指标、manifest 和 derived summary；它不修改冻结 CAR-M 矩阵。`mgba carm-spatial-ablation` 运行固定图参考加八个 movement×field×topology 因子组合，以一个显式 seed 做确定性机制审计并保存九份 raw run；该命令不把重复确定性运行包装成统计证据。`mgba spatial-source-adapt-field/neighborhood` 从逐文件核验的 10x/CSV 源生成临时 observation bundle；`mgba spatial-anchor-build` 再从 bundle 构建去标识 L3 聚合 target，`spatial-anchor-check` 重算身份并检查 raw 标识泄漏；`mgba carm-spatial-anchor-evaluate` 把正式空间 L3 投影到同一指标空间并按 calibration/holdout/external validation 分开评分，这五条命令都不进入生成热路径或自动调参。`mgba demo-export` 保留自包含单文件研究观察台与完全离线兜底。`mgba lab-export` 只读取已经存在的 raw/frozen artifact，将三套比赛实验转换为统一 `LabRunBundle`、小型 catalog 和文件 SHA-256 manifest；它不执行参数搜索、不修改 raw artifact，也不把显示状态反馈进模型。网站本地运行使用 `cd web; npm install; npm run dev`，验证使用 `npm test; npm run lint; npm run build`；在线功能默认关闭，只有配置 `LAB_LIVE_RUNS_ENABLED=true`、`MGBA_RUNNER_BASE_URL` 与 Worker 私有 `MGBA_RUNNER_TOKEN` 后才代理到容器服务。`scripts/mvp_demo.py` 仍冻结为 0.1.0 full/fallback 演示。`mgba data-check` 按 `data/registry.json` 逐条校验入库数据集。五层命令可用分层配置替换参考模型；`mgba sten-smoke` 只验证独立的 L3 通信与拓扑不变量。

## 当前目录

```text
M-GBA/
├── data/carm/                # 去标识化 TCGA 代理聚合 profile
├── data/synthetic-feedback/  # 合成压力档场景集（manifest 内逐场景 sha256）
├── data/aivc/                # 外部资源清单先行区（全部待授权，未下载）
├── data/spatial-carm/        # CAR-M L3 空间数据锚定清单（已授权；网络阻塞未下载）
├── data/registry.json        # 入库数据集登记表；mgba data-check 门禁（ADR-0021）
├── configs/
│   ├── layers/              # 版本化层模型配置
│   ├── experiments/         # 冻结批量实验矩阵
│   ├── scenarios/carm/      # CAR-M 场景、角色、环境与模型参数
│   ├── runner_reference.json # 多速率时钟与预算
│   ├── multiscale_demo.json # 默认五层纵向契约场景
│   ├── multiscale_coculture_demo.json # 两种群共培养契约场景（ADR-0021）
│   └── demo.json            # L3 STEN 子系统场景
├── docs/
├── scripts/
│   ├── mvp_demo.py          # 冻结 full/fallback 演示
│   ├── synthetic_feedback_benchmark.py # 仿真场景生成与 E4 基准
│   ├── synthetic_policy_benchmark.py # 规则 vs 主动推理 L2 策略基准
│   ├── synthetic_latent_benchmark.py # 规则 vs 潜状态 L2 策略基准
│   ├── synthetic_topology_benchmark.py # E5 静态 vs 动态拓扑基准
│   ├── synthetic_e3_benchmark.py # E3 多种子噪声集合基准
│   ├── synthetic_closed_loop_benchmark.py # E4×E3 噪声闭环稳定性基准
│   ├── synthetic_neural_benchmark.py # L0/L3 神经变体替换基准
│   └── calibrate_l2_cell.py     # L2 规则参数标定（预注册搜索 + holdout）
├── services/lab-api/          # 受限配对实验 Python 服务与 Docker 镜像
├── web/                       # Cloudflare/Sites React 实验室、Worker API 与 R2 分享缓存
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
│   ├── latent_experiments.py # 规则 vs 潜状态 L2 策略对照矩阵与 artifact
│   ├── layers/l2_latent.py    # 连续潜状态"虚拟细胞"L2 策略与配置
│   ├── autolab.py           # 元层自动实验调度（注册表 + 筛选→确认 + 提案门禁）
│   ├── autolab_planning.py  # closed-schema Autolab 计划编译与三层验证（ADR-0032）
│   ├── clock_sector.py      # 只读六方向×三距离环空间观察 artifact（ADR-0033）
│   ├── ocellus_anchors.py   # 离线扰动预测/真实 Target 六节点锚点（ADR-0034）
│   ├── data_registry.py     # 数据集注册表加载与 sha256 校验（ADR-0021）
│   ├── topology_experiments.py # E5 静态 vs 动态拓扑对照矩阵与稳定性指标
│   ├── carm_spatial_experiments.py # CAR-M 固定图 vs 因果空间 L3 配对实验
│   ├── carm_spatial_ablation.py # CAR-M 空间 L3 的 2×2×2 机制审计
│   ├── spatial_anchors.py   # observation bundle → 去标识 L3 target（ADR-0026）
│   ├── spatial_anchor_evaluation.py # SpatialTissueState → target 同指标评分（ADR-0027）
│   ├── spatial_source_adapters.py # 10x/IMC 源文件 → observation bundle（ADR-0028）
│   ├── intervention_experiments.py # 状态条件 L0 schedule 与 timing contrast（ADR-0029）
│   ├── lab.py              # Lab request/bundle/catalog 契约与确定性导出器（ADR-0030）
│   ├── collective_dynamics.py # 只读群体相图、状态转换、cohort 与 L4 时间关联（ADR-0031）
│   ├── lab_server.py       # 受服务凭证保护的受限在线执行边界
│   ├── layers/l3_adaptive.py  # 受治理的动态拓扑 L3 模型
│   ├── e3_statistics.py      # E3 预注册判据与分级阶梯
│   ├── e3_experiments.py     # E3 多种子集合运行与 artifact
│   ├── layers/l0_noisy.py   # 种子化转录噪声 L0 模型
│   ├── neural.py            # 纯标准库神经基元（种子化矩阵/MLP/消息传递）
│   ├── layers/l0_neural.py  # 冻结权重 MLP L0 GRN 变体
│   ├── layers/l3_gnn.py     # 冻结权重消息传递 L3 GNN 变体
│   ├── neural_experiments.py # 参考 vs 神经单层替换对照矩阵与 artifact
│   ├── calibration.py       # 预注册确定性参数搜索核心（扫描+坐标细化）
│   ├── scenarios/carm/      # 数据导入、场景编译、L2/L3 适配器、空间 L3 与工作流
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
12. 已完成：CAR-M 可检查点因果空间 L3 与固定图单层配对实验；不改冻结 CAR-M 矩阵。
13. 已完成：移动×场×空间邻域的 L3 内部因子审计，定位当前 L4 差异主要来自场耦合与邻域而非移动。
14. 已完成：CAR-M 局部场/细胞邻域锚点的资源、预算、指标、4/2 holdout 协议、去标识 target 管线和模型同指标评估器；外部数据仍待用户授权。
15. 已完成：比赛版跨尺度虚拟实验室、三套延迟加载的预计算 bundle、受限 Worker/API/R2 分享链和 Docker 后端；默认关闭 live runner，保留离线 HTML。
16. 已完成：生成链外群体动力学观察层、冻结阈值分类、外部 cohort、L4 时间关联和网站双轨相图；不拟合 Ising/Glauber 模型，不改变 E3 分级。
17. 已完成：OCellus 启发的 Autolab closed-schema 计划编译、固定 Router 清单和三层 Verifier；无在线 LLM、无自动改计划。
18. 已完成：ClockSector 生成链外空间观察器及 OCellus 离线扰动锚点契约；当前都只有契约证据，不宣称表示或模型优越。
19. 下一步在网络可达后下载已授权的 Wu/Jackson 最小文件集，生成真实 target 并执行首次 reference score；只有 calibration 选择与一次性 holdout/external validation 结果均按冻结协议输出后，才决定是否允许 L3 参数锚定。OCellus 权重仍须等待公开、许可、预算与单独授权。

每次只升级一层，当前标准库参考模型长期保留为可复现基线。
