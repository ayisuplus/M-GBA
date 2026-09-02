# ADR-0045：实验源码指纹与 Manifest 迁移

- 状态：已接受
- 日期：2026-09-01
- 影响范围：新生成的 `ExperimentManifest`、实验 ID 与 history digest
- 不影响：历史 `mgba-manifest-0.1` artifact、模型数值轨迹、WP8 matrix 身份

## 1. 问题

`ExperimentManifest.code_version` 只有包版本 `0.2.0`。同一版本下的不同提交或脏工作树会得到相同代码标记，无法证明一次实验实际执行了哪组源码字节。

## 2. 决策

- 新 manifest 升级为 `mgba-manifest-0.2`，增加必填的 64 位小写 SHA-256 `source_digest`。
- 指纹覆盖已安装 `mgba` 包目录下全部 `*.py`：先按相对 POSIX 路径排序，再对每个文件字节做 SHA-256，最后对“相对路径 + 文件摘要”列表做规范 JSON SHA-256。
- `source_digest` 参与新实验 ID 与 history digest；配置仍由既有 `config_digest` 独立固定。测试、文档、数据和配置文件不混入源码指纹。
- `mgba-manifest-0.1` 缺少 `source_digest` 时继续按旧字段计算原 ID，报告链保持可读；不追溯改写任何历史 artifact。

## 3. 本次身份迁移

- 源码指纹：`875824b7bfca273b84c5d7423b65c2248c809ef994606da99224d9a7541493ec`
- 单 tick：`mgba-3a179a5a3c399f6d` → `mgba-824e1bade49a7fc3`
- 100 tick：`mgba-06a3c6124501f1d6` → `mgba-98f5aeecf88e3d9e`
- 100 tick history：`4b008f6c…` → `0dff4544…`
- 数值 trace digest 仍为 `20f95784…`，WP8 matrix 仍为 `matrix-7da4137aa39d5122`；变化来自 provenance schema，不是模型轨迹变化。

## 4. 边界

源码指纹证明“运行源码字节是否相同”，不负责归档或获取源码，也不等同 Git commit。复现者仍需保存 wheel、提交或源码快照；具体复核命令见 `docs/复现/实验源码指纹复核.md`。
