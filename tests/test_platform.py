import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from only_voice.application import Application, Paths, data_root, is_worker, lock, process_identity, read_json
from only_voice import worker


class PlatformTests(unittest.TestCase):
    def test_data_is_stored_in_user_directory_or_explicit_override(self):
        with patch.dict(os.environ, {'ONLY_VOICE_DATA': '/tmp/custom-only-voice'}):
            self.assertEqual(Paths().root, Path('/tmp/custom-only-voice').resolve())
        with patch('only_voice.application.WINDOWS', True), patch.dict(os.environ, {'LOCALAPPDATA': '/tmp/user'}):
            os.environ.pop('ONLY_VOICE_DATA', None)
            self.assertEqual(data_root(), Path('/tmp/user/Only Voice'))

    def test_lock_excludes_a_second_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lock'
            with lock(path):
                child = subprocess.run([sys.executable, '-c',
                    'from only_voice.application import lock; import sys\n'
                    'try:\n with lock(sys.argv[1], blocking=False): pass\n'
                    'except BlockingIOError: sys.exit(7)', str(path)], capture_output=True)
                self.assertEqual(child.returncode, 7, child.stderr)
            with lock(path, blocking=False):
                pass

    def test_own_pid_is_not_mistaken_for_worker(self):
        self.assertIsNotNone(process_identity(os.getpid()))
        self.assertFalse(is_worker({'pid': os.getpid(), 'identity': process_identity(os.getpid())}, Paths()))

    def test_cooperative_stop_preserves_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            paths.runtime.mkdir()
            paths.file('stop').touch()
            with patch('only_voice.worker.ensure_model') as ensure:
                self.assertEqual(worker.main(['--project', directory, '--task', 'profile']), 0)
                ensure.assert_not_called()
            self.assertEqual(read_json(paths.file('state.json'))['phase'], 'stopped')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process lifecycle')
    def test_real_windows_worker_identity_singleton_and_cooperative_cleanup(self):
        from only_voice.application import wait_ready
        with tempfile.TemporaryDirectory(prefix='Only Voice Windows ') as directory:
            paths = Paths(Path(directory) / 'data')
            app, second = Application(paths), Application(paths)
            env = {'PYTHONPATH': str(Path(__file__).parent / 'fakes'),
                   'ONLY_VOICE_TEST_DIRECTORY': directory}
            with patch.dict(os.environ, env):
                try:
                    app.start(source='Test Mic', mode='noise')
                    state = wait_ready(app, timeout=15)
                    self.assertTrue(state['active'], app.details())
                    self.assertEqual(state['phase'], 'running', app.details())
                    self.assertEqual(second.start()['pid'], state['pid'])
                    with self.assertRaises(RuntimeError):
                        second.register()
                    self.assertGreater((Path(directory) / 'output.raw').stat().st_size, 0)
                    self.assertFalse(second.stop()['active'])
                    self.assertEqual(app.status()['phase'], 'stopped')
                    self.assertTrue((Path(directory) / 'capture-closed').is_file())
                    self.assertTrue((Path(directory) / 'playback-closed').is_file())
                finally:
                    app.stop()
