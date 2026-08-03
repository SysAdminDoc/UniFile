"""Semantic duplicate detection tests with dependency-free fake embeddings."""
from __future__ import annotations

import math


class _FakeEmbedder:
    def __init__(self, embeddings):
        self.embeddings = embeddings

    def is_available(self):
        return True

    def embed_paths(self, paths):
        return {path: self.embeddings[path] for path in paths if path in self.embeddings}


def test_semantic_detector_clusters_transitive_matches_and_keeps_largest(tmp_path):
    from unifile.duplicates import ProgressiveDuplicateDetector

    paths = [tmp_path / name for name in ("small.jpg", "medium.jpg", "large.jpg", "unique.jpg")]
    paths[0].write_bytes(b"a" * 10)
    paths[1].write_bytes(b"b" * 20)
    paths[2].write_bytes(b"c" * 30)
    paths[3].write_bytes(b"d" * 40)
    a, b, c, unique = (str(path) for path in paths)
    angle = math.radians(20)
    embeddings = {
        a: [1.0, 0.0],
        b: [math.cos(angle), math.sin(angle)],
        c: [math.cos(angle * 2), math.sin(angle * 2)],
        unique: [0.0, 1.0],
    }
    detector = ProgressiveDuplicateDetector(
        enable_perceptual=False,
        enable_audio=False,
        enable_semantic=True,
        semantic_threshold=0.92,
        semantic_embedder=_FakeEmbedder(embeddings),
    )

    result = detector.detect([(str(path), path.stat().st_size) for path in paths])

    assert {a, b, c} <= set(result)
    assert unique not in result
    assert {result[a].group_id, result[b].group_id, result[c].group_id} == {result[a].group_id}
    assert result[c].is_original is True
    assert result[a].is_original is False
    assert result[a].is_semantic is True
    assert "semantic" in result[a].detail


def test_semantic_stage_does_not_replace_exact_duplicate_groups(tmp_path):
    from unifile.duplicates import ProgressiveDuplicateDetector

    exact_a = tmp_path / "exact-a.jpg"
    exact_b = tmp_path / "exact-b.jpg"
    other = tmp_path / "other.jpg"
    other_copy = tmp_path / "other-copy.jpg"
    exact_a.write_bytes(b"same" * 30)
    exact_b.write_bytes(b"same" * 30)
    other.write_bytes(b"other" * 31)
    other_copy.write_bytes(b"different size" * 5)
    paths = [str(exact_a), str(exact_b), str(other), str(other_copy)]
    embedder = _FakeEmbedder({path: [1.0, 0.0] for path in paths})
    detector = ProgressiveDuplicateDetector(
        enable_perceptual=False,
        enable_audio=False,
        enable_semantic=True,
        semantic_embedder=embedder,
    )

    result = detector.detect([(path, (tmp_path / path.split("\\")[-1]).stat().st_size) for path in paths])

    assert str(exact_a) in result and str(exact_b) in result
    assert result[str(exact_a)].is_semantic is False
    assert str(other) in result
    assert str(other_copy) in result
    assert result[str(other)].is_semantic is True
    assert result[str(exact_a)].group_id != result[str(other)].group_id


def test_cluster_semantic_embeddings_uses_cosine_threshold():
    from unifile.duplicates import cluster_semantic_embeddings

    groups = cluster_semantic_embeddings({
        "a": [1.0, 0.0],
        "b": [0.0, 1.0],
        "c": [0.99, 0.1],
    }, threshold=0.92)

    assert len(groups) == 1
    assert set(groups[0][0]) == {"a", "c"}
    assert groups[0][1] > 0.92


def test_onnx_clip_embedder_batches_and_normalizes_images(tmp_path):
    np = __import__("numpy")
    Image = __import__("PIL.Image", fromlist=["Image"])
    from unifile.clip_duplicates import OnnxClipEmbedder

    class FakeSession:
        def __init__(self):
            self.calls = []

        def get_inputs(self):
            return [type("Input", (), {"name": "pixel_values"})()]

        def get_providers(self):
            return ["CPUExecutionProvider"]

        def run(self, _outputs, inputs):
            batch = next(iter(inputs.values()))
            self.calls.append(batch.shape[0])
            return [batch.mean(axis=(2, 3))]

    paths = [tmp_path / "one.jpg", tmp_path / "two.jpg", tmp_path / "three.jpg"]
    for path, color in zip(paths, ((255, 0, 0), (0, 255, 0), (0, 0, 255)), strict=True):
        Image.new("RGB", (12, 12), color).save(path)
    session = FakeSession()
    embedder = OnnxClipEmbedder(
        str(tmp_path), session=session, numpy_module=np, image_loader=Image.open,
        batch_size=2, image_size=16,
    )

    result = embedder.embed_paths([str(path) for path in paths])

    assert set(result) == {str(path) for path in paths}
    assert session.calls == [2, 1]
    assert all(abs(math.sqrt(sum(value * value for value in vector)) - 1.0) < 1e-6
               for vector in result.values())
