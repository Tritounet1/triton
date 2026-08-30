# -*- mode: python ; coding: utf-8 -*-

# Freezes server.py (the FastAPI/uvicorn entry point) into a single
# standalone executable, so the desktop app can run it as a Tauri sidecar
# with no Python/uv install required on the target machine. Built and
# renamed to Tauri's <name>-<target-triple> sidecar convention by
# packaging/build_server.sh - run that script rather than calling
# `pyinstaller` on this spec directly. See PLAN.md for the full picture
# (ROOT_DIR's frozen-mode branch in src/triton/paths.py, the .env lookup
# in src/triton/llm/api.py) and what's still missing for a real Windows build.

a = Analysis(
    ['../server.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name='triton-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
