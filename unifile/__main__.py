"""UniFile — Application entry point."""
import os, sys, time
from datetime import datetime
from pathlib import Path
from PyQt6.QtGui import QIcon


# codex-branding:start
def _branding_icon_path() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "icon.png")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "icon.png")
    current = Path(__file__).resolve()
    candidates.extend([current.parent / "icon.png", current.parent.parent / "icon.png", current.parent.parent.parent / "icon.png"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("icon.png")
# codex-branding:end


def main():
    """Launch the UniFile application."""
    # Crash handler
    from unifile.config import _APP_DATA_DIR

    _CRASH_LOG = os.path.join(_APP_DATA_DIR, 'crash.log')
    _CRASH_LOG_MAX = 512 * 1024  # 500 KB

    def _rotate_crash_log():
        try:
            if os.path.exists(_CRASH_LOG) and os.path.getsize(_CRASH_LOG) > _CRASH_LOG_MAX:
                rotated = _CRASH_LOG + '.1'
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(_CRASH_LOG, rotated)
        except OSError:
            pass

    def _crash_handler(exc_type, exc_value, exc_tb):
        import traceback as _tb
        lines = _tb.format_exception(exc_type, exc_value, exc_tb)
        crash_text = ''.join(lines)
        timestamp = datetime.now().isoformat()
        entry = f"\n{'='*60}\n[{timestamp}] Unhandled {exc_type.__name__}\n{crash_text}"
        try:
            _rotate_crash_log()
            with open(_CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write(entry)
        except OSError:
            pass
        from PyQt6.QtWidgets import QApplication, QMessageBox
        qapp = QApplication.instance()
        if qapp:
            QMessageBox.critical(None, "UniFile — Crash",
                f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}\n\n"
                f"Details saved to:\n{_CRASH_LOG}")
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    import argparse
    sys.excepthook = _crash_handler

    parser = argparse.ArgumentParser(description="UniFile — Context-Aware File Organizer")
    parser.add_argument("--source", type=str, default=None,
                        help="Source folder to auto-scan (used by shell integration)")
    parser.add_argument("--profile", type=str, default=None,
                        help="Load a named profile for scheduled/automated scans")
    parser.add_argument("--auto-apply", action="store_true",
                        help="Automatically apply after scan (for scheduled tasks)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate apply without moving/renaming files")
    args, qt_args = parser.parse_known_args()

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    from unifile.config import get_active_stylesheet
    from unifile.main_window import UniFile
    from unifile.plugins import ProfileManager

    app = QApplication(qt_args)

    branding_icon = QIcon(str(_branding_icon_path()))

    app.setWindowIcon(branding_icon)
    app.setStyle("Fusion")
    app.setStyleSheet(get_active_stylesheet())
    window = UniFile()
    window._cli_dry_run = args.dry_run

    if args.profile:
        try:
            profile = ProfileManager.load(args.profile)
            if profile:
                # Profile is a scan-config dict; main window expects
                # _apply_profile_config, not _apply_profile.
                apply_cfg = getattr(window, '_apply_profile_config', None)
                if apply_cfg is None:
                    apply_cfg = getattr(window, '_apply_profile', None)
                if apply_cfg is not None:
                    apply_cfg(profile)
                    window._log(f"Loaded profile: {args.profile}")
                else:
                    window._log(f"Profile loader unavailable — ignoring '{args.profile}'")
        except FileNotFoundError:
            window._log(f"Profile not found: {args.profile}")
        except Exception as e:
            window._log(f"Failed to load profile '{args.profile}': {e}")
    window.show()

    if args.source and os.path.isdir(args.source):
        window.cmb_op.setCurrentIndex(UniFile.OP_FILES)
        window.cmb_pc_src.setCurrentText(args.source)
        if hasattr(window, 'txt_pc_src'):
            window.txt_pc_src.setText(args.source)
        QTimer.singleShot(200, window._on_scan)
    elif args.profile and args.auto_apply:
        def _auto_scan_apply():
            window._on_scan()
            _deadline = [time.time() + 30 * 60]  # 30-minute safety ceiling
            def _check_and_apply():
                # Bail out if scan has exceeded deadline (prevents infinite polling on stuck scans)
                if time.time() > _deadline[0]:
                    window._log("Auto-apply aborted: scan exceeded 30 minute deadline")
                    return
                scan_worker = getattr(window, 'worker', None)
                still_scanning = (
                    getattr(window, '_scanning', False)
                    or (scan_worker is not None and scan_worker.isRunning())
                )
                if not still_scanning:
                    # Route to the correct apply based on the active op mode
                    op_idx = window.cmb_op.currentIndex()
                    if op_idx == UniFile.OP_FILES:
                        window._apply_files(dry_run=args.dry_run)
                    elif op_idx in (UniFile.OP_CAT, UniFile.OP_SMART):
                        window._apply_cat()
                    else:
                        window._apply_aep(dry_run=args.dry_run)
                else:
                    QTimer.singleShot(500, _check_and_apply)
            QTimer.singleShot(1000, _check_and_apply)
        QTimer.singleShot(200, _auto_scan_apply)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
