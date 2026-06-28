"""Tests for the durable watch-mode job queue (unifile.watch_jobs)."""
import os
import time

import pytest

from unifile.watch_jobs import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_READY,
    STATE_RUNNING,
    STATE_SETTLING,
    add_or_update_job,
    check_settle,
    dismiss_job,
    get_failed_jobs,
    get_pending_count,
    get_ready_folders,
    load_jobs,
    mark_completed,
    mark_failed,
    mark_running,
    purge_completed,
    recover_stale_running,
    retry_job,
    save_jobs,
)

# ── Persistence ──────────────────────────────────────────────────────────────

def test_save_and_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr('unifile.watch_jobs._JOBS_FILE', str(tmp_path / 'jobs.json'))
    jobs = [{'file_path': '/a/b.txt', 'state': STATE_SETTLING}]
    save_jobs(jobs)
    loaded = load_jobs()
    assert len(loaded) == 1
    assert loaded[0]['file_path'] == '/a/b.txt'


def test_load_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr('unifile.watch_jobs._JOBS_FILE', str(tmp_path / 'nope.json'))
    assert load_jobs() == []


# ── Add/update jobs ──────────────────────────────────────────────────────────

def test_add_new_job(tmp_path):
    f = tmp_path / 'file.txt'
    f.write_text('data')
    jobs = add_or_update_job([], str(tmp_path), str(f), 2.0)
    assert len(jobs) == 1
    assert jobs[0]['state'] == STATE_SETTLING
    assert jobs[0]['file_name'] == 'file.txt'


def test_update_existing_settling_job(tmp_path):
    f = tmp_path / 'file.txt'
    f.write_text('data')
    jobs = add_or_update_job([], str(tmp_path), str(f), 2.0)
    old_deadline = jobs[0]['settle_deadline']
    time.sleep(0.05)
    jobs = add_or_update_job(jobs, str(tmp_path), str(f), 2.0)
    assert len(jobs) == 1
    assert jobs[0]['settle_deadline'] > old_deadline


def test_add_does_not_duplicate(tmp_path):
    f = tmp_path / 'file.txt'
    f.write_text('data')
    jobs = add_or_update_job([], str(tmp_path), str(f), 2.0)
    jobs = add_or_update_job(jobs, str(tmp_path), str(f), 2.0)
    assert len(jobs) == 1


# ── Settle checks ───────────────────────────────────────────────────────────

def test_settle_promotes_stable_file(tmp_path):
    f = tmp_path / 'stable.txt'
    f.write_text('done')
    jobs = add_or_update_job([], str(tmp_path), str(f), 0.0)
    jobs[0]['settle_deadline'] = time.time() - 1
    jobs = check_settle(jobs, 0.0)
    assert jobs[0]['state'] == STATE_READY


def test_settle_resets_on_size_change(tmp_path):
    f = tmp_path / 'growing.txt'
    f.write_text('small')
    jobs = add_or_update_job([], str(tmp_path), str(f), 5.0)
    jobs[0]['settle_deadline'] = time.time() - 1
    f.write_text('much larger content now')
    jobs = check_settle(jobs, 5.0)
    assert jobs[0]['state'] == STATE_SETTLING


def test_settle_completes_if_file_deleted(tmp_path):
    f = tmp_path / 'temp.txt'
    f.write_text('bye')
    jobs = add_or_update_job([], str(tmp_path), str(f), 0.0)
    f.unlink()
    jobs = check_settle(jobs, 0.0)
    assert jobs[0]['state'] == STATE_COMPLETED
    assert 'disappeared' in jobs[0]['error']


# ── State transitions ───────────────────────────────────────────────────────

def test_mark_running():
    jobs = [{'folder': '/a', 'file_path': '/a/f.txt', 'state': STATE_READY}]
    jobs = mark_running(jobs, '/a')
    assert jobs[0]['state'] == STATE_RUNNING


def test_mark_completed():
    jobs = [{'folder': '/a', 'file_path': '/a/f.txt', 'state': STATE_RUNNING}]
    jobs = mark_completed(jobs, '/a')
    assert jobs[0]['state'] == STATE_COMPLETED


def test_mark_failed_with_retry():
    jobs = [{'folder': '/a', 'file_path': '/a/f.txt', 'state': STATE_RUNNING, 'retries': 0}]
    jobs = mark_failed(jobs, '/a', 'scan error')
    assert jobs[0]['state'] == STATE_READY
    assert jobs[0]['retries'] == 1


def test_mark_failed_max_retries():
    jobs = [{'folder': '/a', 'file_path': '/a/f.txt', 'state': STATE_RUNNING, 'retries': 2}]
    jobs = mark_failed(jobs, '/a', 'scan error')
    assert jobs[0]['state'] == STATE_FAILED
    assert 'max retries' in jobs[0]['error']


# ── Retry/dismiss ────────────────────────────────────────────────────────────

def test_retry_failed_job():
    jobs = [{'file_path': '/a/f.txt', 'state': STATE_FAILED, 'retries': 3, 'error': 'boom'}]
    jobs = retry_job(jobs, '/a/f.txt')
    assert jobs[0]['state'] == STATE_READY
    assert jobs[0]['retries'] == 0


def test_dismiss_failed_job():
    jobs = [
        {'file_path': '/a/f.txt', 'state': STATE_FAILED},
        {'file_path': '/a/g.txt', 'state': STATE_SETTLING},
    ]
    jobs = dismiss_job(jobs, '/a/f.txt')
    assert len(jobs) == 1
    assert jobs[0]['file_path'] == '/a/g.txt'


# ── Query helpers ────────────────────────────────────────────────────────────

def test_get_ready_folders():
    jobs = [
        {'folder': '/a', 'state': STATE_READY},
        {'folder': '/a', 'state': STATE_READY},
        {'folder': '/b', 'state': STATE_SETTLING},
    ]
    assert get_ready_folders(jobs) == ['/a']


def test_get_failed_jobs():
    jobs = [
        {'state': STATE_FAILED, 'error': 'x'},
        {'state': STATE_READY},
    ]
    assert len(get_failed_jobs(jobs)) == 1


def test_get_pending_count():
    jobs = [
        {'state': STATE_SETTLING},
        {'state': STATE_READY},
        {'state': STATE_COMPLETED},
    ]
    assert get_pending_count(jobs) == 2


# ── Cleanup ──────────────────────────────────────────────────────────────────

def test_purge_completed_old():
    jobs = [
        {'state': STATE_COMPLETED, 'detected_at': time.time() - 100000},
        {'state': STATE_SETTLING, 'detected_at': time.time()},
    ]
    result = purge_completed(jobs)
    assert len(result) == 1
    assert result[0]['state'] == STATE_SETTLING


def test_purge_keeps_recent_completed():
    jobs = [{'state': STATE_COMPLETED, 'detected_at': time.time()}]
    assert len(purge_completed(jobs)) == 1


# ── Restart recovery ────────────────────────────────────────────────────────

def test_recover_stale_running():
    jobs = [
        {'file_path': '/a/f.txt', 'state': STATE_RUNNING},
        {'file_path': '/b/g.txt', 'state': STATE_READY},
    ]
    jobs = recover_stale_running(jobs)
    assert jobs[0]['state'] == STATE_READY
    assert 'recovered' in jobs[0]['error']
    assert jobs[1]['state'] == STATE_READY


# ── Editor integration ──────────────────────────────────────────────────────

def test_watch_history_dialog_importable():
    from unifile.dialogs.tools import WatchHistoryDialog
    assert WatchHistoryDialog is not None
