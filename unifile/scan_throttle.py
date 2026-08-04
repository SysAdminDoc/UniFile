"""I/O pacing and battery-aware pause controls for background scans."""

import ctypes
import sys
import time
from pathlib import Path

DEFAULT_DELAY_MS = 2
DEFAULT_PAUSE_ON_BATTERY = True
DEFAULT_BATTERY_POLL_SECONDS = 5
MAX_DELAY_MS = 2_000
MAX_BATTERY_POLL_SECONDS = 60

THROTTLE_DELAY_MS_KEY = 'scan_throttle/delay_ms'
THROTTLE_PAUSE_BATTERY_KEY = 'scan_throttle/pause_on_battery'
THROTTLE_POLL_SECONDS_KEY = 'scan_throttle/battery_poll_seconds'


def _bounded_int(value, default, minimum, maximum) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _setting_value(settings, key, default):
    if isinstance(settings, dict):
        return settings.get(key, default)
    try:
        return settings.value(key, default)
    except (AttributeError, TypeError):
        return default


def _bool_value(value, default=False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'1', 'true', 'yes', 'on'}:
            return True
        if lowered in {'0', 'false', 'no', 'off', ''}:
            return False
        return default
    return bool(value)


def load_scan_throttle_settings(settings=None) -> dict:
    """Load normalized pacing values from QSettings or a mapping."""
    if settings is None:
        try:
            from PyQt6.QtCore import QSettings
            settings = QSettings('UniFile', 'UniFile')
        except ImportError:
            settings = {}
    return {
        'delay_ms': _bounded_int(
            _setting_value(settings, THROTTLE_DELAY_MS_KEY, DEFAULT_DELAY_MS),
            DEFAULT_DELAY_MS, 0, MAX_DELAY_MS,
        ),
        'pause_on_battery': _bool_value(_setting_value(
            settings, THROTTLE_PAUSE_BATTERY_KEY, DEFAULT_PAUSE_ON_BATTERY
        ), DEFAULT_PAUSE_ON_BATTERY),
        'battery_poll_seconds': _bounded_int(
            _setting_value(
                settings, THROTTLE_POLL_SECONDS_KEY,
                DEFAULT_BATTERY_POLL_SECONDS,
            ),
            DEFAULT_BATTERY_POLL_SECONDS, 1, MAX_BATTERY_POLL_SECONDS,
        ),
    }


def save_scan_throttle_settings(settings, *, delay_ms: int,
                                pause_on_battery: bool,
                                battery_poll_seconds: int) -> dict:
    """Persist normalized pacing values and return what was saved."""
    values = {
        'delay_ms': _bounded_int(delay_ms, DEFAULT_DELAY_MS, 0, MAX_DELAY_MS),
        'pause_on_battery': bool(pause_on_battery),
        'battery_poll_seconds': _bounded_int(
            battery_poll_seconds, DEFAULT_BATTERY_POLL_SECONDS,
            1, MAX_BATTERY_POLL_SECONDS,
        ),
    }
    if isinstance(settings, dict):
        settings.update({
            THROTTLE_DELAY_MS_KEY: values['delay_ms'],
            THROTTLE_PAUSE_BATTERY_KEY: values['pause_on_battery'],
            THROTTLE_POLL_SECONDS_KEY: values['battery_poll_seconds'],
        })
    else:
        settings.setValue(THROTTLE_DELAY_MS_KEY, values['delay_ms'])
        settings.setValue(THROTTLE_PAUSE_BATTERY_KEY, values['pause_on_battery'])
        settings.setValue(
            THROTTLE_POLL_SECONDS_KEY, values['battery_poll_seconds']
        )
        try:
            settings.sync()
        except AttributeError:
            pass
    return values


def system_on_battery():
    """Return True/False for a known power state, or None when unavailable."""
    if sys.platform == 'win32':
        class _SystemPowerStatus(ctypes.Structure):
            _fields_ = [
                ('ac_line_status', ctypes.c_ubyte),
                ('battery_flag', ctypes.c_ubyte),
                ('battery_percent', ctypes.c_ubyte),
                ('reserved', ctypes.c_ubyte),
                ('battery_life_seconds', ctypes.c_uint32),
                ('battery_full_life_seconds', ctypes.c_uint32),
            ]

        status = _SystemPowerStatus()
        try:
            if ctypes.windll.kernel32.GetSystemPowerStatus(
                    ctypes.byref(status)):
                if status.ac_line_status == 0:
                    return True
                if status.ac_line_status == 1:
                    return False
        except (AttributeError, OSError):
            return None
        return None

    power_root = Path('/sys/class/power_supply')
    try:
        supplies = list(power_root.iterdir())
    except (OSError, PermissionError):
        return None
    ac_states = []
    for supply in supplies:
        try:
            supply_type = (supply / 'type').read_text(
                encoding='ascii', errors='ignore'
            ).strip().lower()
            if supply_type in {'mains', 'usb', 'usb_c'}:
                ac_states.append((supply / 'online').read_text(
                    encoding='ascii', errors='ignore').strip() == '1')
        except (OSError, PermissionError):
            continue
    if ac_states:
        return not any(ac_states)
    return None


class ScanThrottle:
    """Pace scan iterations while preserving prompt cancellation."""

    def __init__(self, settings=None, *, battery_probe=None,
                 sleep_fn=None, monotonic_fn=None):
        values = load_scan_throttle_settings(settings)
        self.delay_ms = values['delay_ms']
        self.pause_on_battery = values['pause_on_battery']
        self.battery_poll_seconds = values['battery_poll_seconds']
        self._battery_probe = battery_probe or system_on_battery
        self._sleep = sleep_fn or time.sleep
        self._monotonic = monotonic_fn or time.monotonic
        self._last_battery_poll = float('-inf')
        self._battery_state = None
        self._pause_logged = False

    @property
    def enabled(self) -> bool:
        return bool(self.delay_ms or self.pause_on_battery)

    def describe(self) -> str:
        battery = 'pause on battery' if self.pause_on_battery else 'battery pause off'
        return f"{self.delay_ms} ms/item, {battery}"

    def _battery_status(self, *, force=False):
        now = self._monotonic()
        if force or now - self._last_battery_poll >= self.battery_poll_seconds:
            try:
                self._battery_state = self._battery_probe()
            except Exception:
                self._battery_state = None
            self._last_battery_poll = now
        return self._battery_state

    def wait(self, *, cancelled=None, log_cb=None) -> bool:
        """Wait for one scan slot; return False when cancellation is requested."""
        cancelled = cancelled or (lambda: False)
        if not self.enabled:
            return not cancelled()

        if self.pause_on_battery:
            on_battery = self._battery_status()
            if on_battery is True:
                if not self._pause_logged and log_cb:
                    log_cb("  Scan throttle paused while the device is on battery")
                self._pause_logged = True
                while on_battery is True and not cancelled():
                    self._sleep(0.25)
                    on_battery = self._battery_status(force=True)
                if self._pause_logged and on_battery is False and log_cb:
                    log_cb("  Scan throttle resumed on AC power")
                self._pause_logged = False
                if cancelled():
                    return False

        remaining = self.delay_ms / 1000
        while remaining > 0 and not cancelled():
            slot = min(0.05, remaining)
            self._sleep(slot)
            remaining -= slot
        return not cancelled()


__all__ = [
    'DEFAULT_DELAY_MS', 'DEFAULT_PAUSE_ON_BATTERY',
    'DEFAULT_BATTERY_POLL_SECONDS', 'MAX_DELAY_MS',
    'MAX_BATTERY_POLL_SECONDS', 'THROTTLE_DELAY_MS_KEY',
    'THROTTLE_PAUSE_BATTERY_KEY', 'THROTTLE_POLL_SECONDS_KEY',
    'ScanThrottle', 'load_scan_throttle_settings',
    'save_scan_throttle_settings', 'system_on_battery',
]
