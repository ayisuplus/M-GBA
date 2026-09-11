# 贡献指南（CONTRIBUTING）

感谢你有兴趣参与 M-GBA。本项目是一个跨尺度数字生命研究原型，证据治理优先于功能堆叠。贡献前请务必通读本指南。

## 1. 先读项目守则

开始任何设计、编码、重构或文档工作前，必须完整阅读：

1. `AGENTS.md`（项目守则，约束所有人类与 AI 协作者）
2. `docs/设计文件/核心原则.md`
3. `docs/设计文件/架构设计.md`
4. `docs/计划文件/MVP计划.md`

任何把项目重新表述为"多智能体平台""LLM Agent 框架"或"动态图通信系统"的变更均属于架构漂移，不会被接受。

## 2. 开发环境

要求 Python ≥ 3.11。核心包零第三方依赖：

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\activate
pip install -e .[dev]
```

## 3. 测试门禁（提交前必须全绿）

与 CI（`.github/workflows/core-ci.yml`）一致的四道门禁：

```bash
python -B -m unittest discover -s tests
python -B -m coverage run -m unittest discover -s tests
python -B -m coverage report --fail-under=80

mgba run --config configs/multiscale_demo.json
mgba sten-smoke --config configs/demo.json
mgba data-check
```

即：单元测试全部通过、`src/mgba` 覆盖率 ≥ 80%、三条 CLI 门禁（multiscale demo / sten smoke / data registry check）全部通过。

## 4. ADR 决策记录流程

重大变更（新层、新数据源、新评估判据、路线变更）必须先写 ADR：

1. 在 `docs/决策记录/` 新建 `ADR-NNNN-标题.md`，编号顺延，写明背景、备选方案、决定与后果。
2. 涉及实验结论的变更必须先预注册判据，再运行实验；按冻结判据判定 passed/failed。
3. ADR 落定后才提交实现代码。

## 5. 红线（不得违反）

- **负面结果原样保留**：failed 评估、No-Go 结论必须按原样登记，不得为展示效果删除、改写或降级。
- **冻结基线与冻结 artifact 不得修改**：已冻结的配置、矩阵、manifest、raw artifact 只读；任何"修复"通过新增版本完成。
- **核心包保持零依赖**：`src/mgba` 只使用 Python 标准库；训练栈只能存在于独立环境与脚本层。
- 不宣称制造真实生命、不具备临床预测能力；文档与代码注释口径保持一致。

## 6. Commit / PR 约定

- Commit message 采用 Conventional Commits 风格（如 `feat:` / `fix:` / `ci:` / `chore:`），重大变更在 message 中引用 ADR 编号。
- 一个 PR 只承载一个逻辑变更；混合无关改动的 PR 会被要求拆分。
- PR 描述须说明：动机、对应 ADR（如有）、门禁运行结果、是否触及冻结内容。
- 不提交凭据、密钥、`.env` 文件或大体积 raw 数据；大文件入 `artifacts/` / `data/raw/`（已 gitignore）。

## 7. AI 辅助开发披露

本项目大部分代码与文档由 AI 助手（Kimi 等）在人类研究者的指令与审阅下生成。所有科学结论均经预注册协议与冻结门禁约束，负面结果原样保留。AI 生成的内容不构成科学结论本身；结论只由冻结判据对实际运行产物的判定给出。贡献者使用 AI 工具无需单独申报，但必须遵守上述同样的证据治理规则。
