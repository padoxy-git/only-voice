import math
import unittest

from only_voice.metering import MeterEnvelope


class MeterTests(unittest.TestCase):
    def test_response_is_independent_of_display_refresh_rate(self):
        values = []
        for rate in (30, 60, 144):
            meter = MeterEnvelope()
            meter.set_db(-12)
            for _ in range(rate // 2):
                meter.advance(1 / rate)
            self.assertEqual(meter.value, 48)
            meter.set_db(-60)
            for _ in range(rate // 2):
                meter.advance(1 / rate)
            values.append(meter.value)
        for value in values[1:]:
            self.assertAlmostEqual(value, values[0], places=9)

    def test_attack_is_fast_release_is_gradual_and_silence_settles(self):
        meter = MeterEnvelope()
        meter.set_db(-10)
        attack = [meter.advance(1 / 60) for _ in range(6)]
        self.assertTrue(all(a < b for a, b in zip(attack, attack[1:])))
        self.assertGreater(attack[-1], 45)
        self.assertLess(attack[0], 50)
        meter.set_db(-60)
        self.assertGreater(meter.advance(0.1), 20)
        for _ in range(180):
            meter.advance(1 / 60)
        self.assertEqual(meter.value, 0)
        self.assertFalse(meter.moving)

    def test_invalid_and_out_of_range_levels_cannot_fill_the_bar(self):
        meter = MeterEnvelope()
        for value in (math.nan, math.inf, -math.inf, -180):
            meter.set_db(value)
            self.assertEqual(meter.target, 0)
        meter.set_db(20)
        self.assertEqual(meter.target, 60)
        meter.advance(0.01)
        meter.reset()
        self.assertEqual(meter.value, 0)
        self.assertFalse(meter.moving)
