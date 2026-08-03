"""Optional local embedding backends.

The ONNX backend is lazy and does not download models.  A model directory
must contain an ONNX graph (``model.onnx`` or ``onnx/model.onnx``) and a
Hugging Face ``tokenizer.json``.  Missing optional packages or model files
are reported as an unavailable backend so callers can fall back to Ollama.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class OnnxBackendError(RuntimeError):
    """Raised when a local ONNX embedding backend cannot be initialized."""


def default_onnx_model_dir(app_data_dir: str) -> str:
    return str(Path(app_data_dir) / "models" / "all-MiniLM-L6-v2")


class OnnxEmbeddingBackend:
    """Batch sentence embeddings from a local ONNX graph and tokenizer."""

    def __init__(
        self,
        model_dir: str,
        *,
        provider: str = "auto",
        max_length: int = 256,
        batch_size: int = 32,
        session: Any | None = None,
        tokenizer: Any | None = None,
        numpy_module: Any | None = None,
    ):
        self.model_dir = Path(model_dir).expanduser()
        self.provider = provider.strip().lower() or "auto"
        if self.provider not in {"auto", "cpu", "cuda"}:
            raise ValueError("ONNX provider must be auto, cpu, or cuda")
        self.max_length = max(1, int(max_length))
        self.batch_size = max(1, int(batch_size))
        self._session = session
        self._tokenizer = tokenizer
        self._np = numpy_module
        self._provider_name = ""
        self._error = ""

    @property
    def error(self) -> str:
        return self._error

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def is_available(self) -> bool:
        try:
            self._load()
        except OnnxBackendError as exc:
            self._error = str(exc)
            return False
        return True

    def status(self) -> dict[str, Any]:
        available = self.is_available()
        return {
            "available": available,
            "model_dir": str(self.model_dir),
            "provider": self._provider_name or self.provider,
            "error": self._error,
        }

    def embed(self, texts: list[str] | tuple[str, ...] | str) -> list[list[float]]:
        self._load()
        values = [texts] if isinstance(texts, str) else list(texts)
        if not values:
            return []
        result = []
        for offset in range(0, len(values), self.batch_size):
            result.extend(self._embed_chunk(values[offset:offset + self.batch_size]))
        return result

    def _load(self):
        if self._session is not None and self._tokenizer is not None and self._np is not None:
            return
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise OnnxBackendError(
                "Install the optional ONNX extra: pip install -e '.[onnx]'"
            ) from exc

        model_path = _find_model(self.model_dir)
        tokenizer_path = self.model_dir / "tokenizer.json"
        if not model_path or not tokenizer_path.is_file():
            raise OnnxBackendError(
                f"ONNX model files not found under {self.model_dir}; "
                "expected model.onnx and tokenizer.json"
            )
        providers = _provider_order(ort.get_available_providers(), self.provider)
        try:
            self._session = ort.InferenceSession(str(model_path), providers=providers)
        except Exception as exc:
            if self.provider == "auto" and "CPUExecutionProvider" in providers and providers != [
                    "CPUExecutionProvider"]:
                try:
                    self._session = ort.InferenceSession(
                        str(model_path), providers=["CPUExecutionProvider"])
                except Exception as cpu_exc:
                    raise OnnxBackendError(str(cpu_exc)) from cpu_exc
            else:
                raise OnnxBackendError(str(exc)) from exc
        try:
            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        except Exception as exc:
            raise OnnxBackendError(f"Could not load tokenizer.json: {exc}") from exc
        self._np = np
        session_providers = self._session.get_providers()
        self._provider_name = session_providers[0] if session_providers else "CPUExecutionProvider"

    def _embed_chunk(self, texts: list[str]) -> list[list[float]]:
        encodings = self._tokenizer.encode_batch([str(text) for text in texts])
        max_tokens = min(
            self.max_length,
            max((len(encoding.ids) for encoding in encodings), default=1),
        )
        input_ids = []
        attention = []
        type_ids = []
        for encoding in encodings:
            ids = list(encoding.ids[:max_tokens])
            mask = [1] * len(ids)
            types = list(getattr(encoding, "type_ids", [])[:max_tokens])
            padding = max_tokens - len(ids)
            ids.extend([0] * padding)
            mask.extend([0] * padding)
            types.extend([0] * (max_tokens - len(types)))
            input_ids.append(ids)
            attention.append(mask)
            type_ids.append(types)

        np = self._np
        available_inputs = {item.name for item in self._session.get_inputs()}
        model_inputs = {}
        if "input_ids" in available_inputs:
            model_inputs["input_ids"] = np.asarray(input_ids, dtype=np.int64)
        if "attention_mask" in available_inputs:
            model_inputs["attention_mask"] = np.asarray(attention, dtype=np.int64)
        if "token_type_ids" in available_inputs:
            model_inputs["token_type_ids"] = np.asarray(type_ids, dtype=np.int64)
        if not model_inputs:
            raise OnnxBackendError("ONNX graph has no supported tokenizer inputs")
        outputs = self._session.run(None, model_inputs)
        if not outputs:
            raise OnnxBackendError("ONNX graph returned no embeddings")
        vectors = outputs[0]
        if len(vectors.shape) == 3:
            mask = np.asarray(attention, dtype=np.float32)[..., None]
            totals = (vectors * mask).sum(axis=1)
            counts = mask.sum(axis=1).clip(min=1.0)
            vectors = totals / counts
        if len(vectors.shape) != 2:
            raise OnnxBackendError("ONNX output must be [batch, dim] or [batch, tokens, dim]")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.clip(norms, 1e-12, None)
        return [[float(value) for value in row] for row in vectors]


def _find_model(model_dir: Path) -> Path | None:
    for candidate in (model_dir / "model.onnx", model_dir / "onnx" / "model.onnx"):
        if candidate.is_file():
            return candidate
    return None


def _provider_order(available: list[str], requested: str) -> list[str]:
    available_set = set(available)
    cpu = "CPUExecutionProvider"
    cuda = "CUDAExecutionProvider"
    if requested == "cpu":
        return [cpu] if cpu in available_set else (list(available) or [cpu])
    if requested == "cuda":
        if cuda not in available_set:
            raise OnnxBackendError("CUDAExecutionProvider is not available")
        return [cuda, cpu] if cpu in available_set else [cuda]
    ordered = [provider for provider in (
        "CUDAExecutionProvider",
        "ROCMExecutionProvider",
        "DmlExecutionProvider",
    ) if provider in available_set]
    if cpu in available_set:
        ordered.append(cpu)
    if ordered:
        return ordered
    return list(available) or [cpu]
