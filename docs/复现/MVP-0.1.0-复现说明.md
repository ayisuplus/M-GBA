# M-GBA 0.1.0 复现说明

## 1. 环境边界

- Python 3.11 或更高版本；
- CPU 即可，不需要 GPU；
- 运行时只依赖 Python 标准库；
- 复现不需要网络、Notebook、数据库或外部服务。

`setuptools>=68` 是构建依赖，不是运行时依赖。Python 3.12 的空 venv 不保证自带 setuptools，因此经验证的离线路径是：在构建环境生成 wheel，再将 wheel 安装到空运行环境。若从正式 release 下载 wheel，可直接跳过构建步骤。

## 2. 构建 wheel

在仓库根目录、已具备 `setuptools>=68` 的构建环境中执行。

Windows PowerShell：

```powershell
$env:PIP_CACHE_DIR = "$PWD\artifacts\pip-cache"
.\.venv\Scripts\python -m pip wheel --no-deps --no-build-isolation --wheel-dir artifacts/release-wheelhouse .
```

Linux / WSL：

```bash
PIP_CACHE_DIR="$PWD/artifacts/pip-cache" .venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir artifacts/release-wheelhouse .
```

预期生成 `artifacts/release-wheelhouse/m_gba-0.1.0-py3-none-any.whl`。正式 release wheel 的 SHA-256 记录在 [M-GBA 0.1.0 发布清单](../发布/MVP-0.1.0-发布清单.md)，以避免构建说明与发布身份重复维护。

## 3. 新虚拟环境安装

Windows PowerShell：

```powershell
python -m venv .venv-repro
.\.venv-repro\Scripts\python -m pip install --no-deps --no-cache-dir artifacts/release-wheelhouse/m_gba-0.1.0-py3-none-any.whl
.\.venv-repro\Scripts\python -c "import mgba; print(mgba.__version__)"
```

Linux / WSL：

```bash
python -m venv .venv-repro
.venv-repro/bin/python -m pip install --no-deps --no-cache-dir artifacts/release-wheelhouse/m_gba-0.1.0-py3-none-any.whl
.venv-repro/bin/python -c "import mgba; print(mgba.__version__)"
```

预期版本为 `0.1.0`。

## 4. 自动化验收

Windows PowerShell：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv-repro\Scripts\python -B -m unittest discover -s tests -v
.\.venv-repro\Scripts\python -B scripts/mvp_demo.py --mode full --artifact-root artifacts/reproduction
```

Linux / WSL：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv-repro/bin/python -B -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 .venv-repro/bin/python -B scripts/mvp_demo.py --mode full --artifact-root artifacts/reproduction
```

full demo 必须报告：

| 字段 | 冻结值 |
|---|---|
| `single_tick_experiment_id` | `mgba-023f543fb5a130ab` |
| `multirate_experiment_id` | `mgba-66654d1710f94556` |
| `history_digest` | `7edbf3b897983ae4d24e1537bcc6b6d8850f3933adfeb6cc78b215c56d1350dc` |
| `outcome` | `failed` |
| `matrix_id` | `matrix-7da4137aa39d5122` |
| `matrix_run_count` | `21` |
| `report_file_count` | `10` |

任一值不同时，演示脚本会以非零状态退出，不会将漂移的结果当作通过。

## 5. 手工分步复现

如果需要逐步检查，Windows 控制台命令为：

```powershell
.\.venv-repro\Scripts\mgba run --config configs/multiscale_demo.json
.\.venv-repro\Scripts\mgba simulate --ticks 100
.\.venv-repro\Scripts\mgba experiment --artifact-root artifacts/manual-reproduction
.\.venv-repro\Scripts\mgba report --matrix-root artifacts/manual-reproduction/matrix-7da4137aa39d5122
.\.venv-repro\Scripts\mgba sten-smoke --config configs/demo.json
```

Linux / WSL 将可执行文件替换为 `.venv-repro/bin/mgba`。

### Checkpoint 等价性

```powershell
.\.venv-repro\Scripts\mgba simulate --ticks 13 --checkpoint-out artifacts/checkpoint-13.json
.\.venv-repro\Scripts\mgba simulate --ticks 87 --checkpoint-in artifacts/checkpoint-13.json --trace-out artifacts/resumed-100.json
```

恢复运行的历史摘要应与一次 100 tick 运行相同。

## 6. 报告文件校验

报告默认位于：

```text
artifacts/reproduction/matrix-7da4137aa39d5122/derived/report/
```

其中 `report-manifest.json` 记录 5 份 CSV、4 张 SVG 和 `report.html` 的 SHA-256。直接删除 `derived/report/` 不会损失原始证据；重新执行 `mgba report` 应产生字节相同的报告。

不要手工修改 `raw/` 下的 JSON。报告器会验证实验身份、tick、历史哈希链和 checkpoint ID；损坏 raw 应导致重建失败。

## 7. 降级演示

当演示环境不适合写入约 10 MB 的矩阵 artifact 时，可以执行：

```powershell
.\.venv-repro\Scripts\python scripts/mvp_demo.py --mode fallback
```

fallback 只验证单 tick 契约、30 tick 多速率 Runner 和独立 STEN smoke。它不运行 21-run 矩阵，不生成 WP9 报告，因此不能代替 full demo 的研究追溯证据。

## 8. 常见问题

- 命令找不到配置：确认当前目录是仓库根目录。
- 空 venv 中没有 setuptools：不要在运行环境构建源码；安装构建环境产生的 wheel。
- 已有 artifact 与新运行冲突：选择新的 `--artifact-root`，不要覆盖原始记录。
- 三个 seed 数值相同：这是 0.1.0 确定性模型的已知边界，不是统计显著性证据。
