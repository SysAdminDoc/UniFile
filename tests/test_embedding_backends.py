from types import SimpleNamespace

import numpy as np

from unifile.embedding_backends import OnnxEmbeddingBackend, _provider_order
from unifile.semantic import SemanticIndex, load_semantic_settings, save_semantic_settings


class _Tokenizer:
    def encode_batch(self, texts):
        return [
            SimpleNamespace(ids=[1, 2, 3][:len(text) or 1], type_ids=[0, 0, 0])
            for text in texts
        ]


class _Session:
    def __init__(self):
        self.inputs = [
            SimpleNamespace(name="input_ids"),
            SimpleNamespace(name="attention_mask"),
            SimpleNamespace(name="token_type_ids"),
        ]
        self.feed = None

    def get_inputs(self):
        return self.inputs

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, _outputs, feed):
        self.feed = feed
        batch = feed["input_ids"].shape[0]
        tokens = feed["input_ids"].shape[1]
        return [np.ones((batch, tokens, 3), dtype=np.float32)]


def test_onnx_backend_batches_and_mean_pools_with_attention_mask():
    session = _Session()
    backend = OnnxEmbeddingBackend(
        "unused",
        session=session,
        tokenizer=_Tokenizer(),
        numpy_module=np,
    )
    vectors = backend.embed(["a", "long"])
    assert len(vectors) == 2
    assert all(len(vector) == 3 for vector in vectors)
    assert all(abs(sum(value * value for value in vector) - 1.0) < 1e-5 for vector in vectors)
    assert session.feed["attention_mask"].shape == (2, 3)


def test_onnx_provider_order_prefers_cuda_then_cpu():
    assert _provider_order(["CPUExecutionProvider", "CUDAExecutionProvider"], "auto") == [
        "CUDAExecutionProvider", "CPUExecutionProvider"
    ]
    assert _provider_order(["CPUExecutionProvider"], "cpu") == ["CPUExecutionProvider"]


def test_semantic_settings_round_trip_and_onnx_unavailable_status(tmp_path, monkeypatch):
    settings_path = tmp_path / "semantic.json"
    assert save_semantic_settings({
        "backend": "onnx",
        "model": "nomic-embed-text",
        "onnx_model_dir": str(tmp_path / "model"),
        "onnx_provider": "cpu",
        "threshold": 0.7,
    }, str(settings_path))
    settings = load_semantic_settings(str(settings_path))
    assert settings["backend"] == "onnx"
    assert settings["onnx_provider"] == "cpu"
    assert settings["threshold"] == 0.7

    monkeypatch.setattr("unifile.semantic._EMBED_DB", str(tmp_path / "semantic.db"))
    index = SemanticIndex(backend="onnx", onnx_model_dir=str(tmp_path / "missing"))
    assert not index.is_available()
    status = index.backend_status()
    assert status["active"] == "onnx"
    assert status["available"] is False
    index.close()


def test_semantic_index_batch_uses_one_backend_batch_and_reports_all_callbacks(tmp_path, monkeypatch):
    monkeypatch.setattr("unifile.semantic._EMBED_DB", str(tmp_path / "semantic.db"))
    index = SemanticIndex(backend="onnx")
    seen = []
    calls = []

    def fake_embeddings(texts):
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    index._get_embeddings = fake_embeddings
    count = index.index_batch([
        {"filepath": str(tmp_path / "one.txt"), "description": "one"},
        {"filepath": str(tmp_path / "two.txt"), "description": "two"},
    ], callback=lambda current, total: seen.append((current, total)))
    assert count == 2
    assert len(calls) == 1 and len(calls[0]) == 2
    assert seen == [(1, 2), (2, 2)]
    assert index.get_indexed_count() == 2
    index.close()
