"""S4 bridge coverage and proxy audit (read-only, pure stdlib).

Audits the frozen MSigDB Hallmark six-node bridge (``mgba-hallmark-six-node-
bridge-0.1``, ADR-0036/0039) against the two empirical perturbation universes
(Norman OE, Replogle KD), audits the ADR-0028 frozen spatial eight-gene proxy
sets against the Wu/Swarbrick Visium S1 source features, and runs a read-only
leave-one-node-out sensitivity recomputation over the frozen ADR-0036/0039
profile six-node vectors.  No frozen file is modified; the bridge definition is
extracted from ``src/mgba/ocellus_anchors.py`` by AST parsing (never copied by
hand), and the bridge digest is recomputed and checked against the digest
recorded in the frozen profiles.

Outputs (under --outdir, default artifacts/audit/bridge-coverage-2026-09-11):
  - audit.json     schema mgba-bridge-coverage-audit-0.1
  - manifest.json  SHA-256 chain for inputs and audit.json

The script is deterministic: no timestamps, no randomness, sorted iteration;
two consecutive runs must produce byte-identical outputs.
"""

from __future__ import annotations

import argparse
import ast
import json
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence

AUDIT_SCHEMA_VERSION = "mgba-bridge-coverage-audit-0.1"
AUDIT_DATE = "2026-09-11"
DEFAULT_OUTDIR = Path("artifacts/audit/bridge-coverage-2026-09-11")

# ---------------------------------------------------------------------------
# Canonical digest primitives (byte-identical semantics to mgba.hashing;
# reimplemented inline so this audit stays a standalone stdlib script).
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def digest_payload(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Frozen bridge extraction (read-only AST parse of the frozen contract module)
# ---------------------------------------------------------------------------


def _literal_assignments(module_path: Path, names: Sequence[str]) -> dict[str, Any]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    found: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target = node.target
            value = node.value
        else:
            continue
        if not isinstance(target, ast.Name) or target.id not in names:
            continue
        try:
            found[target.id] = ast.literal_eval(value)
        except (ValueError, SyntaxError) as error:
            raise ValueError(
                f"{module_path.name}: {target.id} is not a plain literal; audit refuses to guess"
            ) from error
    missing = [name for name in names if name not in found]
    if missing:
        raise ValueError(f"{module_path.name}: could not extract frozen names {missing}")
    return found


def load_frozen_bridge(root: Path) -> dict[str, Any]:
    anchors = _literal_assignments(
        root / "src/mgba/ocellus_anchors.py",
        ("HALLMARK_BRIDGE", "HALLMARK_BRIDGE_STRENGTHS", "HALLMARK_BRIDGE_VERSION"),
    )
    l0 = _literal_assignments(root / "src/mgba/layers/l0.py", ("ABSTRACT_GENE_NAMES",))
    bridge = [(str(node), tuple(str(s) for s in sets)) for node, sets in anchors["HALLMARK_BRIDGE"]]
    node_names = tuple(node for node, _ in bridge)
    if node_names != tuple(l0["ABSTRACT_GENE_NAMES"]):
        raise ValueError("bridge node order disagrees with frozen ABSTRACT_GENE_NAMES")
    digest = digest_payload(
        {
            "version": anchors["HALLMARK_BRIDGE_VERSION"],
            "aggregation": "unweighted-mean-over-deduplicated-hallmark-union-log2fc",
            "nodes": {node: list(sets) for node, sets in bridge},
            "strengths": dict(anchors["HALLMARK_BRIDGE_STRENGTHS"]),
        }
    )
    return {
        "version": anchors["HALLMARK_BRIDGE_VERSION"],
        "digest": digest,
        "aggregation": "unweighted-mean-over-deduplicated-hallmark-union-log2fc",
        "nodes": bridge,
        "strengths": dict(anchors["HALLMARK_BRIDGE_STRENGTHS"]),
    }


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gmt(path: Path, *, expected_sha256: str) -> dict[str, tuple[str, ...]]:
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise ValueError(f"Hallmark GMT SHA-256 mismatch: {actual} != {expected_sha256}")
    memberships: dict[str, tuple[str, ...]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            columns = line.rstrip("\n").split("\t")
            if len(columns) < 3:
                continue
            genes = tuple(sorted({gene for gene in columns[2:] if gene}))
            memberships[columns[0]] = genes
    return memberships


def load_bundle(path: Path, *, expected_dataset: str, expected_units: int) -> dict[str, Any]:
    bundle = read_json(path)
    if bundle.get("schema_version") != "mgba-aivc-empirical-log2fc-0.1":
        raise ValueError(f"{path.name}: unsupported bundle schema")
    if bundle.get("dataset_id") != expected_dataset:
        raise ValueError(f"{path.name}: unexpected dataset_id {bundle.get('dataset_id')}")
    genes = bundle["gene_universe"]["genes"]
    if len(genes) != len(set(genes)):
        raise ValueError(f"{path.name}: universe genes not unique")
    units = bundle["units"]
    if len(units) != expected_units:
        raise ValueError(f"{path.name}: expected {expected_units} units, got {len(units)}")
    return {
        "dataset_id": bundle["dataset_id"],
        "universe_genes": tuple(genes),
        "unit_count": len(units),
        "hallmark_sha256": bundle["hallmark_source"]["sha256"],
        "file_sha256": file_sha256(path),
    }


def load_profile(path: Path, *, node_order: Sequence[str], bridge_digest: str) -> dict[str, Any]:
    profile = read_json(path)
    if profile.get("schema_version") != "mgba-aivc-perturbation-profile-0.1":
        raise ValueError(f"{path.name}: unsupported profile schema")
    if profile["bridge"]["digest"] != bridge_digest:
        raise ValueError(f"{path.name}: bridge digest disagrees with extracted frozen bridge")
    units = []
    for unit in profile["units"]:
        vector = unit["six_node_vector"]
        if tuple(vector.keys()) != tuple(node_order):
            raise ValueError(f"{path.name}: unit {unit['unit']} node order mismatch")
        units.append(
            {
                "unit": unit["unit"],
                "role": unit["role"],
                "vector": tuple(float(vector[node]) for node in node_order),
            }
        )
    return {
        "dataset_id": profile["dataset_id"],
        "profile_id": profile["profile_id"],
        "units": units,
        "file_sha256": file_sha256(path),
    }


def load_spatial_features(derived_dir: Path, *, symbol_column: int) -> dict[str, tuple[str, ...]]:
    samples: dict[str, tuple[str, ...]] = {}
    for sample_dir in sorted(p for p in derived_dir.iterdir() if p.is_dir()):
        features = sample_dir / "features.tsv"
        genes = set()
        with features.open("r", encoding="utf-8") as handle:
            for line in handle:
                columns = line.rstrip("\n").split("\t")
                if len(columns) > symbol_column and columns[symbol_column]:
                    genes.add(columns[symbol_column])
                elif columns and columns[0]:
                    genes.add(columns[0])
        samples[sample_dir.name] = tuple(sorted(genes))
    if not samples:
        raise ValueError(f"no Visium samples under {derived_dir}")
    return samples


# ---------------------------------------------------------------------------
# Audit computations
# ---------------------------------------------------------------------------


def node_unions(
    bridge: Sequence[tuple[str, tuple[str, ...]]],
    memberships: Mapping[str, tuple[str, ...]],
) -> dict[str, set[str]]:
    unions: dict[str, set[str]] = {}
    for node, set_names in bridge:
        union: set[str] = set()
        for set_name in set_names:
            if set_name not in memberships:
                raise ValueError(f"GMT misses frozen bridge set {set_name}")
            union |= set(memberships[set_name])
        unions[node] = union
    return unions


def coverage_table(
    unions: Mapping[str, set[str]], universes: Mapping[str, set[str]]
) -> dict[str, Any]:
    table: dict[str, Any] = {}
    for node in sorted(unions):
        genes = unions[node]
        entry: dict[str, Any] = {"mapped_genes": len(genes)}
        for name in sorted(universes):
            covered = genes & universes[name]
            entry[name] = {
                "covered_genes": len(covered),
                "coverage_rate": len(covered) / len(genes),
            }
        table[node] = entry
    return table


def jaccard_matrix(unions: Mapping[str, set[str]]) -> dict[str, dict[str, float]]:
    nodes = sorted(unions)
    matrix: dict[str, dict[str, float]] = {}
    for left in nodes:
        row: dict[str, float] = {}
        for right in nodes:
            inter = len(unions[left] & unions[right])
            union = len(unions[left] | unions[right])
            row[right] = inter / union if union else 0.0
        matrix[left] = row
    return matrix


def specificity(unions: Mapping[str, set[str]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for genes in unions.values():
        for gene in genes:
            counts[gene] = counts.get(gene, 0) + 1
    result: dict[str, Any] = {}
    for node in sorted(unions):
        genes = unions[node]
        exclusive = sorted(gene for gene in genes if counts[gene] == 1)
        result[node] = {
            "exclusive_genes": len(exclusive),
            "exclusive_ratio": len(exclusive) / len(genes),
            "shared_genes": len(genes) - len(exclusive),
        }
    return result


def universe_gap(unions: Mapping[str, set[str]], universe: set[str]) -> dict[str, Any]:
    all_mapped: set[str] = set().union(*unions.values())
    uncovered = sorted(universe - all_mapped)
    return {
        "universe_genes": len(universe),
        "uncovered_genes": len(uncovered),
        "uncovered_rate": len(uncovered) / len(universe),
        "uncovered_gene_list": uncovered,
    }


def spatial_proxy_audit(
    protocol: Mapping[str, Any],
    samples: Mapping[str, tuple[str, ...]],
    unions: Mapping[str, set[str]],
    memberships: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    symbol_column = int(protocol["feature_symbol_column"])
    channels = protocol["field_channels"]
    min_genes = int(protocol["min_genes_per_channel"])

    # gene -> Hallmark sets (from GMT), then gene -> bridge nodes via node unions
    gene_to_sets: dict[str, list[str]] = {}
    for set_name, genes in memberships.items():
        for gene in genes:
            gene_to_sets.setdefault(gene, []).append(set_name)

    def nodes_of(gene: str) -> list[str]:
        return sorted(node for node, genes in unions.items() if gene in genes)

    result: dict[str, Any] = {"symbol_column": symbol_column, "min_genes_per_channel": min_genes}
    channel_report: dict[str, Any] = {}
    for channel in sorted(channels):
        genes = list(channels[channel])
        per_sample: dict[str, Any] = {}
        for sample in sorted(samples):
            present = set(samples[sample])
            hits = sorted(gene for gene in genes if gene in present)
            per_sample[sample] = {
                "hit_genes": len(hits),
                "total_genes": len(genes),
                "coverage_rate": len(hits) / len(genes),
                "passes_min_genes_gate": len(hits) >= min_genes,
            }
        all_present = set().union(*(set(g) for g in samples.values()))
        gene_rows = []
        for gene in sorted(genes):
            hallmark_sets = sorted(gene_to_sets.get(gene, []))
            gene_rows.append(
                {
                    "gene": gene,
                    "present_in_all_samples": gene in all_present
                    and all(gene in set(samples[s]) for s in samples),
                    "hallmark_sets": hallmark_sets,
                    "bridge_nodes": nodes_of(gene),
                }
            )
        min_hits = min(per_sample[s]["hit_genes"] for s in per_sample)
        channel_report[channel] = {
            "genes": genes,
            "per_sample": per_sample,
            "min_hit_genes_across_samples": min_hits,
            "all_samples_pass_min_genes_gate": min_hits >= min_genes,
            "gene_attribution": gene_rows,
        }
    result["channels"] = channel_report
    return result


def sensitivity_leave_one_node_out(
    profile: Mapping[str, Any], node_order: Sequence[str]
) -> dict[str, Any]:
    """Recompute per-unit vector norms with each node removed (read-only)."""
    per_node: dict[str, list[tuple[float, float, float]]] = {
        node: [] for node in node_order
    }
    norms_full: list[float] = []
    for unit in profile["units"]:
        vector = unit["vector"]
        full_sq = sum(value * value for value in vector)
        full_norm = full_sq**0.5
        norms_full.append(full_norm)
        for index, node in enumerate(node_order):
            reduced_sq = full_sq - vector[index] * vector[index]
            reduced_norm = reduced_sq**0.5
            delta = full_norm - reduced_norm
            relative = delta / full_norm if full_norm > 0.0 else 0.0
            share = (vector[index] * vector[index]) / full_sq if full_sq > 0.0 else 0.0
            per_node[node].append((delta, relative, share))
    nodes_report: dict[str, Any] = {}
    for node in node_order:
        rows = per_node[node]
        nodes_report[node] = {
            "mean_norm_delta": fmean(row[0] for row in rows),
            "max_norm_delta": max(row[0] for row in rows),
            "mean_relative_norm_delta": fmean(row[1] for row in rows),
            "max_relative_norm_delta": max(row[1] for row in rows),
            "mean_squared_norm_share": fmean(row[2] for row in rows),
        }
    return {
        "dataset_id": profile["dataset_id"],
        "profile_id": profile["profile_id"],
        "unit_count": len(profile["units"]),
        "mean_full_norm": fmean(norms_full),
        "rule": (
            "leave-one-node-out on frozen six_node_vector; delta = ||v||2 - "
            "||v_without_node||2 per unit, aggregated by mean/max"
        ),
        "per_node": nodes_report,
    }


def expansion_candidates(
    memberships: Mapping[str, tuple[str, ...]],
    used_sets: set[str],
    universes: Mapping[str, set[str]],
    reference_set: set[str],
) -> list[dict[str, Any]]:
    candidates = []
    for set_name in sorted(memberships):
        if set_name in used_sets:
            continue
        genes = set(memberships[set_name])
        row: dict[str, Any] = {
            "hallmark_set": set_name,
            "gene_count": len(genes),
            "overlap_with_current_negative_feedback_set": len(genes & reference_set),
        }
        for name in sorted(universes):
            row[f"{name}_covered_genes"] = len(genes & universes[name])
        candidates.append(row)
    candidates.sort(
        key=lambda row: (
            -min(row[f"{name}_covered_genes"] for name in sorted(universes)),
            row["hallmark_set"],
        )
    )
    return candidates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_audit(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    input_hashes: dict[str, str] = {}

    bridge = load_frozen_bridge(root)
    for rel in ("src/mgba/ocellus_anchors.py", "src/mgba/layers/l0.py"):
        input_hashes[rel] = file_sha256(root / rel)

    norman_bundle = load_bundle(
        root / "data/aivc/A2-scperturb/norman-empirical-log2fc.json",
        expected_dataset="norman-weissman-2019-scperturb-filtered",
        expected_units=236,
    )
    replogle_bundle = load_bundle(
        root / "data/aivc/B2-replogle2022/replogle-kd-empirical-log2fc.json",
        expected_dataset="replogle-2022-k562-essential-scperturb",
        expected_units=1832,
    )
    gmt_path = root / "data/aivc/A1-msigdb-hallmark/h.all.v2026.1.Hs.symbols.gmt"
    if norman_bundle["hallmark_sha256"] != replogle_bundle["hallmark_sha256"]:
        raise ValueError("bundles disagree on the Hallmark GMT identity")
    memberships = load_gmt(gmt_path, expected_sha256=norman_bundle["hallmark_sha256"])
    input_hashes["data/aivc/A1-msigdb-hallmark/h.all.v2026.1.Hs.symbols.gmt"] = norman_bundle[
        "hallmark_sha256"
    ]
    input_hashes["data/aivc/A2-scperturb/norman-empirical-log2fc.json"] = norman_bundle[
        "file_sha256"
    ]
    input_hashes["data/aivc/B2-replogle2022/replogle-kd-empirical-log2fc.json"] = replogle_bundle[
        "file_sha256"
    ]

    node_order = tuple(node for node, _ in bridge["nodes"])
    universes = {
        "norman": set(norman_bundle["universe_genes"]),
        "replogle_kd": set(replogle_bundle["universe_genes"]),
    }
    unions = node_unions(bridge["nodes"], memberships)

    profiles = {
        "norman": load_profile(
            root / "data/aivc/derived/norman-perturbation-profile.json",
            node_order=node_order,
            bridge_digest=bridge["digest"],
        ),
        "replogle_kd": load_profile(
            root / "data/aivc/derived/replogle-kd-perturbation-profile.json",
            node_order=node_order,
            bridge_digest=bridge["digest"],
        ),
    }
    input_hashes["data/aivc/derived/norman-perturbation-profile.json"] = profiles["norman"][
        "file_sha256"
    ]
    input_hashes["data/aivc/derived/replogle-kd-perturbation-profile.json"] = profiles[
        "replogle_kd"
    ]["file_sha256"]

    protocol_path = root / "configs/experiments/carm_spatial_source_protocol.json"
    protocol = read_json(protocol_path)
    if protocol.get("schema_version") != "mgba-spatial-source-protocol-0.1":
        raise ValueError("unsupported spatial source protocol schema")
    input_hashes["configs/experiments/carm_spatial_source_protocol.json"] = file_sha256(
        protocol_path
    )
    samples = load_spatial_features(
        root / "data/raw/spatial-carm/S1/derived",
        symbol_column=int(protocol["feature_symbol_column"]),
    )
    for sample in sorted(samples):
        input_hashes[f"data/raw/spatial-carm/S1/derived/{sample}/features.tsv"] = file_sha256(
            root / f"data/raw/spatial-carm/S1/derived/{sample}/features.tsv"
        )

    registry = read_json(root / "data/registry.json")
    registry_entries = [
        {
            "dataset_id": entry["dataset_id"],
            "path": entry["path"],
            "sha256": entry["sha256"],
        }
        for entry in registry["datasets"]
        if entry.get("dataset_id")
        in {
            "aivc-norman-perturbation-profile",
            "aivc-replogle-kd-perturbation-profile",
            "carm-spatial-anchor-target",
        }
    ]
    input_hashes["data/registry.json"] = file_sha256(root / "data/registry.json")

    used_sets = {name for _, names in bridge["nodes"] for name in names}
    negative_feedback_union = unions["negative_feedback_expression"]

    audit: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audit_date": AUDIT_DATE,
        "scope": (
            "Read-only audit of the frozen Hallmark six-node bridge coverage over the "
            "Norman OE and Replogle KD universes, ADR-0028 spatial eight-gene proxy "
            "coverage over Wu/Swarbrick Visium S1 features, and leave-one-node-out "
            "sensitivity of the frozen ADR-0036/0039 profile vectors. No frozen "
            "contract, mapping, or data file is modified."
        ),
        "bridge": {
            "version": bridge["version"],
            "digest": bridge["digest"],
            "aggregation": bridge["aggregation"],
            "node_order": list(node_order),
            "node_to_hallmarks": {node: list(names) for node, names in bridge["nodes"]},
            "node_proxy_strength": bridge["strengths"],
        },
        "universes": {
            "norman": {
                "dataset_id": norman_bundle["dataset_id"],
                "universe_genes": len(universes["norman"]),
                "unit_count": norman_bundle["unit_count"],
            },
            "replogle_kd": {
                "dataset_id": replogle_bundle["dataset_id"],
                "universe_genes": len(universes["replogle_kd"]),
                "unit_count": replogle_bundle["unit_count"],
            },
        },
        "node_coverage": coverage_table(unions, universes),
        "node_jaccard_matrix": jaccard_matrix(unions),
        "node_specificity": specificity(unions),
        "universe_gap": {
            "norman": universe_gap(unions, universes["norman"]),
            "replogle_kd": universe_gap(unions, universes["replogle_kd"]),
        },
        "spatial_proxies_adr_0028": spatial_proxy_audit(
            protocol, samples, unions, memberships
        ),
        "sensitivity_leave_one_node_out": {
            name: sensitivity_leave_one_node_out(profiles[name], node_order)
            for name in ("norman", "replogle_kd")
        },
        "negative_feedback_expansion_candidates": expansion_candidates(
            memberships, used_sets, universes, negative_feedback_union
        ),
        "registry_entries": registry_entries,
    }
    audit["audit_id"] = f"bridge-coverage-audit-{digest_payload(audit)[:16]}"
    return audit, input_hashes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="project root (default: parent of this script's directory)",
    )
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    args = parser.parse_args()

    root = args.root.resolve()
    outdir = args.outdir if args.outdir.is_absolute() else root / args.outdir
    audit, input_hashes = build_audit(root)

    outdir.mkdir(parents=True, exist_ok=True)
    audit_bytes = (
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    audit_path = outdir / "audit.json"
    audit_path.write_bytes(audit_bytes)

    manifest = {
        "schema_version": "mgba-bridge-coverage-audit-manifest-0.1",
        "audit_id": audit["audit_id"],
        "outputs": {
            "audit.json": {
                "sha256": sha256(audit_bytes).hexdigest(),
                "bytes": len(audit_bytes),
            }
        },
        "inputs": {
            path: {"sha256": digest} for path, digest in sorted(input_hashes.items())
        },
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"audit_id={audit['audit_id']}")
    print(f"wrote {audit_path}")
    print(f"wrote {outdir / 'manifest.json'}")


if __name__ == "__main__":
    main()
