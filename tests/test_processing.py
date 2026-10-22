import ctypes.util
import unittest

import numpy as np

from only_voice.processing import FRAME_SIZE, RNNoise, frame_array


class ProcessingTests(unittest.TestCase):
    def test_frames_reject_nan_and_wrong_shape(self):
        for bad in (np.zeros(479), np.zeros((1, 480)), np.full(480, np.nan)):
            with self.assertRaises(ValueError):
                frame_array(bad)

    @unittest.skipUnless(ctypes.util.find_library("rnnoise"), "RNNoise no instalado")
    def test_native_rnnoise_suppresses_stationary_noise_and_resets(self):
        processor = RNNoise()
        try:
            rng = np.random.default_rng(42)
            noise = (rng.standard_normal((200, FRAME_SIZE)) * 0.04).astype(np.float32)
            clean = np.stack([processor.process(frame) for frame in noise])
            self.assertTrue(np.isfinite(clean).all())
            self.assertLess(np.sqrt(np.mean(clean[50:]**2)), np.sqrt(np.mean(noise[50:]**2)))
            processor.reset()
            first = processor.process(noise[0])
            processor.reset()
            np.testing.assert_array_equal(first, processor.process(noise[0]))
        finally:
            processor.close()
            processor.close()
        with self.assertRaises(RuntimeError):
            processor.process(noise[0])
