# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\monitoring_tool-main\\monitoring_tool\\agent\\sentinel_helper.py'],
    pathex=['D:\\monitoring_tool-main\\monitoring_tool\\agent'],
    binaries=[],
    datas=[],
    hiddenimports=['json', 'hashlib', 'hmac', 'logging', 'pathlib', 'ctypes', 'ctypes.wintypes', 'threading', 'enum', 'psutil', 'requests', 'urllib3', 'pytz', 'win32api', 'win32con', 'win32gui', 'win32security', 'win32process', 'win32event', 'win32ts', 'win32service', 'win32serviceutil', 'servicemanager', 'pywintypes', 'winerror', 'logger', 'core', 'core.service', 'core.config', 'core.config_schema', 'core.ingest', 'core.buffer', 'core.uploader', 'core.aggregator', 'core.state_machine', 'core.live_telemetry', 'core.integrity', 'core.secure_store', 'core.updater', 'helper', 'helper.main', 'helper.collector', 'helper.comm', 'helper.config', 'helper.idle', 'helper.window', 'helper.domain', 'helper.inventory', 'helper.extended_inventory', 'helper.eol_collector', 'helper.hardware_collector', 'helper.security', 'helper.security_collector', 'helper.performance', 'helper.persistence', 'helper.state_detector', 'helper.state_detector_spans', 'helper.identity_sync', 'helper.app_names'],
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
    a.binaries,
    a.datas,
    [],
    name='syshealth',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
