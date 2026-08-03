"""Optional local image embeddings for semantic duplicate detection.

The backend deliberately accepts an exported ONNX image encoder instead of
pulling a model or importing PyTorch.  CLIP and SigLIP exports that accept
``pixel_values`` and return one vector per image are supported through the
same small adapter.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe
from unifile.embedding_backends import _provider_order

_CLIP_SETTINGS_FILE = os.path.join(_APP_DATA_DIR, "clip_duplicates.json")


class ClipEmbeddingError(RuntimeError):
    """Raised when a local image-embedding backend cannot be initialized."""


def default_clip_model_dir(app_data_dir: str = _APP_DATA_DIR) -> str:
    """Return the default directory for an exported CLIP/SigLIP image graph."""
    return str(Path(app_data_dir) / "models" / "clip")


def load_clip_settings(path: str = _CLIP_SETTINGS_FILE) -> dict[str, Any]:
    """Load semantic-duplicate settings with safe, bounded defaults."""
    raw = load_json_safe(path, {}, expected_type=dict)
    try:
        threshold = float(raw.get("threshold", 0.92))
    except (TypeError, ValueError):
        threshold = 0.92
    try:
        batch_size = int(raw.get("batch_size", 32))
    except (TypeError, ValueError):
        batch_size = 32
    provider = str(raw.get("provider", "auto")).strip().lower()
    if provider not in {"auto", "cpu", "cuda"}:
        provider = "auto"
    return {
        "model_dir": str(raw.get("model_dir", default_clip_model_dir())).strip()
        or default_clip_model_dir(),
        "provider": provider,
        "threshold": min(0.99, max(0.80, threshold)),
        "batch_size": min(256, max(1, batch_size)),
    }


def save_clip_settings(settings: dict[str, Any], path: str = _CLIP_SETTINGS_FILE) -> bool:
    """Persist only known semantic-duplicate settings atomically."""
    current = load_clip_settings(path)
    merged = dict(current)
    merged.update({key: value for key, value in settings.items() if key in current})
    normalized = _normalize_clip_settings(merged)
    return save_json_safe(path, normalized)


def _normalize_clip_settings(raw: dict[str, Any]) -> dict[str, Any]:
    provider = str(raw.get("provider", "auto")).strip().lower()
    if provider not in {"auto", "cpu", "cuda"}:
        provider = "auto"
    try:
        threshold = float(raw.get("threshold", 0.92))
    except (TypeError, ValueError):
        threshold = 0.92
    try:
        batch_size = int(raw.get("batch_size", 32))
    except (TypeError, ValueError):
        batch_size = 32
    return {
        "model_dir": str(raw.get("model_dir", default_clip_model_dir())).strip()
        or default_clip_model_dir(),
        "provider": provider,
        "threshold": min(0.99, max(0.80, threshold)),
        "batch_size": min(256, max(1, batch_size)),
    }


class OnnxClipEmbedder:
    """Batch image embeddings from a local CLIP/SigLIP-style ONNX graph.

    The graph must accept an NCHW float32 ``pixel_values`` tensor and return a
    two-dimensional image embedding output.  ``model.onnx`` or
    ``vision_model.onnx`` is accepted, including under an ``onnx`` child
    directory.  Model files are never downloaded automatically.
    """

    _MEAN = (0.48145466, 0.4578275, 0.40821073)
    _STD = (0.26862954, 0.26130258, 0.27577711)

    def __init__(
        self,
        model_dir: str,
        *,
        provider: str = "auto",
        batch_size: int = 32,
        image_size: int = 224,
        session: Any | None = None,
        numpy_module: Any | None = None,
        image_loader: Any | None = None,
    ):
        self.model_dir = Path(model_dir).expanduser()
        self.provider = provider.strip().lower() or "auto"
        if self.provider not in {"auto", "cpu", "cuda"}:
            raise ValueError("CLIP ONNX provider must be auto, cpu, or cuda")
        self.batch_size = min(256, max(1, int(batch_size)))
        self.image_size = min(1024, max(32, int(image_size)))
        self._session = session
        self._np = numpy_module
        self._image_loader = image_loader
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
        except ClipEmbeddingError as exc:
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

    def embed_paths(self, paths: list[str] | tuple[str, ...]) -> dict[str, list[float]]:
        """Return normalized embeddings for readable image paths.

        Unreadable or unsupported files are skipped so one damaged image does
        not abort a collection scan.
        """
        self._load()
        values = []
        valid_paths = []
        for path in paths:
            try:
                values.append(self._preprocess(path))
                valid_paths.append(str(path))
            except (OSError, ValueError, TypeError):
                continue
        if not values:
            return {}

        result: dict[str, list[float]] = {}
        for offset in range(0, len(values), self.batch_size):
            batch_paths = valid_paths[offset:offset + self.batch_size]
            batch = self._np.asarray(values[offset:offset + self.batch_size], dtype=self._np.float32)
            vectors = self._run_batch(batch)
            for path, vector in zip(batch_paths, vectors, strict=True):
                result[path] = [float(value) for value in vector]
        return result

    def _load(self) -> None:
        if self._session is not None and self._np is not None and self._image_loader is not None:
            return
        try:
            import numpy as np
            import onnxruntime as ort
            from PIL import Image
        except ImportError as exc:
            raise ClipEmbeddingError(
                "Install the optional ONNX extra: pip install -e '.[onnx]'"
            ) from exc

        model_path = _find_clip_model(self.model_dir)
        if not model_path:
            raise ClipEmbeddingError(
                f"CLIP/SigLIP ONNX model not found under {self.model_dir}; "
                "expected model.onnx or vision_model.onnx"
            )
        providers = _provider_order(ort.get_available_providers(), self.provider)
        try:
            self._session = ort.InferenceSession(str(model_path), providers=providers)
        except Exception as exc:
            if self.provider == "auto" and providers != ["CPUExecutionProvider"]:
                try:
                    self._session = ort.InferenceSession(
                        str(model_path), providers=["CPUExecutionProvider"])
                except Exception as cpu_exc:
                    raise ClipEmbeddingError(str(cpu_exc)) from cpu_exc
            else:
                raise ClipEmbeddingError(str(exc)) from exc
        self._np = np
        self._image_loader = Image.open
        session_providers = self._session.get_providers()
        self._provider_name = session_providers[0] if session_providers else "CPUExecutionProvider"

    def _preprocess(self, path: str):
        source = self._image_loader(path)
        converted = None
        resized = None
        try:
            converted = source.convert("RGB")
            resampling = getattr(getattr(converted, "Resampling", None), "BICUBIC", None)
            if resampling is None:
                from PIL import Image
                resampling = Image.Resampling.BICUBIC
            resized = converted.resize((self.image_size, self.image_size), resampling)
            array = self._np.asarray(resized, dtype=self._np.float32) / 255.0
        finally:
            closed = set()
            for image in (resized, converted, source):
                if image is None or id(image) in closed:
                    continue
                close = getattr(image, "close", None)
                if close:
                    close()
                closed.add(id(image))
        array = (array - self._np.asarray(self._MEAN, dtype=self._np.float32)) / self._np.asarray(
            self._STD, dtype=self._np.float32)
        return array.transpose(2, 0, 1)

    def _run_batch(self, batch):
        inputs = self._session.get_inputs()
        if not inputs:
            raise ClipEmbeddingError("CLIP ONNX graph exposes no inputs")
        input_names = {item.name for item in inputs}
        input_name = "pixel_values" if "pixel_values" in input_names else inputs[0].name
        outputs = self._session.run(None, {input_name: batch})
        if not outputs:
            raise ClipEmbeddingError("CLIP ONNX graph returned no embeddings")
        vector_output = next(
            (output for output in outputs
             if getattr(output, "ndim", len(getattr(output, "shape", ()))) == 2),
            outputs[0],
        )
        vectors = self._np.asarray(vector_output, dtype=self._np.float32)
        if vectors.ndim == 3:
            vectors = vectors[:, 0, :]
        if vectors.ndim != 2 or vectors.shape[0] != batch.shape[0]:
            raise ClipEmbeddingError("CLIP ONNX output must be [batch, dim] or [batch, tokens, dim]")
        norms = self._np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / self._np.clip(norms, 1e-12, None)


def _find_clip_model(model_dir: Path) -> Path | None:
    for candidate in (
        model_dir / "vision_model.onnx",
        model_dir / "model.onnx",
        model_dir / "onnx" / "vision_model.onnx",
        model_dir / "onnx" / "model.onnx",
    ):
        if candidate.is_file():
            return candidate
    return None
