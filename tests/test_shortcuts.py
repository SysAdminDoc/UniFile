"""Tests for configurable keyboard shortcut persistence and editing."""

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QDialog

from unifile.dialogs.shortcuts import KeyboardShortcutsDialog
from unifile.shortcuts import ShortcutManager, is_os_reserved, normalize_sequence


def _settings(tmp_path):
    return QSettings(str(tmp_path / "shortcuts.ini"), QSettings.Format.IniFormat)


def test_default_shortcuts_are_unique_and_not_windows_reserved(tmp_path):
    manager = ShortcutManager(_settings(tmp_path))
    values = manager.values()

    enabled = [value for value in values.values() if value]
    assert len(enabled) == len(set(enabled))
    assert all(not is_os_reserved(value) for value in enabled)


def test_shortcuts_persist_and_migrate_legacy_voice_binding(tmp_path):
    settings = _settings(tmp_path)
    settings.setValue("voice/shortcut", "Ctrl+Alt+V")
    manager = ShortcutManager(settings)

    assert manager.sequence("voice_control") == normalize_sequence("Ctrl+Alt+V")
    assert manager.set_sequence("command_palette", "Ctrl+Shift+P") == (True, "")

    reloaded = ShortcutManager(_settings(tmp_path))
    assert reloaded.sequence("command_palette") == normalize_sequence("Ctrl+Shift+P")
    assert reloaded.sequence("voice_control") == normalize_sequence("Ctrl+Alt+V")


def test_shortcut_manager_rejects_duplicate_and_reserved_bindings(tmp_path):
    manager = ShortcutManager(_settings(tmp_path))
    values = manager.values()
    values["start_scan"] = values["command_palette"]
    ok, errors = manager.save_values(values)
    assert not ok
    assert "start_scan" in errors
    assert "conflict" in errors["start_scan"].lower()

    values = manager.values()
    values["command_palette"] = normalize_sequence(QKeySequence("Alt+F4"))
    ok, errors = manager.save_values(values)
    assert not ok
    assert "command_palette" in errors
    assert "reserved" in errors["command_palette"].lower()


def test_keyboard_shortcuts_dialog_saves_rebound_sequence(qtbot, tmp_path):
    manager = ShortcutManager(_settings(tmp_path))
    dialog = KeyboardShortcutsDialog(manager=manager)
    qtbot.addWidget(dialog)
    saved = []
    dialog.saved.connect(saved.append)

    dialog._editors["command_palette"].setKeySequence(QKeySequence("Ctrl+Shift+P"))
    assert dialog.btn_save.isEnabled()
    dialog.btn_save.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert saved and saved[0]["command_palette"] == normalize_sequence("Ctrl+Shift+P")
    assert manager.sequence("command_palette") == normalize_sequence("Ctrl+Shift+P")
