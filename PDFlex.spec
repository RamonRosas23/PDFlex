# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = []

for pkg in ('pymupdf', 'PIL', 'PyQt6', 'docx', 'numpy', 'requests'):
    tmp = collect_all(pkg)
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# win32com para conversión Word→PDF
hiddenimports += ['win32com.client', 'win32com.gen_py', 'pythoncom', 'pywintypes']

# requests: dependencias SSL implícitas
hiddenimports += [
    'certifi', 'urllib3', 'urllib3.util.ssl_',
    'charset_normalizer', 'idna',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ── UPX: excluir todas las DLLs de Qt6 y PyMuPDF ───────────────────
# UPX puede corromper Qt6 y causar crash al arrancar.
UPX_EXCLUDE = [
    "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Network.dll",
    "Qt6OpenGL.dll", "Qt6Svg.dll", "Qt6PrintSupport.dll",
    "qwindows.dll", "qwindowsvistastyle.dll",
    "mupdf*.dll", "fitz*.pyd",
    "python3*.dll", "vcruntime*.dll", "msvcp*.dll",
]

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDFlex',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=UPX_EXCLUDE,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)
