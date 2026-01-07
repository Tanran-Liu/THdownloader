# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['simple_downloader.py'],
    pathex=[],
    binaries=[],
    datas=[('config', 'config'), ('download', 'download'), ('.venv/Lib/site-packages/mysql', 'mysql'), ('.venv/Lib/site-packages/ttkthemes', 'ttkthemes')],
    hiddenimports=['config', 'config.config', 'download', 'download.async_downloader', 'download.db', 'tkinter.font', 'tkinter.scrolledtext', 'mysql.connector', 'mysql.connector.errorcode', 'mysql.connector.errors', 'oss2', 'oss2.auth', 'oss2.api', 'oss2.models', 'oss2.exceptions', 'oss2.utils', 'oss2.http', 'oss2.compat', 'oss2.iterators', 'pandas', 'pandas._libs.tslibs', 'pandas.io.formats.style', 'openpyxl', 'openpyxl.workbook', 'openpyxl.worksheet', 'PIL', 'PIL._imaging', 'PIL.Image', 'PIL.ImageTk', 'ttkthemes', 'cryptography.hazmat.backends.openssl', 'dateutil.parser', 'dateutil.tz'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['_mysql_connector', 'matplotlib', 'scipy', 'IPython', 'jupyter', 'notebook', 'pytest', 'test', 'tests', 'unittest'],
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
    name='Tashigang Data Downloader',
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
