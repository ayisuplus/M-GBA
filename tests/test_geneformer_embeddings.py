"""Tests for ADR-0040 embedding extraction (.venv-train; safetensors fixture)."""

from __future__ import annotations

import importlib.util
import json
import pickle
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

SAFETENSORS_AVAILABLE = importlib.util.find_spec("safetensors") is not None

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts" / "geneformer_gene_embeddings.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("geneformer_gene_embeddings", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(SAFETENSORS_AVAILABLE, "safetensors only exists in .venv-train")
class EmbeddingExtractionTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        import numpy as np
        from safetensors.numpy import save_file

        # token ids: 0 <pad>, 1 <mask>, 2 <cls>, 3 ENSG1, 4 ENSG2.
        table = np.arange(20, dtype=np.float64).reshape(5, 4) / 10.0
        model = root / "model.safetensors"
        save_file(
            {"bert.embeddings.word_embeddings.weight": table, "other.weight": table},
            str(model),
        )
        token_dict = root / "token.pkl"
        with token_dict.open("wb") as handle:
            pickle.dump({"<pad>": "0", "<mask>": "1", "<cls>": "2", "ENSG1": "3", "ENSG2": "4"}, handle)
        name_id = root / "nameid.pkl"
        with name_id.open("wb") as handle:
            pickle.dump({"G1": "ENSG0001", "G2": "ENSG2"}, handle)
        # Note: G1 maps to an Ensembl id ABSENT from the token dict -> unmapped.
        profile = root / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "units": [
                        {"unit": "G1"},
                        {"unit": "G2"},
                        {"unit": "G2_G2"},
                        {"unit": "NOPE"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return model, token_dict, name_id, profile

    def test_mapping_chain_and_unmapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, token_dict, name_id, profile = self._fixture(root)
            module = _load_script()
            genes = module.needed_genes([profile])
            self.assertEqual(["G1", "G2", "NOPE"], genes)
            result = module.extract(model, token_dict, name_id, genes)
            self.assertEqual(["G1", "NOPE"], result["unmapped_genes"])
            self.assertEqual(["G2"], sorted(result["embeddings"]))
            # token id 4 -> row 4 of arange(20).reshape(5,4)/10
            self.assertEqual([1.6, 1.7, 1.8, 1.9], result["embeddings"]["G2"])
            self.assertEqual(4, result["embedding_dim"])
            self.assertEqual(_sha256(model), result["source"]["model_sha256"])
            self.assertEqual(_sha256(token_dict), result["source"]["token_dictionary_sha256"])

    def test_deterministic_reextract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, token_dict, name_id, profile = self._fixture(root)
            module = _load_script()
            genes = module.needed_genes([profile])
            first = module.extract(model, token_dict, name_id, genes)
            second = module.extract(model, token_dict, name_id, genes)
            self.assertEqual(first, second)

    def test_missing_tensor_rejected(self) -> None:
        import numpy as np
        from safetensors.numpy import save_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, token_dict, name_id, profile = self._fixture(root)
            bad = root / "bad.safetensors"
            save_file({"other.weight": np.zeros((2, 2))}, str(bad))
            module = _load_script()
            with self.assertRaisesRegex(ValueError, "missing from the model"):
                module.extract(bad, token_dict, name_id, ["G2"])


if __name__ == "__main__":
    unittest.main()
