"""Extract/install each deliverable and exercise its actual frozen worker."""
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def smoke(executable):
    assert executable.is_file(), executable
    if sys.platform == 'win32':
        import pefile
        with pefile.PE(str(executable), fast_load=True) as pe:
            assert pe.OPTIONAL_HEADER.Subsystem == 2, 'Windows entry must use GUI subsystem (no console)'
    subprocess.run([sys.executable, 'packaging/smoke.py', str(executable)], check=True)


if sys.platform == 'win32':
    installer, = Path('dist').glob('*-setup.exe')
    portable, = Path('dist').glob('*-portable.zip')
    with tempfile.TemporaryDirectory(prefix='Only Voice package ') as directory:
        target = Path(directory) / 'Installed App'
        subprocess.run([str(installer.resolve()), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                        '/NORESTART', '/SP-', '/DIR=' + str(target)], check=True, timeout=180)
        smoke(target / 'OnlyVoice.exe')
        with zipfile.ZipFile(portable) as archive:
            archive.extractall(Path(directory) / 'portable')
        smoke(Path(directory) / 'portable/OnlyVoice/OnlyVoice.exe')
        subprocess.run([str(target / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                        '/NORESTART'], check=True, timeout=60)
else:
    for pattern in ('*.deb', '*.rpm', '*.pkg.tar.zst'):
        package, = Path('dist').glob(pattern)
        with tempfile.TemporaryDirectory(prefix='Only Voice package ') as directory:
            if package.suffix == '.deb':
                subprocess.run(['dpkg-deb', '-x', str(package), directory], check=True)
            else:
                subprocess.run(['bsdtar', '-xf', str(package), '-C', directory], check=True)
            root = Path(directory)
            assert (root / 'usr/share/applications/only-voice.desktop').is_file()
            assert (root / 'usr/share/icons/hicolor/scalable/apps/only-voice.svg').is_file()
            smoke(root / 'opt/only-voice/only-voice')
            print('Verified package:', package.name)
