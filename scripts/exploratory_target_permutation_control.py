#!/usr/bin/env python
"""ADR-0048 control 3 (target-permutation): spatial-anchor evaluator vs a
deterministically permuted target.

Pure standard library; runs in ``.venv``. Does NOT re-run the simulator: the
frozen 39-metric model projection is extracted verbatim from the existing
evaluation artifact ``carm-spatial-anchor-eval-e4557bd18b08ebff`` and scored
against a permuted target with the exact ``score_spatial_projection`` NAE
semantics (scale = max(q75-q25, std, 0.05*max(|median|,1), 1e-9);
NAE = |model - median| / scale).

Frozen permutation derivation (ADR-0048 section 3.3): the 39 distribution
slots keep (role, metric_id, sample_count) in place; the statistic 7-tuples
(minimum, q25, median, q75, maximum, mean, standard_deviation) are permuted
across slots by sigma = argsort of
sha256("mgba-adr-0048-target-permutation-v1|<target_sha256>|<role>|<metric_id>").

Anchor: scoring the REAL target with this implementation must reproduce the
frozen role means (10.347825516541054 / 12.146142329407688 /
1.3273749445952074) and all 39 per-metric NAEs within 1e-12 before any
criterion is evaluated.

Pre-registered criterion: the permuted target's three role mean NAEs and the
overall 39-metric mean must ALL be strictly worse (larger) than the real
target's; any role that is not worse is recorded as a discrimination gap.
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

SCHEMA_VERSION = "mgba-falsification-control-0.1"
CONTROL_ID = "target-permutation"
TARGET_PATH = Path("data/spatial-carm/derived/carm-spatial-anchor-target.json")
EVALUATION_PATH = Path(
    "artifacts/carm-spatial-anchor/carm-spatial-anchor-eval-e4557bd18b08ebff"
    "/derived/summary.json"
)
PERMUTATION_SALT = "mgba-adr-0048-target-permutation-v1"
EPSILON = 1e-12
ROLES = ("calibration", "holdout", "external_validation")
STAT_FIELDS = (
    "minimum",
    "q25",
    "median",
    "q75",
    "maximum",
    "mean",
    "standard_deviation",
)

SCIENTIFIC_BOUNDARY = (
    "阴性对照：检验评估管线在无信号输入下是否假阳性；不构成对任何生物主张的"
    "支持或否定，不撤销历史 verdict，仅标定其证据等级"
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nae(model_value: float, distribution: dict) -> float:
    median = distribution["median"]
    scale = max(
        distribution["q75"] - distribution["q25"],
        distribution["standard_deviation"],
        0.05 * max(abs(median), 1.0),
        1e-9,
    )
    return abs(model_value - median) / scale


def _score(model_metrics: dict[str, float], distributions: list[dict]) -> dict:
    comparisons = []
    for distribution in distributions:
        metric_id = distribution["metric_id"]
        comparisons.append(
            {
                "role": distribution["role"],
                "metric_id": metric_id,
                "model_value": model_metrics[metric_id],
                "target_median": distribution["median"],
                "normalized_absolute_error": _nae(model_metrics[metric_id], distribution),
            }
        )
    role_scores = {}
    for role in ROLES:
        group = [c for c in comparisons if c["role"] == role]
        role_scores[role] = {
            "metric_count": len(group),
            "mean_normalized_absolute_error": sum(
                c["normalized_absolute_error"] for c in group
            )
            / len(group),
        }
    overall = sum(c["normalized_absolute_error"] for c in comparisons) / len(comparisons)
    return {"comparisons": comparisons, "role_scores": role_scores, "overall_mean": overall}


def _permute(distributions: list[dict], target_sha256: str, salt: str) -> tuple[list[dict], list[int]]:
    keys = [
        sha256(
            f"{salt}|{target_sha256}|{d['role']}|{d['metric_id']}".encode("utf-8")
        ).hexdigest()
        for d in distributions
    ]
    sigma = sorted(range(len(distributions)), key=lambda i: keys[i])
    tuples = [tuple(d[field] for field in STAT_FIELDS) for d in distributions]
    permuted = []
    for i, distribution in enumerate(distributions):
        source = tuples[sigma[i]]
        entry = {
            "role": distribution["role"],
            "metric_id": distribution["metric_id"],
            "sample_count": distribution["sample_count"],
        }
        entry.update(dict(zip(STAT_FIELDS, source)))
        permuted.append(entry)
    return permuted, sigma


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    target_sha256 = _sha256_file(TARGET_PATH)
    evaluation_sha256 = _sha256_file(EVALUATION_PATH)
    target = json.loads(TARGET_PATH.read_text(encoding="utf-8"))
    evaluation = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))
    if target["schema_version"] != "mgba-spatial-anchor-target-0.1":
        raise ValueError("unexpected target schema")
    model_metrics = dict(evaluation["score"]["projection"]["metrics"])
    distributions = target["distributions"]
    if len(distributions) != 39:
        raise ValueError("target must carry exactly 39 distribution slots")

    # Anchor: reproduce the frozen real-target scores within 1e-12.
    real_score = _score(model_metrics, distributions)
    frozen_role_means = {
        item["role"]: item["mean_normalized_absolute_error"]
        for item in evaluation["score"]["role_scores"]
    }
    anchor_role_diffs = {
        role: abs(real_score["role_scores"][role]["mean_normalized_absolute_error"] - frozen_role_means[role])
        for role in ROLES
    }
    frozen_comparisons = {
        (item["role"], item["metric_id"]): item["normalized_absolute_error"]
        for item in evaluation["score"]["comparisons"]
    }
    anchor_metric_max_diff = max(
        abs(c["normalized_absolute_error"] - frozen_comparisons[(c["role"], c["metric_id"])])
        for c in real_score["comparisons"]
    )
    anchor_ok = (
        max(anchor_role_diffs.values()) <= EPSILON and anchor_metric_max_diff <= EPSILON
    )

    # Permuted target (retry salt only on an identity permutation, per ADR).
    salt = PERMUTATION_SALT
    permuted, sigma = _permute(distributions, target_sha256, salt)
    retries = 0
    while sigma == list(range(len(distributions))):
        retries += 1
        salt = f"{PERMUTATION_SALT}|retry-{retries}"
        permuted, sigma = _permute(distributions, target_sha256, salt)
    permuted_score = _score(model_metrics, permuted)

    real_means = {
        role: real_score["role_scores"][role]["mean_normalized_absolute_error"]
        for role in ROLES
    }
    permuted_means = {
        role: permuted_score["role_scores"][role]["mean_normalized_absolute_error"]
        for role in ROLES
    }
    role_worse = {role: permuted_means[role] > real_means[role] for role in ROLES}
    overall_worse = permuted_score["overall_mean"] > real_score["overall_mean"]
    criteria_met = all(role_worse.values()) and overall_worse

    real_by_key = {
        (c["role"], c["metric_id"]): c["normalized_absolute_error"]
        for c in real_score["comparisons"]
    }
    per_metric = [
        {
            "role": c["role"],
            "metric_id": c["metric_id"],
            "real_nae": real_by_key[(c["role"], c["metric_id"])],
            "permuted_nae": c["normalized_absolute_error"],
            "permuted_worse": c["normalized_absolute_error"]
            > real_by_key[(c["role"], c["metric_id"])],
        }
        for c in permuted_score["comparisons"]
    ]
    worse_count = sum(1 for item in per_metric if item["permuted_worse"])

    results_payload = {
        "schema_version": SCHEMA_VERSION,
        "control_id": CONTROL_ID,
        "adr": "ADR-0048",
        "created_date": "2026-09-11",
        "status": "completed",
        "inputs": [
            {
                "path": str(TARGET_PATH).replace("\\", "/"),
                "sha256": target_sha256,
                "role": "frozen carm-spatial-anchor-target (spatial-anchor-29c87ba1411d4fc8)",
            },
            {
                "path": str(EVALUATION_PATH).replace("\\", "/"),
                "sha256": evaluation_sha256,
                "role": "frozen evaluation summary supplying the verbatim model projection",
            },
        ],
        "derivation": {
            "rule": (
                "39 个分布槽保持 (role, metric_id, sample_count) 原位；统计七元组 "
                "(minimum, q25, median, q75, maximum, mean, standard_deviation) 跨槽置换："
                "sigma = argsort(sha256('mgba-adr-0048-target-permutation-v1|<target_sha256>"
                "|<role>|<metric_id>'))；置换后槽 i 的七元组 = 原第 sigma(i) 槽"
            ),
            "salt": salt,
            "retry_count": retries,
            "permutation_first8": sigma[:8],
            "model_projection_source": "score.projection.metrics of the frozen evaluation (no re-simulation)",
        },
        "criteria": {
            "text": (
                "置换 target 的三 role NAE 均值与 39 指标总均值必须全部严格差于真实 target："
                "calibration > 10.347825516541054，holdout > 12.146142329407688，"
                "external_validation > 1.3273749445952074，总均值同理；任一 role 不差即记 "
                "criteria_not_met 并如实登记区分度缺口"
            ),
            "anchor": "同一实现重算真实 target 必须复现三 role 均值与 39 条 NAE（≤1e-12）后才计算判据",
        },
        "anchors": {
            "role_mean_abs_diffs": anchor_role_diffs,
            "per_metric_max_abs_diff": anchor_metric_max_diff,
            "anchor_ok": anchor_ok,
        },
        "results": {
            "real_role_mean_nae": real_means,
            "real_overall_mean_nae": real_score["overall_mean"],
            "permuted_role_mean_nae": permuted_means,
            "permuted_overall_mean_nae": permuted_score["overall_mean"],
            "role_worse": role_worse,
            "overall_worse": overall_worse,
            "per_metric_worse_count": worse_count,
            "per_metric_total": len(per_metric),
            "per_metric": per_metric,
        },
        "verdict": "criteria_met" if (anchor_ok and criteria_met) else "criteria_not_met",
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.json"
    if results_path.exists():
        raise SystemExit(f"refusing to overwrite existing results: {results_path}")
    results_path.write_text(
        json.dumps(results_payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    script_path = Path(__file__).resolve()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "control_id": CONTROL_ID,
        "kind": "manifest",
        "entries": [
            {
                "path": "results.json",
                "sha256": _sha256_file(results_path),
                "bytes": results_path.stat().st_size,
            },
            {
                "path": f"scripts/{script_path.name}",
                "sha256": _sha256_file(script_path),
                "bytes": script_path.stat().st_size,
            },
        ],
        "determinism": None,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "control_id": CONTROL_ID,
                "verdict": results_payload["verdict"],
                "anchor_ok": anchor_ok,
                "real_role_mean_nae": real_means,
                "permuted_role_mean_nae": permuted_means,
                "real_overall": real_score["overall_mean"],
                "permuted_overall": permuted_score["overall_mean"],
                "per_metric_worse": f"{worse_count}/{len(per_metric)}",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
