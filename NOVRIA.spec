# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

_datas = [('assets','assets')]
_binaries = []
_hidden = []
for pkg in ['demucs', 'torch', 'torchaudio', 'soundfile', 'sounddevice', 'librosa', 'scipy', 'mido', 'mutagen']:
    try:
        d, b, h = collect_all(pkg)
        _datas += d
        _binaries += b
        _hidden += h
    except Exception:
        pass

_hidden += collect_submodules('demucs')
_common_hidden = _hidden + [
    'numpy', 'soundfile', 'sounddevice', 'librosa', 'scipy', 'mido', 'mutagen',
    'demucs.separate', 'demucs.pretrained', 'demucs.apply', 'demucs.api',
]

analysis = Analysis(
    ['app/launcher.py'],
    pathex=['.'],
    binaries=_binaries,
    datas=_datas + [('config', 'config')],
    hiddenimports=_common_hidden + ['app.main'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name='NOVRIA-AI-Music-Studio', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None,
)

worker_analysis = Analysis(
    ['app/separation_worker_process.py'],
    pathex=['.'],
    binaries=_binaries,
    datas=[],
    hiddenimports=_common_hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
worker_pyz = PYZ(worker_analysis.pure)
worker_exe = EXE(
    worker_pyz, worker_analysis.scripts, [], exclude_binaries=True,
    name='NOVRIA-Separation-Worker', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None,
)

coll = COLLECT(
    exe, worker_exe,
    analysis.binaries, analysis.datas,
    worker_analysis.binaries, worker_analysis.datas,
    strip=False, upx=False, upx_exclude=[],
    name='NOVRIA-AI-Music-Studio',
)
