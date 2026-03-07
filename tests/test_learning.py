"""Tests for the adaptive learning engine."""
import os
import json
import pytest

from unifile.learning import PatternLearner


class TestPatternLearner:

    def test_record_correction_increments(self, tmp_path, monkeypatch):
        db = tmp_path / "learn.json"
        monkeypatch.setattr("unifile.learning._LEARNING_DB", str(db))

        learner = PatternLearner()
        assert learner._total_corrections == 0

        learner.record_correction("invoice.pdf", "/tmp/invoice.pdf", "Finance")
        assert learner._total_corrections == 1
        assert learner._ext_patterns['.pdf']['Finance'] == 1

    def test_predict_returns_none_without_data(self, tmp_path, monkeypatch):
        db = tmp_path / "learn.json"
        monkeypatch.setattr("unifile.learning._LEARNING_DB", str(db))

        learner = PatternLearner()
        result = learner.predict("random.xyz", "/tmp/random.xyz")
        assert result is None

    def test_predict_after_enough_corrections(self, tmp_path, monkeypatch):
        db = tmp_path / "learn.json"
        monkeypatch.setattr("unifile.learning._LEARNING_DB", str(db))

        learner = PatternLearner()
        # Record enough corrections to pass threshold
        for i in range(5):
            learner.record_correction(f"invoice_{i}.pdf", f"/tmp/invoices/invoice_{i}.pdf", "Finance")

        result = learner.predict("invoice_new.pdf", "/tmp/invoices/invoice_new.pdf")
        assert result is not None
        assert result['category'] == 'Finance'
        assert result['confidence'] > 0

    def test_batch_corrections(self, tmp_path, monkeypatch):
        db = tmp_path / "learn.json"
        monkeypatch.setattr("unifile.learning._LEARNING_DB", str(db))

        learner = PatternLearner()
        corrections = [
            {'filename': 'a.psd', 'filepath': '/tmp/a.psd', 'category': 'Design'},
            {'filename': 'b.psd', 'filepath': '/tmp/b.psd', 'category': 'Design'},
        ]
        learner.record_batch_corrections(corrections)
        assert learner._total_corrections == 2
        assert learner._ext_patterns['.psd']['Design'] == 2

    def test_persistence(self, tmp_path, monkeypatch):
        db = tmp_path / "learn.json"
        monkeypatch.setattr("unifile.learning._LEARNING_DB", str(db))

        learner1 = PatternLearner()
        learner1.record_correction("test.py", "/tmp/test.py", "Code")
        assert db.exists()

        # Load again from disk
        learner2 = PatternLearner()
        assert learner2._total_corrections == 1
        assert learner2._ext_patterns['.py']['Code'] == 1

    def test_size_buckets(self):
        assert PatternLearner._size_bucket(500) == "tiny"
        assert PatternLearner._size_bucket(50_000) == "small"
        assert PatternLearner._size_bucket(500_000) == "medium"
        assert PatternLearner._size_bucket(5_000_000) == "large"
        assert PatternLearner._size_bucket(50_000_000) == "xlarge"
        assert PatternLearner._size_bucket(500_000_000) == "huge"
