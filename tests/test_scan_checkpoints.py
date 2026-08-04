"""Coverage for SQLite-backed scan progress checkpoints."""

import json
import threading
from pathlib import Path

import pytest

from unifile.files import _ScanCache, scan_checkpoint_identity


def test_rule_classification_pool_runs_indexed_jobs_on_multiple_qthreads(monkeypatch):
    from unifile import workers

    barrier = threading.Barrier(2, timeout=5)
    thread_ids = set()
    thread_lock = threading.Lock()

    def classify(path, ext_map, is_folder, categories):
        del ext_map, is_folder, categories
        with thread_lock:
            thread_ids.add(threading.get_ident())
        barrier.wait()
        return (path, 90, 'threaded')

    monkeypatch.setattr(workers, '_classify_pc_item', classify)
    pool = workers._RuleClassificationPool(2, threading.Event())
    try:
        results = pool.classify([
            (index, f'item-{index}', {}, False, [])
            for index in range(4)
        ])
    finally:
        pool.close()

    assert len(thread_ids) == 2
    assert [results[index][0] for index in range(4)] == [
        f'item-{index}' for index in range(4)
    ]


def test_scan_checkpoint_commits_every_500_items():
    from unifile import workers

    class _Cache:
        def __init__(self):
            self.commits = 0
            self.records = []

        def checkpoint_prepare(self, *args):
            return False

        def checkpoint_load(self, *args):
            return {}

        def checkpoint_store(self, *args):
            self.records.append(args)

        def checkpoint_clear(self, *args):
            pass

        def commit(self):
            self.commits += 1

    cache = _Cache()
    tracker = workers._ScanCheckpointTracker(
        cache, 'C:/library', mode='rules', categories=[], destination='',
        scan_depth=0, check_hashes=False, include_folders=True,
        include_files=True, ext_filter=None, total_items=501,
    )

    for index in range(500):
        tracker.record(f'item-{index}', index, {'category': 'Other'})

    assert cache.commits == 1
    assert len(cache.records) == 500

    tracker.record('item-500', 500, {'category': 'Other'})
    tracker.flush()
    assert cache.commits == 2


@pytest.fixture
def _disable_protected_paths(monkeypatch):
    """Allow temporary test directories through UniFile's safety filter."""
    import unifile.config as config

    monkeypatch.setattr(
        config, '_cached_protected_paths',
        {'system': [], 'custom': [], 'enabled': False},
    )


def test_cancelled_scan_resumes_completed_items(tmp_path, monkeypatch,
                                                _disable_protected_paths):
    from unifile import workers

    root = tmp_path / 'scan-root'
    root.mkdir()
    for index in range(3):
        (root / f'item-{index}.txt').write_text('content', encoding='utf-8')

    db_path = tmp_path / 'scan-cache.db'

    class _TempCache(_ScanCache):
        def __init__(self):
            super().__init__(str(db_path))

    monkeypatch.setattr(workers, '_ScanCache', _TempCache)
    monkeypatch.setattr(workers, 'MetadataExtractor', type(
        '_Metadata', (), {'extract': staticmethod(lambda *args, **kwargs: {})}
    ))

    categories = [{'name': 'Documents', 'extensions': ['txt']}]
    first_calls = []
    first_worker = None

    def cancel_after_first(path, ext_map, is_folder, configured_categories):
        first_calls.append(Path(path).name)
        result = ('Documents', 90, 'test')
        if len(first_calls) == 1:
            first_worker.cancel()
        return result

    monkeypatch.setattr(workers, '_classify_pc_item', cancel_after_first)
    first_worker = workers.ScanFilesWorker(
        str(root), '', categories, include_folders=False, include_files=True,
    )
    first_results = []
    first_worker.result_ready.connect(first_results.append)
    first_worker.run()

    assert len(first_results) == 1
    assert len(first_calls) == 1

    second_calls = []

    def classify_remaining(path, ext_map, is_folder, configured_categories):
        second_calls.append(Path(path).name)
        return ('Documents', 90, 'test')

    monkeypatch.setattr(workers, '_classify_pc_item', classify_remaining)
    second_worker = workers.ScanFilesWorker(
        str(root), '', categories, include_folders=False, include_files=True,
    )
    second_results = []
    second_logs = []
    second_worker.result_ready.connect(second_results.append)
    second_worker.log.connect(second_logs.append)
    second_worker.run()

    assert len(second_results) == 3
    assert len(second_calls) == 2
    assert any('Resuming 1 completed item' in message for message in second_logs)
    assert any('resumed without reclassification' in message for message in second_logs)

    scan_id, config_json = scan_checkpoint_identity(
        str(root), mode='rules', categories=categories, include_folders=False,
        include_files=True,
        extra={'effective_categories': categories, 'directory_rules': None},
    )
    cache = _ScanCache(str(db_path))
    cache.open()
    assert cache.checkpoint_load(scan_id) == {}
    assert cache._conn.execute(
        'SELECT COUNT(*) FROM scan_checkpoints WHERE scan_id=?', (scan_id,)
    ).fetchone()[0] == 0
    assert config_json
    cache.close()


def test_incremental_scan_reuses_unchanged_files_and_honors_force_rescan(
    tmp_path, monkeypatch, _disable_protected_paths,
):
    from unifile import workers

    root = tmp_path / 'incremental-root'
    root.mkdir()
    source = root / 'item.txt'
    source.write_text('initial', encoding='utf-8')
    db_path = tmp_path / 'incremental-cache.db'

    class _TempCache(_ScanCache):
        def __init__(self):
            super().__init__(str(db_path))

    monkeypatch.setattr(workers, '_ScanCache', _TempCache)
    monkeypatch.setattr(workers, 'MetadataExtractor', type(
        '_Metadata', (), {'extract': staticmethod(lambda *args, **kwargs: {})}
    ))
    categories = [{'name': 'Documents', 'extensions': ['txt']}]
    calls = []

    def classify(path, ext_map, is_folder, configured_categories):
        calls.append(Path(path).name)
        return ('Documents', 90, 'test')

    monkeypatch.setattr(workers, '_classify_pc_item', classify)
    first_worker = workers.ScanFilesWorker(
        str(root), '', categories, include_folders=False, include_files=True,
    )
    first_results = []
    first_worker.result_ready.connect(first_results.append)
    first_worker.run()

    assert len(first_results) == 1
    assert calls == ['item.txt']

    def fail_if_reclassified(*args, **kwargs):
        raise AssertionError('unchanged file was reclassified')

    monkeypatch.setattr(workers, '_classify_pc_item', fail_if_reclassified)
    second_worker = workers.ScanFilesWorker(
        str(root), '', categories, include_folders=False, include_files=True,
    )
    second_results = []
    second_logs = []
    second_worker.result_ready.connect(second_results.append)
    second_worker.log.connect(second_logs.append)
    second_worker.run()

    assert len(second_results) == 1
    assert second_results[0]['method'] == 'test+cached'
    assert any('[CACHE] 1 items loaded' in message for message in second_logs)

    source.write_text('changed content', encoding='utf-8')
    changed_calls = []

    def classify_changed(path, ext_map, is_folder, configured_categories):
        changed_calls.append(Path(path).name)
        return ('Documents', 91, 'changed')

    monkeypatch.setattr(workers, '_classify_pc_item', classify_changed)
    changed_worker = workers.ScanFilesWorker(
        str(root), '', categories, include_folders=False, include_files=True,
    )
    changed_worker.run()
    assert changed_calls == ['item.txt']

    force_calls = []

    def classify_forced(path, ext_map, is_folder, configured_categories):
        force_calls.append(Path(path).name)
        return ('Documents', 92, 'forced')

    monkeypatch.setattr(workers, '_classify_pc_item', classify_forced)
    forced_worker = workers.ScanFilesWorker(
        str(root), '', categories, include_folders=False, include_files=True,
        force_rescan=True,
    )
    forced_results = []
    forced_worker.result_ready.connect(forced_results.append)
    forced_worker.run()

    assert force_calls == ['item.txt']
    assert forced_results[0]['method'] == 'forced'


def test_llm_scan_resumes_emitted_batch_results(tmp_path, monkeypatch,
                                                _disable_protected_paths):
    from unifile import workers

    root = tmp_path / 'llm-root'
    root.mkdir()
    for index in range(2):
        (root / f'item-{index}.txt').write_text('content', encoding='utf-8')

    db_path = tmp_path / 'llm-cache.db'

    class _TempCache(_ScanCache):
        def __init__(self):
            super().__init__(str(db_path))

    settings = {
        'url': 'http://checkpoint.test',
        'model': 'checkpoint-model',
        'vision_enabled': False,
        'content_extraction': False,
        'content_max_chars': 200,
    }
    monkeypatch.setattr(workers, '_ScanCache', _TempCache)
    monkeypatch.setattr(workers, 'load_ollama_settings', lambda: settings)
    monkeypatch.setattr(
        workers.ScanFilesLLMWorker, '_ensure_ollama_ready',
        lambda self, configured: True,
    )
    monkeypatch.setattr(
        workers, 'ollama_test_connection', lambda *args: (True, 'ok', [])
    )
    monkeypatch.setattr(workers, 'load_photo_settings', lambda: {'enabled': False})
    monkeypatch.setattr(workers, 'MetadataExtractor', type(
        '_Metadata', (), {'extract': staticmethod(lambda *args, **kwargs: {})}
    ))

    generate_calls = []
    first_worker = None

    def fake_generate(prompt, **kwargs):
        generate_calls.append(prompt)
        first_worker.cancel()
        return json.dumps([
            {
                'category': 'Documents', 'confidence': 92,
                'reason': 'batch', 'suggested_name': 'document',
            },
            {
                'category': 'Documents', 'confidence': 91,
                'reason': 'batch', 'suggested_name': 'document_two',
            },
        ])

    monkeypatch.setattr(workers, '_ollama_generate', fake_generate)
    categories = [{'name': 'Documents', 'extensions': ['txt']}]
    first_worker = workers.ScanFilesLLMWorker(
        str(root), '', categories, include_folders=False, include_files=True,
    )
    first_results = []
    first_worker.result_ready.connect(first_results.append)
    first_worker.run()

    assert len(first_results) == 2
    assert len(generate_calls) == 1

    second_worker = workers.ScanFilesLLMWorker(
        str(root), '', categories, include_folders=False, include_files=True,
    )
    second_results = []
    second_logs = []
    second_worker.result_ready.connect(second_results.append)
    second_worker.log.connect(second_logs.append)
    second_worker.run()

    assert len(second_results) == 2
    assert len(generate_calls) == 1
    assert any('resumed without reclassification' in message for message in second_logs)
