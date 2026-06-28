"""Durable watch-mode job queue with file-settle checks and retry status.

Jobs persist across app restarts via a JSON file in the app data directory.
Each job tracks a detected file change through states: settling → ready →
running → completed | failed. Files must remain size/mtime-stable for the
configured settle duration before a scan is triggered.
"""
import os
import time

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

_JOBS_FILE = os.path.join(_APP_DATA_DIR, 'watch_jobs.json')
_MAX_RETRIES = 3

STATE_SETTLING = 'settling'
STATE_READY = 'ready'
STATE_RUNNING = 'running'
STATE_COMPLETED = 'completed'
STATE_FAILED = 'failed'


def _file_stat(path: str) -> tuple:
    """Return (size, mtime) for a path, or (0, 0) if inaccessible."""
    try:
        st = os.stat(path)
        return (st.st_size, st.st_mtime)
    except OSError:
        return (0, 0)


def load_jobs() -> list[dict]:
    return load_json_safe(_JOBS_FILE, [], expected_type=list)


def save_jobs(jobs: list[dict]) -> None:
    save_json_safe(_JOBS_FILE, jobs)


def add_or_update_job(jobs: list[dict], folder: str, file_path: str, settle_secs: float) -> list[dict]:
    """Add a new settling job or reset the settle timer if the file changed."""
    now = time.time()
    stat = _file_stat(file_path)
    for job in jobs:
        if job.get('file_path') == file_path:
            if job['state'] in (STATE_COMPLETED,):
                job['state'] = STATE_SETTLING
            if job['state'] in (STATE_SETTLING, STATE_READY):
                job['detected_at'] = now
                job['last_stat'] = list(stat)
                job['settle_deadline'] = now + settle_secs
                job['state'] = STATE_SETTLING
            return jobs
    jobs.append({
        'folder': folder,
        'file_path': file_path,
        'file_name': os.path.basename(file_path),
        'detected_at': now,
        'last_stat': list(stat),
        'settle_deadline': now + settle_secs,
        'state': STATE_SETTLING,
        'retries': 0,
        'error': '',
    })
    return jobs


def check_settle(jobs: list[dict], settle_secs: float) -> list[dict]:
    """Promote settling jobs to ready if their file is size/mtime-stable."""
    now = time.time()
    for job in jobs:
        if job['state'] != STATE_SETTLING:
            continue
        path = job['file_path']
        if not os.path.exists(path):
            job['state'] = STATE_COMPLETED
            job['error'] = 'file disappeared before settle'
            continue
        current = list(_file_stat(path))
        if current != job.get('last_stat'):
            job['last_stat'] = current
            job['settle_deadline'] = now + settle_secs
            continue
        if now >= job.get('settle_deadline', 0):
            job['state'] = STATE_READY
    return jobs


def mark_running(jobs: list[dict], folder: str) -> list[dict]:
    """Mark all ready jobs for a folder as running."""
    for job in jobs:
        if job['folder'] == folder and job['state'] == STATE_READY:
            job['state'] = STATE_RUNNING
    return jobs


def mark_completed(jobs: list[dict], folder: str) -> list[dict]:
    """Mark all running jobs for a folder as completed."""
    for job in jobs:
        if job['folder'] == folder and job['state'] == STATE_RUNNING:
            job['state'] = STATE_COMPLETED
            job['error'] = ''
    return jobs


def mark_failed(jobs: list[dict], folder: str, error: str) -> list[dict]:
    """Mark all running jobs for a folder as failed."""
    for job in jobs:
        if job['folder'] == folder and job['state'] == STATE_RUNNING:
            job['retries'] = job.get('retries', 0) + 1
            if job['retries'] >= _MAX_RETRIES:
                job['state'] = STATE_FAILED
                job['error'] = f'{error} (max retries reached)'
            else:
                job['state'] = STATE_READY
                job['error'] = error
    return jobs


def retry_job(jobs: list[dict], file_path: str) -> list[dict]:
    """Reset a failed job back to ready for retry."""
    for job in jobs:
        if job['file_path'] == file_path and job['state'] == STATE_FAILED:
            job['state'] = STATE_READY
            job['retries'] = 0
            job['error'] = ''
    return jobs


def dismiss_job(jobs: list[dict], file_path: str) -> list[dict]:
    """Remove a failed job from the queue."""
    return [j for j in jobs if not (j['file_path'] == file_path and j['state'] == STATE_FAILED)]


def get_ready_folders(jobs: list[dict]) -> list[str]:
    """Return unique folders that have at least one ready job."""
    seen = set()
    result = []
    for job in jobs:
        if job['state'] == STATE_READY and job['folder'] not in seen:
            seen.add(job['folder'])
            result.append(job['folder'])
    return result


def get_failed_jobs(jobs: list[dict]) -> list[dict]:
    return [j for j in jobs if j['state'] == STATE_FAILED]


def get_pending_count(jobs: list[dict]) -> int:
    return sum(1 for j in jobs if j['state'] in (STATE_SETTLING, STATE_READY))


def purge_completed(jobs: list[dict], max_age_secs: float = 86400) -> list[dict]:
    """Remove completed jobs older than max_age_secs."""
    now = time.time()
    return [j for j in jobs if not (
        j['state'] == STATE_COMPLETED and
        now - j.get('detected_at', 0) > max_age_secs
    )]


def recover_stale_running(jobs: list[dict]) -> list[dict]:
    """On startup, reset any jobs stuck in 'running' back to 'ready'."""
    for job in jobs:
        if job['state'] == STATE_RUNNING:
            job['state'] = STATE_READY
            job['error'] = 'recovered after restart'
    return jobs
