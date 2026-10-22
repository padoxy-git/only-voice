"""Create a pacman package from the same frozen bundle as deb/rpm."""
from pathlib import Path
import os
import shutil
import subprocess
import time

version = os.environ['VERSION']
stage = Path('build/arch')
stage.mkdir(parents=True, exist_ok=True)
shutil.copytree('dist/only-voice', stage / 'opt/only-voice', dirs_exist_ok=True)
for src, dst in [('packaging/only-voice.desktop', 'usr/share/applications/only-voice.desktop'),
                 ('assets/only-voice.svg', 'usr/share/icons/hicolor/scalable/apps/only-voice.svg')]:
    target = stage / dst
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, target)
size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
depends = ['glibc', 'gcc-libs', 'pulseaudio', 'libglvnd', 'libxkbcommon', 'libxkbcommon-x11',
           'xcb-util-cursor', 'xcb-util-wm', 'xcb-util-keysyms', 'xcb-util-image', 'xcb-util-renderutil']
(stage / '.PKGINFO').write_text(f'pkgname = only-voice\npkgbase = only-voice\npkgver = {version}-1\n'
    f'pkgdesc = Micrófono virtual controlado desde la bandeja del sistema\n'
    f'url = https://github.com/padoxy-git/only-voice\nbuilddate = {int(time.time())}\n'
    f'packager = Pablo Dorado\nsize = {size}\narch = x86_64\n' + ''.join(f'depend = {d}\n' for d in depends))
output = Path(f'dist/only-voice-{version}-1-x86_64.pkg.tar.zst').resolve()
subprocess.run(['bsdtar', '--zstd', '-cf', str(output), '--uid', '0', '--gid', '0', '-C', str(stage), '.PKGINFO', 'opt', 'usr'], check=True)
print(output)
