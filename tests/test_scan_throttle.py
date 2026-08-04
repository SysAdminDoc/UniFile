"""Tests for configurable, cancellation-aware scan pacing."""

import pytest

from unifile.scan_throttle import (
    DEFAULT_BATTERY_POLL_SECONDS,
    DEFAULT_DELAY_MS,
    DEFAULT_PAUSE_ON_BATTERY,
    MAX_DELAY_MS,
    THROTTLE_DELAY_MS_KEY,
    THROTTLE_PAUSE_BATTERY_KEY,
    THROTTLE_POLL_SECONDS_KEY,
    ScanThrottle,
    load_scan_throttle_settings,
    save_scan_throttle_settings,
)


def test_scan_throttle_settings_normalize_and_round_trip():
    settings = {
        THROTTLE_DELAY_MS_KEY: 'not-a-number',
        THROTTLE_PAUSE_BATTERY_KEY: 'false',
        THROTTLE_POLL_SECONDS_KEY: 999,
    }
    loaded = load_scan_throttle_settings(settings)
    assert loaded == {
        'delay_ms': DEFAULT_DELAY_MS,
        'pause_on_battery': False,
        'battery_poll_seconds': 60,
    }

    saved = save_scan_throttle_settings(
        settings, delay_ms=MAX_DELAY_MS + 1, pause_on_battery=True,
        battery_poll_seconds=0,
    )
    assert saved == {
        'delay_ms': MAX_DELAY_MS,
        'pause_on_battery': True,
        'battery_poll_seconds': 1,
    }
    assert load_scan_throttle_settings(settings) == saved


def test_scan_throttle_delays_in_small_cancellable_slots():
    sleeps = []
    throttle = ScanThrottle(
        {
            THROTTLE_DELAY_MS_KEY: 120,
            THROTTLE_PAUSE_BATTERY_KEY: False,
            THROTTLE_POLL_SECONDS_KEY: DEFAULT_BATTERY_POLL_SECONDS,
        },
        battery_probe=lambda: None,
        sleep_fn=sleeps.append,
    )

    assert throttle.wait() is True
    assert len(sleeps) == 3
    assert sum(sleeps) == pytest.approx(0.12)


def test_scan_throttle_pauses_on_battery_and_resumes_on_ac():
    battery_states = iter([True, False])
    sleeps = []
    logs = []
    throttle = ScanThrottle(
        {
            THROTTLE_DELAY_MS_KEY: 0,
            THROTTLE_PAUSE_BATTERY_KEY: True,
            THROTTLE_POLL_SECONDS_KEY: 5,
        },
        battery_probe=lambda: next(battery_states),
        sleep_fn=sleeps.append,
    )

    assert throttle.wait(log_cb=logs.append) is True
    assert sleeps == [0.25]
    assert logs == [
        '  Scan throttle paused while the device is on battery',
        '  Scan throttle resumed on AC power',
    ]


def test_scan_throttle_cancellation_interrupts_battery_pause():
    cancelled = [False]
    sleeps = []

    def sleep_and_cancel(_seconds):
        sleeps.append(_seconds)
        cancelled[0] = True

    throttle = ScanThrottle(
        {
            THROTTLE_DELAY_MS_KEY: 0,
            THROTTLE_PAUSE_BATTERY_KEY: True,
            THROTTLE_POLL_SECONDS_KEY: 5,
        },
        battery_probe=lambda: True,
        sleep_fn=sleep_and_cancel,
    )

    assert throttle.wait(cancelled=lambda: cancelled[0]) is False
    assert sleeps == [0.25]
