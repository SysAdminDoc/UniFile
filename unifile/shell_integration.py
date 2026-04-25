"""UniFile — Windows Shell Integration.

Registers an "Organize with UniFile" right-click context menu entry for
folders in Windows Explorer. All writes go to HKCU (no admin required).

Public API:
    install()         -- register context menu + Send To shortcut
    uninstall()       -- remove all shell integration
    is_installed()    -- check current registration state
    install_sendto()  -- Send To shortcut only
    uninstall_sendto()

The context menu launches:
    python run.py --source "<folder_path>"

If running as a frozen exe (PyInstaller), the exe path is used instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _exe_and_args() -> tuple[str, str]:
    """Return (executable, extra_args) used to launch UniFile.

    Frozen builds:   ("C:\\...\\UniFile.exe", "")
    Script builds:   ("C:\\...\\python.exe", '"C:\\...\\run.py"')
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return exe, ""
    python = sys.executable
    run_py = Path(__file__).resolve().parent.parent / "run.py"
    return python, f'"{run_py}"'


def _menu_root() -> str:
    return r"Software\Classes\Directory\shell\UniFile"


def _background_root() -> str:
    return r"Software\Classes\Directory\Background\shell\UniFile"


def _icon_path() -> str:
    """Return path to icon.ico for the context menu icon."""
    candidates = [
        Path(__file__).resolve().parent.parent / "icon.ico",
        Path(__file__).resolve().parent.parent / "icon.png",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


def _sendto_dir() -> Path:
    """Return the Windows SendTo directory for the current user."""
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "SendTo"


def _sendto_lnk() -> Path:
    return _sendto_dir() / "Organize with UniFile.lnk"


# ── Registry helpers (winreg — Windows only) ──────────────────────────────────

def _set_reg_value(key_path: str, name: str, value: str) -> None:
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path,
                             0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _delete_reg_tree(key_path: str) -> bool:
    """Delete a registry key and all its subkeys. Returns True if deleted."""
    try:
        import winreg
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, key_path + r"\command")
    except (OSError, ImportError):
        pass
    try:
        import winreg
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, key_path)
        return True
    except (OSError, ImportError):
        return False


def _reg_value_exists(key_path: str, name: str) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, name)
        return True
    except (OSError, ImportError):
        return False


# ── Send To shortcut ──────────────────────────────────────────────────────────

def install_sendto() -> bool:
    """Create a .lnk in the Windows 'Send To' folder.

    Returns True on success.
    """
    if sys.platform != "win32":
        return False
    try:
        import winshell  # type: ignore
        exe, extra = _exe_and_args()
        lnk_path = str(_sendto_lnk())
        with winshell.shortcut(lnk_path) as lnk:
            lnk.path = exe
            lnk.arguments = extra + " --source %1" if extra else "--source %1"
            lnk.description = "Organize selected folder with UniFile"
            icon = _icon_path()
            if icon:
                lnk.icon_location = (icon, 0)
        return True
    except ImportError:
        # winshell not available — create shortcut via PowerShell
        try:
            lnk_path = str(_sendto_lnk())
            exe, extra = _exe_and_args()
            target = exe
            arguments = (extra + " --source %1").strip() if extra else "--source %1"
            ps_script = (
                f'$ws = New-Object -ComObject WScript.Shell; '
                f'$lnk = $ws.CreateShortcut("{lnk_path}"); '
                f'$lnk.TargetPath = "{target}"; '
                f'$lnk.Arguments = "{arguments}"; '
                f'$lnk.Description = "Organize with UniFile"; '
                f'$lnk.Save()'
            )
            import subprocess
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                timeout=15,
            )
            return _sendto_lnk().exists()
        except Exception:
            return False
    except Exception:
        return False


def uninstall_sendto() -> bool:
    """Remove the Send To shortcut. Returns True if removed."""
    lnk = _sendto_lnk()
    if lnk.exists():
        try:
            lnk.unlink()
            return True
        except OSError:
            return False
    return True


def is_sendto_installed() -> bool:
    return _sendto_lnk().exists()


# ── Context menu ──────────────────────────────────────────────────────────────

def install_context_menu() -> bool:
    """Register 'Organize with UniFile' on right-click for folders in Explorer.

    Creates two registry keys in HKCU (no admin required):
      - Directory\\shell\\UniFile         (folder right-click)
      - Directory\\Background\\shell\\UniFile  (background right-click)

    Returns True on success.
    """
    if sys.platform != "win32":
        return False
    try:
        exe, extra = _exe_and_args()
        # Build the command string
        if extra:
            cmd_folder = f'"{exe}" {extra} --source "%1"'
            cmd_bg     = f'"{exe}" {extra} --source "%V"'
        else:
            cmd_folder = f'"{exe}" --source "%1"'
            cmd_bg     = f'"{exe}" --source "%V"'

        icon = _icon_path()

        for root, cmd in ((_menu_root(), cmd_folder),
                          (_background_root(), cmd_bg)):
            _set_reg_value(root, "", "Organize with UniFile")
            _set_reg_value(root, "Icon", icon)
            _set_reg_value(root + r"\command", "", cmd)

        return True
    except Exception:
        return False


def uninstall_context_menu() -> bool:
    """Remove the context menu entries. Returns True if both removed."""
    ok1 = _delete_reg_tree(_menu_root())
    ok2 = _delete_reg_tree(_background_root())
    return ok1 or ok2


def is_context_menu_installed() -> bool:
    """Return True if the context menu entry exists in the registry."""
    return _reg_value_exists(_menu_root(), "")


# ── Combined helpers ──────────────────────────────────────────────────────────

def install() -> dict[str, bool]:
    """Install both context menu and Send To shortcut.

    Returns {'context_menu': bool, 'sendto': bool}.
    """
    return {
        "context_menu": install_context_menu(),
        "sendto": install_sendto(),
    }


def uninstall() -> dict[str, bool]:
    """Remove both context menu and Send To shortcut."""
    return {
        "context_menu": uninstall_context_menu(),
        "sendto": uninstall_sendto(),
    }


def is_installed() -> dict[str, bool]:
    """Return installation state of each integration point."""
    return {
        "context_menu": is_context_menu_installed(),
        "sendto": is_sendto_installed(),
    }
