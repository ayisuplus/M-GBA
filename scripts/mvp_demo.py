from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SINGLE_TICK_ID = "mgba-85a4d85a8d78fa83"
REFERENCE_MULTIRATE_ID = "mgba-c4801af10685fcb7"
REFERENCE_HISTORY_DIGEST = (
    "5715209a09cc63b6495c0a4212467dac6fa662c9d03a885d1cd20df3e08325f2"
)
REFERENCE_MATRIX_ID = "matrix-7da4137aa39d5122"


def _invoke(*arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        (sys.executable, "-m", "mgba.cli", *arguments),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise RuntimeError(f"mgba {' '.join(arguments)} did not return a JSON object")
    return result


def _require(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} changed: expected {expected!r}, got {actual!r}")


def run_full(artifact_root: Path) -> dict[str, Any]:
    single_tick = _invoke("run")
    _require(
        single_tick["experiment"]["experiment_id"],
        REFERENCE_SINGLE_TICK_ID,
        "single-tick experiment ID",
    )

    multirate = _invoke("simulate", "--ticks", "100")
    _require(
        multirate["experiment"]["experiment_id"],
        REFERENCE_MULTIRATE_ID,
        "multirate experiment ID",
    )
    _require(
        multirate["history_digest"],
        REFERENCE_HISTORY_DIGEST,
        "100-tick history digest",
    )
    _require(multirate["phenotype_window"]["outcome"], "failed", "outcome")

    matrix = _invoke(
        "experiment", "--artifact-root", str(artifact_root.resolve())
    )
    _require(matrix["matrix_id"], REFERENCE_MATRIX_ID, "causal matrix ID")
    _require(matrix["run_count"], 21, "causal matrix run count")
    _require(matrix["comparison_count"], 18, "paired comparison count")

    report = _invoke("report", "--matrix-root", matrix["artifact_root"])
    _require(report["matrix_id"], REFERENCE_MATRIX_ID, "report matrix ID")
    _require(len(report["files"]), 10, "report file count")

    return {
        "mode": "full",
        "single_tick_experiment_id": REFERENCE_SINGLE_TICK_ID,
        "multirate_experiment_id": REFERENCE_MULTIRATE_ID,
        "history_digest": REFERENCE_HISTORY_DIGEST,
        "outcome": "failed",
        "matrix_id": REFERENCE_MATRIX_ID,
        "matrix_run_count": matrix["run_count"],
        "report_file_count": len(report["files"]),
        "artifact_root": matrix["artifact_root"],
        "report_root": report["report_root"],
    }


def run_fallback() -> dict[str, Any]:
    single_tick = _invoke("run")
    _require(
        single_tick["experiment"]["experiment_id"],
        REFERENCE_SINGLE_TICK_ID,
        "single-tick experiment ID",
    )
    multirate = _invoke("simulate", "--ticks", "30")
    sten = _invoke("sten-smoke", "--config", "configs/demo.json")
    return {
        "mode": "fallback",
        "scope": "contract, 30-tick runner, and independent STEN smoke only",
        "single_tick_experiment_id": REFERENCE_SINGLE_TICK_ID,
        "multirate_experiment_id": multirate["experiment"]["experiment_id"],
        "history_digest": multirate["history_digest"],
        "outcome": multirate["phenotype_window"]["outcome"],
        "sten_event_digest": sten["event_digest"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen M-GBA MVP demonstration"
    )
    parser.add_argument(
        "--mode",
        choices=("full", "fallback"),
        default="full",
        help="full reproduces WP8/WP9; fallback avoids the batch artifact step",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts/mvp-demo"),
        help="directory for full-mode matrix and report artifacts",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_full(args.artifact_root) if args.mode == "full" else run_fallback()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
