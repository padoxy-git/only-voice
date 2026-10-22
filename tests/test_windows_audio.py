import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Exercise Windows routing without touching host hardware or requiring PortAudio.
with patch.dict(sys.modules, {'sounddevice': MagicMock()}):
    from only_voice import windows_audio as audio


class WindowsAudioTests(unittest.TestCase):
    def setUp(self):
        self.mock = patch.object(audio, 'sd').start()
        self.addCleanup(patch.stopall)
        self.mock.query_hostapis.return_value = [{'name': 'MME'}, {'name': 'Windows WASAPI'}]
        self.mock.query_devices.return_value = [
            dict(name='Mic', hostapi=0, max_input_channels=1, max_output_channels=0),
            dict(name='Mic', hostapi=1, max_input_channels=1, max_output_channels=0),
            dict(name='CABLE Output (VB-Audio Virtual Cable)', hostapi=1, max_input_channels=2, max_output_channels=0),
            dict(name='CABLE Input (VB-Audio Virtual Cable)', hostapi=1, max_input_channels=0, max_output_channels=2)]

    def test_discovers_only_physical_wasapi_inputs(self):
        self.assertEqual(audio.microphones(), [{'name': 'Mic', 'description': 'Mic'}])
        self.assertEqual(audio.resolve_source('Mic'), 'Mic')
        with self.assertRaisesRegex(RuntimeError, 'no está conectado'):
            audio.resolve_source('CABLE Output (VB-Audio Virtual Cable)')

    def test_routes_to_cable_input_and_call_uses_cable_output(self):
        with audio.Cable(16000) as cable:
            self.assertIn('CABLE Input', cable.sink)
            self.assertIn('CABLE Output', cable.source)
        self.mock.query_devices.return_value = []
        with self.assertRaisesRegex(RuntimeError, 'Instala VB-CABLE'):
            with audio.Cable(16000):
                pass

    def test_capture_playback_release_and_overflow_reset(self):
        with audio.AudioStream('Mic', 'CABLE Input (VB-Audio Virtual Cable)', 16000, 640) as stream:
            stream._capture(np.ones((640, 1), dtype=np.float32), 640, None,
                            type('Status', (), {'input_overflow': True})())
            sequence, frame = stream.read()
            self.assertEqual(sequence, 1)
            self.assertEqual(frame.shape, (640,))
            stream.write(frame)
            output = self.mock.OutputStream.return_value.__enter__.return_value
            self.assertEqual(output.write.call_args.args[0].shape, (640, 2))
            self.assertEqual(self.mock.InputStream.call_args.kwargs['device'], 1)
            self.assertEqual(self.mock.OutputStream.call_args.kwargs['device'], 3)
        self.mock.InputStream.return_value.__exit__.assert_called_once()
        self.mock.OutputStream.return_value.__exit__.assert_called_once()

    def test_open_failure_releases_playback(self):
        self.mock.InputStream.side_effect = RuntimeError('unplugged')
        with self.assertRaisesRegex(RuntimeError, 'unplugged'):
            with audio.AudioStream('Mic', 'CABLE Input (VB-Audio Virtual Cable)', 16000, 640):
                pass
        self.mock.OutputStream.return_value.__exit__.assert_called_once()
