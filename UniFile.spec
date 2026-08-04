# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

_face_data = []
try:
    _face_data = collect_data_files('face_recognition_models')
except Exception:
    pass

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('unifile', 'unifile')] + _face_data,
    hiddenimports=['unifile.bootstrap', 'unifile.watch_jobs', 'unifile.config', 'unifile.main_window', 'unifile.tagging.db', 'unifile.tagging.models', 'unifile.tagging.library', 'unifile.dialogs.tag_library', 'unifile.dialogs.media_lookup', 'unifile.dialogs.cleanup', 'unifile.dialogs.duplicates', 'unifile.dialogs.editors', 'unifile.dialogs.settings', 'unifile.dialogs.theme', 'unifile.dialogs.tools', 'unifile.dialogs.advanced_settings', 'unifile.dialogs.settings_hub', 'unifile.diagnostics', 'unifile.media.providers', 'unifile.nexa_backend', 'unifile.scan_mixin', 'unifile.script', 'unifile.plugin_manifest', 'yaml', 'unifile.apply_mixin', 'unifile.theme_mixin', 'unifile.undo_mixin', 'unifile.filter_mixin', 'unifile.tray_mixin', 'unifile.watch_mixin', 'unifile.dialogs_mixin', 'unifile.workers', 'unifile.widgets', 'unifile.ui_helpers', 'unifile.classifier', 'unifile.categories', 'unifile.engine', 'unifile.naming', 'unifile.metadata', 'unifile.ollama', 'unifile.photos', 'unifile.files', 'unifile.cache', 'unifile.models', 'unifile.plugins', 'unifile.profiles', 'unifile.cleanup', 'unifile.duplicates', 'unifile.semantic', 'unifile.embedding_backends', 'unifile.clip_duplicates', 'unifile.embedding', 'sqlalchemy.dialects.sqlite'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['unifile/pyinstaller_runtime.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='UniFile',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    icon='icon.ico',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='UniFile',
)
