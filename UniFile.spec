# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('unifile', 'unifile')],
    hiddenimports=['unifile.bootstrap', 'unifile.config', 'unifile.main_window', 'unifile.tagging.db', 'unifile.tagging.models', 'unifile.tagging.library', 'unifile.dialogs.tag_library', 'unifile.dialogs.media_lookup', 'unifile.dialogs.cleanup', 'unifile.dialogs.duplicates', 'unifile.dialogs.editors', 'unifile.dialogs.settings', 'unifile.dialogs.theme', 'unifile.dialogs.tools', 'unifile.dialogs.advanced_settings', 'unifile.dialogs.settings_hub', 'unifile.media.providers', 'unifile.nexa_backend', 'unifile.scan_mixin', 'unifile.apply_mixin', 'unifile.theme_mixin', 'unifile.undo_mixin', 'unifile.filter_mixin', 'unifile.tray_mixin', 'unifile.watch_mixin', 'unifile.dialogs_mixin', 'unifile.workers', 'unifile.widgets', 'unifile.ui_helpers', 'unifile.classifier', 'unifile.categories', 'unifile.engine', 'unifile.naming', 'unifile.metadata', 'unifile.ollama', 'unifile.photos', 'unifile.files', 'unifile.cache', 'unifile.models', 'unifile.plugins', 'unifile.profiles', 'unifile.cleanup', 'unifile.duplicates', 'unifile.semantic', 'unifile.embedding', 'sqlalchemy.dialects.sqlite'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
