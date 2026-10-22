"""Audio meter display timing, independent of GTK and the processing engine."""

import math

LEVEL_INTERVAL = 0.08


class MeterEnvelope:
    """Fast attack, gentle release; elapsed time keeps motion frame-rate independent."""

    def __init__(self):
        self.value = 0.0
        self.target = 0.0

    def set_db(self, decibels):
        self.target = max(0.0, min(60.0, decibels + 60.0)) if math.isfinite(decibels) else 0.0

    @property
    def moving(self):
        return self.value != self.target

    def advance(self, seconds):
        difference = self.target - self.value
        duration = 0.035 if difference > 0 else 0.16
        self.value += difference * -math.expm1(-max(0.0, seconds) / duration)
        if abs(self.target - self.value) < 0.025:
            self.value = self.target
        return self.value

    def reset(self):
        self.value = self.target = 0.0
