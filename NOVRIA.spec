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

analysis = Analysis(
    ['app/launcher.py'],
    pathex=['.'],
    binaries=_binaries,
    datas=_datas + [('config', 'config')],
    hiddenimports=_hidden + [
        'app.main', 'numpy', 'soundfile', 'sounddevice', 'librosa', 'scipy', 'mido', 'mutagen',
        'demucs.separate', 'demucs.pretrained', 'demucs.apply',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name='NOVRIA-AI-Music-Studio', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(
    exe, analysis.binaries, analysis.datas, strip=False, upx=False, upx_exclude=[],
    name='NOVRIA-AI-Music-Studio',
)
