"""UniFile — Application entry point."""
import os, sys
from datetime import datetime


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
    app.setStyle("Fusion")
    app.setStyleSheet(get_active_stylesheet())
    window = UniFile()
    window._cli_dry_run = args.dry_run

    if args.profile:
        try:
            profile = ProfileManager.load(args.profile)
            if profile:
                window._apply_profile(profile)
                window._log(f"Loaded profile: {args.profile}")
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
            def _check_and_apply():
                if not hasattr(window, '_scan_worker') or window._scan_worker is None:
                    window._apply_files(dry_run=args.dry_run)
                else:
                    QTimer.singleShot(500, _check_and_apply)
            QTimer.singleShot(1000, _check_and_apply)
        QTimer.singleShot(200, _auto_scan_apply)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
