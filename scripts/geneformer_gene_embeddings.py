#!/usr/bin/env python
"""ADR-0040: extract Geneformer input token embeddings for perturbed genes.

Runs ONLY in the independent training venv (``.venv-train``). Pure table
extraction — the model never runs a forward pass. Mapping chain (frozen):
gene symbol -> gene_name_id_dict -> Ensembl -> token_dictionary -> token id ->
``bert.embeddings.word_embeddings.weight`` row (768-d). Genes missing at any
step are recorded as unmapped; no imputation.

Output: ``mgba-gene-embedding-table-0.1`` JSON with full source provenance.
"""

from __future__ import annotations

import argparse
import json
import pickle
from hashlib import sha256
from pathlib import Path

import numpy as np
from safetensors.numpy import load_file

EMBEDDING_TABLE_SCHEMA = "mgba-gene-embedding-table-0.1"
EMBEDDING_TENSOR = "bert.embeddings.word_embeddings.weight"


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_pickle(path: Path) -> dict:
    with path.open("rb") as handle:
        result = pickle.load(handle)
    if not isinstance(result, dict):
        raise ValueError(f"expected a dict in {path.name}")
    return result


def needed_genes(profile_paths: list[Path]) -> list[str]:
    genes: set[str] = set()
    for path in profile_paths:
        profile = json.loads(path.read_text(encoding="utf-8"))
        for unit in profile["units"]:
            genes.update(part for part in unit["unit"].split("_") if part)
    if not genes:
        raise ValueError("no genes collected from profiles")
    return sorted(genes)


def extract(model_path: Path, token_dict_path: Path, name_id_path: Path, genes: list[str]) -> dict:
    name_id = _load_pickle(name_id_path)
    token_dict = _load_pickle(token_dict_path)
    table = load_file(str(model_path))
    if EMBEDDING_TENSOR not in table:
        raise ValueError(f"{EMBEDDING_TENSOR} missing from the model file")
    embeddings = np.asarray(table[EMBEDDING_TENSOR], dtype=np.float64)
    vocab_size, dim = embeddings.shape

    resolved: dict[str, list[float]] = {}
    unmapped: list[str] = []
    for gene in genes:
        ensembl = name_id.get(gene)
        token = token_dict.get(ensembl) if ensembl is not None else None
        if token is None:
            unmapped.append(gene)
            continue
        token_id = int(token)
        if not 0 <= token_id < vocab_size:
            unmapped.append(gene)
            continue
        resolved[gene] = [float(value) for value in embeddings[token_id]]

    if not resolved:
        raise ValueError("no gene resolved to an embedding row")
    return {
        "schema_version": EMBEDDING_TABLE_SCHEMA,
        "source": {
            "model_path": model_path.name,
            "model_sha256": _sha256_file(model_path),
            "model_id": "Geneformer-V2-104M_CLcancer",
            "token_dictionary": token_dict_path.name,
            "token_dictionary_sha256": _sha256_file(token_dict_path),
            "gene_name_id_dictionary": name_id_path.name,
            "gene_name_id_dictionary_sha256": _sha256_file(name_id_path),
            "tensor": EMBEDDING_TENSOR,
            "layer_note": "input token embeddings only; no forward pass",
        },
        "embedding_dim": dim,
        "embeddings": {gene: resolved[gene] for gene in sorted(resolved)},
        "unmapped_genes": unmapped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Geneformer model.safetensors")
    parser.add_argument("--token-dict", required=True, help="token_dictionary_gc104M.pkl")
    parser.add_argument("--name-id-dict", required=True, help="gene_name_id_dict_gc104M.pkl")
    parser.add_argument(
        "--profile",
        required=True,
        nargs="+",
        help="perturbation profile JSON(s) whose units define the needed genes",
    )
    parser.add_argument("--output", required=True, help="embedding table JSON output")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing table: {output}")
    genes = needed_genes([Path(p) for p in args.profile])
    result = extract(
        Path(args.model), Path(args.token_dict), Path(args.name_id_dict), genes
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "embedding_dim": result["embedding_dim"],
                "resolved_genes": len(result["embeddings"]),
                "unmapped_genes": len(result["unmapped_genes"]),
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
