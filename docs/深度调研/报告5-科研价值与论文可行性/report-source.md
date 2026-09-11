# M-GBA 项目科研价值与论文发表可行性评估

**评估日期：** 2026-09-03  
**评估对象：** 本地仓库 `M-GBA-main`，版本标记 v0.2.0  
**方法：** 仓库与实验产物审计、独立复现门禁、Sciverse 学术语义证据、联网一手文献核验  
**结论等级：** 当前状态 / 补强后可投 / 不宜主张

## 执行摘要

### 一句话结论

**能发论文，但不能以“已经获得可信的跨尺度生物预测、CAR-M 疗效结论或数字生命涌现”为主张投稿。** 当前最有把握的路线是把 M-GBA 收敛为一篇“证据治理与可复现跨尺度仿真软件”论文；若要投计算生物学方法论文，必须先完成真正的未见扰动/未见背景外推和独立空间数据验证。以现有结果直接投稿生物学发现型论文，证据不足。

### 投稿可行性分档

| 论文类型 | 当前判断 | 主要理由 | 达到可投状态的最短路径 |
|---|---|---|---|
| 生物学发现 / CAR-M 疗效论文 | **不宜投稿** | 主链多数层是无量纲 reference rules；没有 CAR-M 干预数据校准，也没有湿实验验证 | 获取真实 CAR-M 共培养、类器官或动物干预数据，预注册并做独立外部验证 |
| 计算生物学方法论文 | **尚未达到** | Norman 聚合 holdout 为正，但重新分层后对“成分全未见”样本不优于质心；Replogle KD 任务未胜 ridge；空间 holdout 明显未锚定 | 聚焦一个窄任务，采用 component/context-disjoint split、多数据集、强基线、置信区间和一次性外部测试 |
| 科研软件论文 | **有潜力，需重大补强** | 架构、审计链、不可变产物、测试和负结果治理较强；但基础架构已有 Vivarium/PhysiCell/PhysiBoSS 等先例，且仓库缺 LICENSE、CONTRIBUTING、CITATION，公开开发史也可能过短 | 将新颖性收敛到“evidence-governed/replayable testbed”，补齐开源治理并完成同类软件对比基准 |
| 预印本 / 技术报告 | **现在即可** | 可以诚实报告架构、证据分级、负结果与诊断性重分析 | 明确写成“软件与证据治理报告”，不得包装成已验证的 virtual cell |

### 最重要的判断

1. **工程成熟度明显高于科研有效性。** 605 项测试全部通过，数据登记校验通过，追踪与不可变产物设计严谨；这证明软件按定义执行，不等于定义本身符合真实生物学。
2. **五层架构本身的新颖性有限。** Vivarium 已提供异构过程的跨尺度组合与多速率执行；PhysiCell/PhysiBoSS 已连接细胞内信号、细胞行为、组织空间和微环境。M-GBA 更可能的新颖点是“相邻层契约 + 证据等级 + 预注册门禁 + 负结果保留 + 可重放审计链”，而不是 L0–L4 分层本身。
3. **现有最强的机器学习正结果主要是插值，不是严格外推。** Norman holdout 的 MLP 总体优于质心和 ridge；但本次按训练集中是否见过扰动成分重新分层后，在 10 个成分全未见 holdout 单元上，MLP MAE 为 0.013225，反而高于质心 0.012533。
4. **空间链仍未与真实组织量级对齐。** 原 reference trajectory 在 15 个 calibration 指标和 15 个 holdout 指标上均无一落入观察范围；后续标定又因 105 次实际评估超过预注册的 89 次上限，被项目自身降级为探索性诊断。这是科研诚信优点，也是当前不能主张泛化的直接证据。
5. **最好的投稿策略是先做减法。** 不要同时证明“扰动预测、空间组织、CAR-M 干预、闭环恢复、涌现”。选一个可证伪问题，其余层只作为固定基础设施。

## 1. 评估范围与判据

本评估把“科研价值”拆成六个互不替代的维度：

- **问题价值：** 是否回答明确、可证伪且对同行有用的问题；
- **方法新颖性：** 是否超出已有跨尺度仿真与 perturbation-prediction 框架；
- **经验有效性：** 是否在未见条件或独立数据上得到可重复的预测优势；
- **统计充分性：** 是否有正确的独立样本单位、强基线、重复、区间估计和预注册；
- **可复现性：** 是否能从代码、配置、数据身份和原始轨迹重建结论；
- **可发表性：** 是否满足论文类型对应的最低证据与开源治理要求。

这里特别区分四件事：代码测试通过、模拟结果可重复、模型在数据上拟合、模型对新生物条件有效。前两项是软件证据，后两项才是预测性科学证据。

## 2. 仓库审计结果

### 2.1 已经具备的科研软件资产

| 资产 | 本次核验 | 科研意义 |
|---|---:|---|
| 核心 Python 代码 | 约 27,807 行 | 不是空壳或单 notebook；已有完整仿真、实验和报告链 |
| 测试代码 | 约 14,885 行，605 项 | 覆盖契约、确定性、篡改拒绝、CLI 和实验矩阵 |
| 架构决策记录 | 46 份 ADR | 对预注册、失败、边界和协议变更有较强追踪性 |
| 数据/产物登记 | 18 条全部通过 SHA-256 校验 | 支持数据身份和派生产物追溯 |
| 版本与 CI | v0.1.0、v0.2.0；Python 3.11/3.12 与 Web CI | 有基本发行与自动化门禁 |
| 独立执行 | `605/605`；data-check、run、sten-smoke 通过 | 软件可运行，冻结身份保持 |

主链明确执行 L0→L1→L2→L3→L4，相邻层数据结构、版本、source digest、checkpoint 和结果摘要均可追踪。`mgba run` 的机器可读输出还明确标注 `model_status: contract-demonstrator-not-biological-model`。这种自我约束比许多原型项目更可靠。

### 2.2 当前开源发表障碍

本地仓库未发现 `LICENSE`、`CONTRIBUTING.md` 或 `CITATION.cff`；`pyproject.toml` 也没有软件许可证元数据。提交 JOSS 等软件期刊时，OSI 批准的许可证是硬要求，贡献与支持路径、公开迭代史和外部使用也是重要筛选项。[JOSS 当前审稿标准](https://joss.readthedocs.io/en/latest/review_criteria.html)要求实际 LICENSE 文件、文档、测试、同类软件比较和科研影响证据；[JOSS 投稿要求](https://joss.readthedocs.io/en/latest/submitting.html)还规定公开开发史应超过六个月，并反对主要提交集中在数周内的仓库历史。

本地 Git 记录显示 20 次提交，日期集中在 2026-08-19 至 2026-09-02，且提交者身份属于同一作者。若 GitHub 公开历史同样短，则现在投 JOSS 有较高的 desk-reject 风险。这个问题不能靠补一份 `paper.md` 在一周内解决，需要真实的公开迭代和使用证据。

## 3. 科学证据逐项评估

### 3.1 L0 扰动响应：有可复现正结果，但严格泛化不足

Norman 2019 K562 CRISPRa 任务把每个扰动单元映射到六个 Hallmark 聚合抽象节点。188 个训练单元、48 个 holdout 单元；32 隐单元 MLP、ridge 和训练质心在冻结协议下比较。仓库登记的 holdout 指标为：

| 模型 | 六节点 MAE | 方向一致率 | Spearman |
|---|---:|---:|---:|
| 质心 | 0.012872 | 0.7014 | 0.7905 |
| Ridge | 0.012280 | 0.6563 | 0.6560 |
| MLP | **0.009494** | **0.8333** | **0.8524** |

按仓库预注册规则，MLP 同时胜过质心和 ridge，因此 verdict 为 `passed`。这是一个真实、可重算的内部正结果。

但 split 是按扰动单元哈希划分，而不是按扰动基因成分划分。为检验“未见成分泛化”，本次从 `l0-response-predictions.json` 重新计算：先从训练单元提取 95 个出现过的扰动成分，再把 holdout 分为 all-seen、partial 和 all-unseen。

| Holdout 层级 | n | 质心 MAE | Ridge MAE | MLP MAE | 解释 |
|---|---:|---:|---:|---:|---|
| 所有成分训练见过 | 37 | 0.013068 | 0.010247 | **0.008536** | MLP 的优势主要来自该层 |
| 部分成分见过 | 1 | 0.009019 | 0.008565 | **0.007644** | 样本过少，不能推断 |
| 所有成分均未见 | 10 | **0.012533** | 0.020174 | 0.013225 | MLP 不优于质心 |

因此，当前证据支持“在同一数据集、相同抽象靶标、以单元随机拆分为主的预测改进”，不支持“对新基因扰动有可靠外推能力”。这与当前 perturbation-prediction 领域的主要警示一致：Ahlmann-Eltze 等在 Nature Methods 报告复杂模型尚未稳定胜过简单线性基线；Systema 在 10 个数据集上指出常用指标容易被系统性变化抬高，未见扰动的特异效应仍非常难预测。[Nature Methods 基线研究](https://www.nature.com/articles/s41592-025-02772-6.pdf)；[Systema](https://www.nature.com/articles/s41587-025-02777-8)

2025 Virtual Cell Challenge 的官方复盘也指出，提交模型尚未在所有指标上稳定超过朴素基线；官方评价尺度明确把 context mean baseline 设为 0、实验 split-half 设为 1。这说明 M-GBA 未来不能只用一个 MAE 和一个随机 holdout 证明“virtual cell”能力。[Arc 2025 复盘](https://arcinstitute.org/news/virtual-cell-challenge-2025-wrap-up)；[VCC 指标说明](https://vcc-cli-wiki.virtualcellchallenge.org/)

### 3.2 Replogle KD：负结果具有科研价值，但尚不能成为方法主张

Replogle K562 CRISPRi 主臂使用 1,426 个训练单元、354 个 holdout 单元、Geneformer 768 维输入与 56 维 Hallmark 结构化输出。冻结六节点头的 holdout MAE 为：质心 0.014819、ridge 0.014181、MLP 0.014219。MLP 比质心好，但比 ridge 差 3.74×10⁻⁵，按规则 verdict 为 `failed`。

该结果的价值不是“模型成功”，而是排除了两个看似合理的补救方向：更强的 Geneformer 特征没有让非线性 MLP 胜过 ridge；把目标扩展为 Hallmark 结构化监督也没有恢复 KD 主任务优势。项目如实冻结并关闭该路线，体现了良好的证据纪律。若写方法论文，可把它纳入更大规模、多方法、多数据集的“何时复杂模型不优于线性基线”研究；单独一组失败实验尚不足以构成论文。

### 3.3 空间组织与 CAR-M：数据锚点真实，模型锚定失败

项目使用 Wu 乳腺癌空间转录组和 Jackson 乳腺癌 IMC 数据构建聚合空间锚点。原 reference trajectory 的分角色得分为：

| 角色 | 指标数 | 平均归一化绝对误差 | 落入观察范围比例 |
|---|---:|---:|---:|
| Calibration | 15 | 10.3478 | 0.00 |
| Holdout | 15 | 12.1461 | 0.00 |
| External validation（邻域） | 9 | 1.3274 | 1.00 |

前两组结果直接说明无量纲 reference fields 没有匹配真实空间分布。邻域组虽全部落入观察范围，但其范围来自跨样本聚合，且平均误差仍超过一个归一化尺度，只能视为弱描述性一致。仓库自己的 scientific boundary 也明确说，这不是 likelihood、p-value、生物验证或疗效分数。

后续空间标定把历史结果写成 `improved`，但 ADR-0044 发现实际 105 次评估超过预注册 89 次上限，因而把全部结果降级为探索性参数诊断，并认定当前 target 已消费、不得复用作确认。这一处理提高了项目的可信度，却同时意味着目前没有确认性的空间泛化结果。

更关键的是生物问题与验证数据不完全对齐。Wu 数据是乳腺癌生态图谱，Jackson IMC 是乳腺癌肿瘤生态系统；二者都不是 CAR-M 干预后的治疗响应数据。[Wu 等乳腺癌图谱](https://www.nature.com/articles/s41588-021-00911-1)；[Jackson 等 IMC 图谱](https://www.nature.com/articles/s41586-019-1876-x)。CAR-M 的生物学合理性来自真实研究，例如 Klichinsky 等的早期 CAR-M 研究和 2025 年免疫完整模型中 CAR-M 与 PD-1 阻断的联用研究，但这些结果没有被 M-GBA 直接用于参数识别或独立预测验证。[Klichinsky 等](https://www.nature.com/articles/s41587-020-0462-y)；[Pierini 等](https://www.nature.com/articles/s41467-024-55770-1)

作为对照，空间 QSP/ABM 研究已经把模型输出与同一临床试验中的 IMC、Visium 及治疗结局对应起来，即使如此仍把患者数和未来验证列为限制。[HCC spQSP 研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC10462044/)。这代表了 M-GBA 若要提出 CAR-M 科学主张所需接近的验证标准：疾病、治疗、时间点和样本层级必须与模型问题一致。

### 3.4 其他仿真结果：适合诊断模型，不适合推出生物结论

仓库中的 L2 主动推断、latent 模型、反馈/闭环、动态拓扑、冻结权重 neural L0/L3 等实验多数是负结果、近零效应或 contract demonstrator。CAR-M timing 矩阵的多个 seed 产生相同数值，主要验证确定性重放而不是估计生物变异。当前“全部 RECOVERED”“晚期干预的 vitality/inflammation trade-off”等结论只描述 reference rules 的内部响应；由于 L4 阈值和相邻层映射也是手工冻结规则，不能外推为治疗策略。

这一点不是缺点本身。负结果和模型内敏感性分析可以服务于软件论文或方法开发记录；问题在于不能把“内部可控性”写成“外部预测性”。

## 4. 与现有工作的关系：真正的新颖点在哪里

### 4.1 已被现有框架覆盖的部分

- **异构模型组合与多尺度执行：** Vivarium 可把 agent-based、ODE、随机反应、代谢约束、物理和空间扩散模块组合成复合模型，并支持离散事件与多 CPU 执行。[Vivarium](https://pubmed.ncbi.nlm.nih.gov/35134830/)
- **细胞—微环境—组织空间模拟：** PhysiCell 已提供 3D 细胞力学、迁移、死亡、增殖与扩散底物，并可扩展到 10⁵–10⁶ 细胞量级。[PhysiCell](https://pubmed.ncbi.nlm.nih.gov/29474446/)
- **细胞内信号到群体表型：** PhysiBoSS 把 MaBoSS Boolean signaling 与 PhysiCell ABM 连接，研究遗传/环境改变如何传播到多细胞行为；2.0 版本进一步强调解耦和模型无关设计。[PhysiBoSS](https://pubmed.ncbi.nlm.nih.gov/30169736/)；[PhysiBoSS 2.0](https://pubmed.ncbi.nlm.nih.gov/37903760/)

因此，“可以跨层连接模型”“每层可替换”“具有动态图或空间场”本身不足以支撑方法新颖性。

### 4.2 M-GBA 可能成立的差异化贡献

M-GBA 最值得保留并论文化的，不是一个更大的生物故事，而是一套较严格的**证据治理机制**：

1. 只允许相邻层传递，明确区分层内替换和跨层契约；
2. 每个状态、模型版本、配置、源码和结果都有可追踪 digest；
3. 原始轨迹 append-only，派生报告可从 raw 重建；
4. 预注册预算、holdout 消费和 write-once 门禁进入可执行代码；
5. 负结果保留且不能因“失败”阻止阶段完成；
6. 声称等级从 contract demonstrator 到 validated result 显式分级。

Sciverse 的全文语义证据显示，Fletcher 与 Osborne 把多细胞跨尺度建模的标准、可重复性、互操作性和 benchmark 明确列为核心开放挑战，并强调要把生物过程定义与 in-silico 扰动定义分离，再通过共同 benchmark 比较软件和建模假设（Sciverse doc `878336…`, offset 25800）。联网核验的开放版本给出相同结论。[Seven challenges in the multiscale modeling of multicellular tissues](https://pmc.ncbi.nlm.nih.gov/articles/PMC11478939/)

这为 M-GBA 的“证据治理型测试床”定位提供了学术问题依据，但仍需与 Vivarium、PhysiCell/PhysiBoSS、CompuCell3D/Morpheus 等做可执行对比，证明它不是仅靠文档约定实现的同义包装。

## 5. 论文路线建议

### 路线 A：科研软件论文（推荐，风险最低）

**建议主张：** M-GBA 是一个 evidence-governed、replayable 的跨尺度生物仿真测试床，用于把模型替换、预注册实验、负结果与证据等级连接成可执行工作流。

**不要主张：** validated virtual cell、digital life、CAR-M efficacy prediction、emergent organism intelligence。

**建议题目：**  
*M-GBA: An Evidence-Governed and Replayable Testbed for Multiscale Biological Simulation*

**投稿前硬任务：**

1. 添加 OSI 许可证、`CITATION.cff`、`CONTRIBUTING.md`、支持/治理说明和 AI 使用披露；
2. 提供一个干净环境中的一键安装与一键复现实验；给依赖、数据获取和运行时资源锁版本；
3. 把论文主示例压缩到两个：一个纯 contract 示例，一个真实数据锚定但明确失败/成功边界的示例；
4. 建立同类软件比较矩阵并执行最小 benchmark：模型组合、相邻层约束、多速率调度、checkpoint replay、source/data identity、报告重建、篡改拒绝、运行时与扩展性；
5. 由仓库作者以外的人完成安装复现，留下 issue/PR 或公开复现记录；
6. 若目标是 JOSS，先累积满足其当前要求的公开开发史和科研使用证据。现在不宜仓促投稿。

**成功门槛：** 不需要证明某个新生物机制，但必须证明软件解决了现有框架没有充分解决的研究工作流问题，并且外部用户能复现。

### 路线 B：扰动预测方法论文（科学增量更高，当前风险较高）

**唯一研究问题示例：** “结构化通路靶标与跨尺度约束，能否改善未见扰动和未见细胞背景下的功能表型预测？”

**最低实验设计：**

1. split 必须覆盖：unseen-gene、组合扰动 0/1/2-seen、unseen-cell-context；
2. 除 MAE 外，采用 perturbation-specific reference、差异表达恢复、方向、排序、下游通路/表型任务等互补指标；
3. 基线至少含 context mean、perturbed mean、additive、ridge，以及与任务匹配的公开模型；
4. 在 Norman、Replogle 之外加入至少一个独立细胞背景或数据源；最终测试集在锁定方法后只查看一次；
5. 以扰动单元或生物样本为统计单位，报告 bootstrap/重复 split 的区间，不把细胞数误当独立重复；
6. 预先定义“比最佳简单基线提高多少才值得继续”，而不是只要求任意正 margin。

**当前 go/no-go：** 先用现有数据完成 component-disjoint benchmark。由于 all-unseen 层当前已不胜质心，如果新方法在这个门槛上仍无稳定优势，就停止扩写方法论文，转回软件论文。这个早停规则能节省最多时间。

### 路线 C：空间 CAR-M 方法/生物论文（成本最高）

**最低条件：**

1. 用与 CAR-M 干预直接相关的共培养、类器官、动物或临床前空间数据校准，而不是只用一般乳腺癌图谱做代理；
2. 把单位、扩散/迁移/吞噬/细胞死亡等过程参数化，并进行 identifiability、敏感性和不确定性分析；
3. 在样本或动物层面划分 calibration/validation，至少保留一个未查看的外部队列；
4. 比较简单 reaction–diffusion、无空间模型及成熟 ABM/QSP 基线；
5. 预测一个可实验检验的结果，例如给定剂量/时序下的空间浸润、肿瘤负荷或联合治疗差异，并由独立实验验证。

没有这些数据前，继续细化 L3/L4 规则会增加代码量，但不会增加可发表的科学证据。

## 6. 90 天最小行动计划

| 时间 | 动作 | 验收条件 | 决策 |
|---|---|---|---|
| 第 1–2 周 | 冻结论文类型与一句话 claim；补许可证、引用、贡献指南；制作 prior-art 对比表 | 所有作者同意“能主张/不能主张”清单 | 不能达成则不投稿 |
| 第 3–4 周 | 建立干净环境复现、外部安装测试、两个主示例、软件 benchmark | 新机器从 clone 到重建报告全绿 | 可启动软件论文草稿 |
| 第 3–6 周（并行） | 对 Norman/Replogle 做 component/context-disjoint benchmark 和强基线 | 在预注册主指标上稳定超过最佳简单基线，并给出区间 | 通过才继续方法路线 |
| 第 7–10 周 | 独立数据集复核；消融只围绕唯一主张 | 主效应在独立数据上方向与量级可重复 | 失败则保留负结果并回到软件路线 |
| 第 11–12 周 | 写预印本/软件论文、归档代码与数据、制作复现说明 | 论文中每个图表可从冻结原始数据重建 | 发布预印本或准备投稿 |

若目标期刊要求六个月以上公开开发史，90 天计划的结果应先作为预印本、技术报告和公开软件版本，同行评审投稿时间顺延。

## 7. 最终判定

### 科研价值

- **高：** 科研软件工程、可追溯性、预注册门禁、失败结果治理、教学与方法原型；
- **中：** 跨尺度模型替换与实验编排的研究基础设施；
- **低到中：** 当前扰动预测方法的外推能力；
- **低：** 当前空间 CAR-M 的真实生物预测与疗效推断。

### 能否发论文

**可以，但必须换主张。** 当前版本适合准备“软件与证据治理”方向的预印本；完成开源治理、同类 benchmark 和外部复现后，有机会成为科研软件论文。计算生物学方法论文需要一轮新的、以严格泛化为中心的实验；生物学发现或 CAR-M 疗效论文目前不能成立。

最稳妥的策略不是继续扩展五层功能，而是把已经做得最好的“证据边界”变成论文的中心贡献，再用一个小而严格的外部验证证明这套机制确实能阻止错误科研主张。

## 8. 证据与方法说明

### 本地核验

- 阅读：`AGENTS.md`、核心原则、架构设计、MVP 计划、README、pyproject、CI、46 份 ADR、数据 registry、关键训练/空间评估 JSON 与训练脚本；
- 独立运行：`python -m unittest discover -s tests -v`，605 项全部通过，用时 211.157 秒；
- 独立运行：`python -m mgba data-check`、`python -m mgba run`、`python -m mgba sten-smoke`；
- 诊断性重分析：按训练扰动成分是否出现，对 Norman holdout 重新分层并重算六节点 MAE；该分析没有预注册，只用于识别发表风险，不作为新的正式科研结论；
- 没有重训神经网络，也没有重新运行高成本完整实验矩阵；现有权重和派生产物通过仓库自带 digest、测试与评估代码核验。

### Sciverse 与联网检索分工

Sciverse 用于从论文语料中检索与定位语义证据，尤其是多尺度模型的标准/benchmark 挑战，以及空间多组学支持的 QSP/ABM 验证范式；联网搜索用于核对 DOI、版本、期刊状态、官方竞赛结果和软件期刊现行要求。Sciverse 结果只作为检索证据，最终关键判断尽量回链到期刊、PubMed/PMC 或官方页面。

Sciverse 主要证据记录：

- Fletcher & Osborne，`doc_id 87833667579eef…`，Challenge 6/7 全文区间约 offset 25,800–32,800；
- Zhang et al. HCC spQSP，`doc_id 968e6d341550ad18…`，语义检索记录与全文证据；
- Sciverse 的覆盖不是完整系统综述，未命中不能证明文献不存在。

## 9. 主要参考来源

1. Fletcher AG, Osborne JM. [Seven challenges in the multiscale modeling of multicellular tissues](https://pmc.ncbi.nlm.nih.gov/articles/PMC11478939/). WIREs Mechanisms of Disease, 2022.
2. Agmon E, et al. [Vivarium: an interface and engine for integrative multiscale modeling in computational biology](https://pubmed.ncbi.nlm.nih.gov/35134830/). Bioinformatics, 2022.
3. Ghaffarizadeh A, et al. [PhysiCell: An open source physics-based cell simulator for 3-D multicellular systems](https://pubmed.ncbi.nlm.nih.gov/29474446/). PLOS Computational Biology, 2018.
4. Letort G, et al. [PhysiBoSS: a multi-scale agent-based modelling framework integrating physical dimension and cell signalling](https://pubmed.ncbi.nlm.nih.gov/30169736/). Bioinformatics, 2019.
5. Ponce-de-Leon M, et al. [PhysiBoSS 2.0](https://pubmed.ncbi.nlm.nih.gov/37903760/). Bioinformatics, 2023.
6. Ahlmann-Eltze C, Huber W, Anders S. [Deep-learning-based gene perturbation effect prediction does not yet outperform simple linear baselines](https://www.nature.com/articles/s41592-025-02772-6.pdf). Nature Methods, 2025.
7. Viñas Torné R, et al. [Systema: a framework for evaluating genetic perturbation response prediction beyond systematic variation](https://www.nature.com/articles/s41587-025-02777-8). Nature Biotechnology, 2025/2026.
8. [Benchmarking algorithms for generalizable single-cell perturbation response prediction](https://www.nature.com/articles/s41592-025-02980-0). Nature Methods, 2025.
9. Arc Institute. [Virtual Cell Challenge 2025 Wrap-Up](https://arcinstitute.org/news/virtual-cell-challenge-2025-wrap-up).
10. Klichinsky M, et al. [Human chimeric antigen receptor macrophages for cancer immunotherapy](https://www.nature.com/articles/s41587-020-0462-y). Nature Biotechnology, 2020.
11. Pierini S, et al. [CAR-M sensitize HER2+ solid tumors to PD1 blockade in pre-clinical models](https://www.nature.com/articles/s41467-024-55770-1). Nature Communications, 2025.
12. Wu SZ, et al. [A single-cell and spatially resolved atlas of human breast cancers](https://www.nature.com/articles/s41588-021-00911-1). Nature Genetics, 2021.
13. Jackson HW, et al. [The single-cell pathology landscape of breast cancer](https://www.nature.com/articles/s41586-019-1876-x). Nature, 2020.
14. Zhang S, et al. [Informing virtual clinical trials of hepatocellular carcinoma with spatial multi-omics analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC10462044/). bioRxiv preprint, 2023.
15. JOSS. [Review criteria](https://joss.readthedocs.io/en/latest/review_criteria.html) and [submission requirements](https://joss.readthedocs.io/en/latest/submitting.html), accessed 2026-09-03.
