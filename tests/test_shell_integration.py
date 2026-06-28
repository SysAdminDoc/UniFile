"""Shell integration command contracts."""

import subprocess
import sys


def test_source_arguments_quotes_path_token_and_enables_preview(monkeypatch):
    from unifile import shell_integration as si

    monkeypatch.setattr(si, "_exe_and_args", lambda: ("python.exe", '"C:/repo/run.py"'))

    assert si._source_arguments("%1") == '"C:/repo/run.py" --source "%1" --show-preview'
    assert si._source_arguments("%V", show_preview=False) == '"C:/repo/run.py" --source "%V"'


def test_powershell_string_escapes_embedded_quotes_and_apostrophes():
    from unifile import shell_integration as si

    assert si._ps_string('--source "%1" --show-preview') == "'--source \"%1\" --show-preview'"
    assert si._ps_string("C:/User's Apps/UniFile.exe") == "'C:/User''s Apps/UniFile.exe'"


def test_install_context_menu_registers_preview_commands(monkeypatch):
    from unifile import shell_integration as si

    calls = []
    monkeypatch.setattr(si.sys, "platform", "win32")
    monkeypatch.setattr(si, "_exe_and_args", lambda: ("C:/Python/python.exe", '"C:/repo/run.py"'))
    monkeypatch.setattr(si, "_icon_path", lambda: "C:/repo/icon.ico")
    monkeypatch.setattr(si, "_set_reg_value", lambda key, name, value: calls.append((key, name, value)))

    assert si.install_context_menu() is True

    commands = {key: value for key, name, value in calls if key.endswith(r"\command") and name == ""}
    assert commands[r"Software\Classes\Directory\shell\UniFile\command"] == (
        '"C:/Python/python.exe" "C:/repo/run.py" --source "%1" --show-preview'
    )
    assert commands[r"Software\Classes\Directory\Background\shell\UniFile\command"] == (
        '"C:/Python/python.exe" "C:/repo/run.py" --source "%V" --show-preview'
    )


def test_cli_help_lists_show_preview_flag():
    cp = subprocess.run(
        [sys.executable, "-m", "unifile", "--help"],
        capture_output=True,
        text=True,
    )
    assert cp.returncode == 0
    assert "--show-preview" in cp.stdout
