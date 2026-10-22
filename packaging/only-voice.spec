from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

root = Path(SPECPATH).parent
windows = sys.platform == 'win32'
library = 'rnnoise.dll' if windows else 'librnnoise.so.0'
datas = [(str(root / 'build/native/RNNoise-LICENSE.txt'), 'licenses')]
binaries = [(str(root / 'build/native' / library), '.')]
hidden = ['only_voice.worker', 'only_voice.windows_audio' if windows else 'only_voice.audio']
for package in ('voxlock', 'onnxruntime', 'soxr', 'soundfile'):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hidden += imports
datas += collect_data_files('huggingface_hub')
# Preserve third-party redistribution notices, including Qt's LGPL texts.
import importlib.metadata
for distribution in importlib.metadata.distributions():
    for item in distribution.files or []:
        if any(word in str(item).lower() for word in ('license', 'copying', 'notice')):
            path = distribution.locate_file(item)
            if path.is_file():
                datas.append((str(path), 'licenses/' + distribution.metadata['Name']))
a = Analysis([str(root / 'packaging/entry.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['tkinter', 'gi', 'torch', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'IPython'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='OnlyVoice' if windows else 'only-voice',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='OnlyVoice' if windows else 'only-voice')
