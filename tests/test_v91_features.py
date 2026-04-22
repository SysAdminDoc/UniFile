"""Tests for v9.1.0 additions: CLI subcommand, Ollama batch chunking,
connection registry, and scan-plan JSON writer."""
import json
import os
import sqlite3
from pathlib import Path

import pytest


# ── Connection registry (atexit cleanup) ──────────────────────────────────────

def test_register_sqlite_connection_is_idempotent(tmp_path):
    from unifile.config import register_sqlite_connection, _sqlite_registry
    conn = sqlite3.connect(str(tmp_path / 't.db'))
    before = len(_sqlite_registry)
    register_sqlite_connection(conn)
    register_sqlite_connection(conn)  # idempotent
    assert len(_sqlite_registry) <= before + 1
    conn.close()


def test_close_all_sqlite_connections_is_best_effort():
    """Closing an already-closed connection should not propagate."""
    from unifile.config import register_sqlite_connection, _close_all_sqlite_connections
    conn = sqlite3.connect(":memory:")
    register_sqlite_connection(conn)
    conn.close()
    # Should not raise on already-closed connection
    _close_all_sqlite_connections()


# ── Ollama batch chunking ─────────────────────────────────────────────────────

def test_ollama_batch_chunk_limit_is_respected(monkeypatch):
    """When folders exceed the chunk limit, the batch function dispatches
    to the per-chunk helper multiple times."""
    from unifile import ollama as _ol

    calls: list[int] = []

    def fake_chunk(folders, **kw):
        calls.append(len(folders))
        return [{'name': None, 'category': 'Documents', 'confidence': 80,
                 'method': 'llm_batch', 'detail': 'mock'} for _ in folders]

    monkeypatch.setattr(_ol, '_ollama_classify_batch_chunk', fake_chunk)
    folders = [{'folder_name': f'f{i}', 'folder_path': '', 'context': ''}
               for i in range(60)]
    result = _ol.ollama_classify_batch(folders, chunk_limit=25)
    # 60 folders / 25 = 3 chunks: 25, 25, 10
    assert calls == [25, 25, 10]
    assert len(result) == 60


def test_ollama_batch_chunk_error_doesnt_poison_others(monkeypatch):
    """A single chunk raising returns failure entries for just that chunk."""
    from unifile import ollama as _ol

    state = {'call': 0}

    def fake_chunk(folders, **kw):
        state['call'] += 1
        if state['call'] == 2:
            raise RuntimeError("simulated chunk failure")
        return [{'name': None, 'category': 'Documents', 'confidence': 80,
                 'method': 'llm_batch', 'detail': 'ok'} for _ in folders]

    monkeypatch.setattr(_ol, '_ollama_classify_batch_chunk', fake_chunk)
    folders = [{'folder_name': f'f{i}', 'folder_path': '', 'context': ''}
               for i in range(50)]
    out = _ol.ollama_classify_batch(folders, chunk_limit=25)
    assert len(out) == 50
    # First 25 succeeded
    assert all(r['category'] == 'Documents' for r in out[:25])
    # Second chunk (25) failed — each entry has category=None and detail containing "error"
    assert all(r['category'] is None for r in out[25:])
    assert all('error' in (r.get('detail') or '') for r in out[25:])


def test_ollama_batch_empty_input():
    from unifile.ollama import ollama_classify_batch
    assert ollama_classify_batch([]) == []


# ── CLI --output-json scan plan writer ────────────────────────────────────────

def test_write_scan_json_serializes_file_items(tmp_path):
    """_write_scan_json should produce a well-formed JSON plan from a mock
    window exposing file_items + cmb_op."""
    from unifile.__main__ import _write_scan_json

    class _MockItem:
        def __init__(self, name, src, cat, conf):
            self.name = name
            self.full_src = src
            self.full_dst = src + '.new'
            self.category = cat
            self.confidence = conf
            self.method = 'test'
            self.size = 100
            self.selected = True
            self.status = 'Pending'

    class _MockCmb:
        def currentText(self):
            return 'PC Files'

    class _MockTxt:
        def text(self):
            return '/tmp/src'

    class _MockWindow:
        def __init__(self):
            self.file_items = [
                _MockItem('a.txt', '/tmp/a.txt', 'Documents', 90),
                _MockItem('b.jpg', '/tmp/b.jpg', 'Images', 95),
            ]
            self.cat_items = []
            self.aep_items = []
            self.cmb_op = _MockCmb()
            self.txt_src = _MockTxt()
            self._cli_source = ''
            self._log_messages: list[str] = []

        def _log(self, msg):
            self._log_messages.append(msg)

    w = _MockWindow()
    output = tmp_path / 'plan.json'
    _write_scan_json(w, str(output))
    assert output.exists()
    data = json.loads(output.read_text(encoding='utf-8'))
    assert data['version'] == '1'
    assert data['mode'] == 'PC Files'
    assert len(data['items']) == 2
    assert data['items'][0]['name'] == 'a.txt'
    assert data['items'][0]['category'] == 'Documents'
    assert data['items'][1]['category'] == 'Images'
    # Log emitted a success message
    assert any('Scan plan exported' in m for m in w._log_messages)


def test_classify_subcommand_pdf(tmp_path, capsys):
    """The CLI `classify` subcommand produces JSON with a usable category."""
    from unifile.__main__ import _cmd_classify
    import argparse

    pdf = tmp_path / 'report.pdf'
    pdf.write_bytes(b'%PDF-1.4\n' + b'x' * 100)
    ns = argparse.Namespace(path=str(pdf), json=True)
    rc = _cmd_classify(ns)
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data['kind'] == 'file'
    assert data['category'] == 'Documents'
    assert data['confidence'] >= 80


def test_classify_subcommand_missing_path(tmp_path, capsys):
    from unifile.__main__ import _cmd_classify
    import argparse
    ns = argparse.Namespace(path=str(tmp_path / 'does_not_exist.foo'), json=False)
    rc = _cmd_classify(ns)
    assert rc == 2
    err = capsys.readouterr().err
    assert 'does not exist' in err


def test_classify_subcommand_folder(tmp_path, capsys):
    """Folder classification returns the 'folder' kind and a tuple-like result."""
    from unifile.__main__ import _cmd_classify
    import argparse
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'document.pdf').write_bytes(b'%PDF-1.4\n')
    ns = argparse.Namespace(path=str(tmp_path / 'sub'), json=True)
    rc = _cmd_classify(ns)
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data['kind'] == 'folder'
    assert 'confidence' in data
    assert 'method' in data
