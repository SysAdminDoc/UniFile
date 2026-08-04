"""Tests for the WAL-backed apply operation journal."""

import sqlite3


def _move_operation(current, original, timestamp):
    return {
        'type': 'move', 'src': str(current), 'dst': str(original),
        'timestamp': timestamp, 'category': 'Documents',
        'confidence': '95', 'status': 'Done',
    }


def test_operation_log_replays_newest_operations_first(tmp_path, monkeypatch):
    from unifile import cache

    undo_json = tmp_path / 'undo_stack.json'
    undo_legacy = tmp_path / 'undo_log.json'
    operation_db = tmp_path / 'operation_log.sqlite'
    monkeypatch.setattr(cache, '_UNDO_STACK_FILE', str(undo_json))
    monkeypatch.setattr(cache, '_UNDO_LOG_FILE', str(undo_legacy))
    monkeypatch.setattr(cache, '_OPERATION_LOG_DB', str(operation_db))

    first_current = tmp_path / 'first-current.txt'
    first_original = tmp_path / 'first-original.txt'
    second_current = tmp_path / 'second-current.txt'
    second_original = tmp_path / 'second-original.txt'
    third_current = tmp_path / 'third-current.txt'
    third_original = tmp_path / 'third-original.txt'
    first_current.write_text('first', encoding='utf-8')
    second_current.write_text('second', encoding='utf-8')
    third_current.write_text('third', encoding='utf-8')

    cache.save_undo_log([
        _move_operation(first_current, first_original, '2026-08-03T10:00:00'),
    ], source_dir=str(tmp_path), mode='files')
    cache.save_undo_log([
        _move_operation(second_current, second_original, '2026-08-03T10:01:00'),
        _move_operation(third_current, third_original, '2026-08-03T10:01:01'),
    ], source_dir=str(tmp_path), mode='files')

    connection = sqlite3.connect(operation_db)
    assert connection.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'wal'
    connection.close()

    reverse = list(cache.iter_operation_log_reverse())
    assert [entry['operation']['src'] for entry in reverse] == [
        str(third_current), str(second_current), str(first_current),
    ]
    assert cache.operation_log_count() == 3

    first_replay = cache.replay_operation_log(limit=1)
    assert first_replay['restored'] == 1
    assert third_original.read_text(encoding='utf-8') == 'third'
    assert second_current.exists()
    assert cache.operation_log_count() == 2
    assert cache.load_operation_batches()[-1]['status'] == 'partial'

    second_replay = cache.replay_operation_log(limit=10)
    assert second_replay['restored'] == 2
    assert first_original.read_text(encoding='utf-8') == 'first'
    assert second_original.read_text(encoding='utf-8') == 'second'
    assert cache.operation_log_count() == 0
    assert all(batch['status'] == 'undone'
               for batch in cache.load_operation_batches())

    stack = cache._load_undo_stack()
    assert len(stack) == 2
    assert all(batch['status'] == 'undone' for batch in stack)
