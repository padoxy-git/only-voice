import ctypes.util
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from only_voice.application import Application, Paths
from only_voice.desktop_backend import DesktopBackend, microphones
from test_cli_integration import FAKE_AUDIO_TOOL


class DesktopBackendTests(unittest.TestCase):
    def test_slow_status_and_actions_never_block_the_gui_reader(self):
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            app = Application(Paths(Path(directory)))
            def slow_status():
                entered.set()
                release.wait(3)
                return {'active': False, 'phase': 'stopped'}
            with patch.object(app, 'status', side_effect=slow_status):
                backend = DesktopBackend(app)
                try:
                    self.assertTrue(entered.wait(1))
                    started = time.monotonic()
                    for _ in range(1000):
                        self.assertIsNone(backend.take_update())
                    self.assertLess(time.monotonic() - started, 0.1)
                    backend.submit('devices', lambda: [{'name': 'physical_mic'}])
                    kind, devices, error = backend.events.get(timeout=1)
                    self.assertEqual((kind, devices, error), ('devices', [{'name': 'physical_mic'}], None))
                finally:
                    backend.close()
                    release.set()
                    backend._poll_thread.join(timeout=1)

    def test_device_discovery_excludes_monitors_and_our_virtual_source(self):
        with patch('only_voice.desktop_backend.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps([{'name': 'headphones.monitor'},
                                                  {'name': 'only_voice_abc_mic'},
                                                  {'name': 'physical_mic', 'description': 'Mi micrófono'}])
            self.assertEqual(microphones(), [{'name': 'physical_mic', 'description': 'Mi micrófono'}])
            self.assertEqual(run.call_args.args[0], ['pactl', '--format=json', 'list', 'sources'])

    def test_failed_action_reports_error_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = DesktopBackend(Application(Paths(Path(directory))))
            try:
                def fail():
                    raise RuntimeError('No hay micrófono')
                backend.submit('job', fail)
                self.assertEqual(backend.events.get(timeout=1), ('job', None, 'No hay micrófono'))
                backend.submit('job', lambda: 'OK')
                self.assertEqual(backend.events.get(timeout=1), ('job', 'OK', None))
            finally:
                backend.close()
                backend._poll_thread.join(timeout=1)

    @unittest.skipUnless(ctypes.util.find_library('rnnoise'), 'RNNoise no instalado')
    def test_background_controls_start_and_stop_real_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / 'bin'
            binaries.mkdir()
            for command in ('pactl', 'parec', 'pacat'):
                executable = binaries / command
                executable.write_text(f'#!{sys.executable}\n' + FAKE_AUDIO_TOOL)
                executable.chmod(0o700)
            app = Application(Paths(root / 'app'))
            with patch.dict(os.environ, {'PATH': str(binaries) + os.pathsep + os.environ.get('PATH', ''),
                                        'ONLY_VOICE_TEST_DIRECTORY': directory}):
                backend = DesktopBackend(app, interval=0.02)
                try:
                    backend.submit('job', lambda: app.start('fake_input', 'noise'))
                    self.assertIsNone(backend.events.get(timeout=5)[2], app.details())
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        snapshot = backend.take_update()
                        if snapshot and snapshot['state'].get('phase') == 'running':
                            break
                        time.sleep(0.01)
                    else:
                        self.fail(app.details())
                    self.assertIn('output_db', snapshot['state'])
                    backend.submit('job', app.stop)
                    _, state, error = backend.events.get(timeout=5)
                    self.assertIsNone(error)
                    self.assertFalse(state['active'])
                    self.assertEqual(app.settings()['source'], 'fake_input')
                finally:
                    backend.close()
                    backend._poll_thread.join(timeout=1)
                    app.stop()
            commands = [json.loads(line) for line in (root / 'commands.jsonl').read_text().splitlines()]
            self.assertEqual(commands[-2:], [['unload-module', '102'], ['unload-module', '101']])
