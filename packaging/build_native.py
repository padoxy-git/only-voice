"""Build a pinned RNNoise library for the frozen application (BSD license)."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

REVISION = '2cb77862b17c43eb78e4ed0531763f3e7854e49b'
root = Path('build/native').resolve()
root.mkdir(parents=True, exist_ok=True)
archive = root / 'rnnoise.tar.gz'
urllib.request.urlretrieve(f'https://codeload.github.com/xiph/rnnoise/tar.gz/{REVISION}', archive)
with tarfile.open(archive) as tar:
    tar.extractall(root, filter='data')
source = root / f'rnnoise-{REVISION}'
# v0.1's stable frame size is not exposed by an accessor until later releases.
(source / 'src/frame_size.c').write_text('#include "rnnoise.h"\nRNNOISE_EXPORT int rnnoise_get_frame_size(void) { return 480; }\n')
windows = sys.platform == 'win32'
compiler = os.environ.get('RNNOISE_CC', 'gcc')
if windows:
    # GCC's child tools need the MinGW runtime DLLs on PATH as well.
    os.environ['PATH'] = str(Path(compiler).parent) + os.pathsep + os.environ['PATH']
subprocess.run([compiler, '--version'], check=True)
library = root / ('rnnoise.dll' if windows else 'librnnoise.so.0')
files = ['denoise', 'rnn', 'rnn_data', 'pitch', 'kiss_fft', 'celt_lpc', 'frame_size']
subprocess.run([compiler, '-shared', '-O3', '-DRNNOISE_BUILD',
                *(['-DWIN32', '-DDLL_EXPORT', '-static-libgcc'] if windows else ['-fPIC', '-Wl,-soname,librnnoise.so.0']),
                '-I' + str(source / 'include'), '-I' + str(source / 'src'),
                *[str(source / f'src/{name}.c') for name in files], '-lm', '-o', str(library)], check=True)
if not windows:
    (root / 'librnnoise.so').unlink(missing_ok=True)
    (root / 'librnnoise.so').symlink_to(library.name)
shutil.copy(source / 'COPYING', root / 'RNNoise-LICENSE.txt')
print(library)
