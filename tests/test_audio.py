import io
import queue
import unittest
from unittest.mock import patch

import numpy as np

from only_voice.audio import VirtualMicrophone, put_latest, read_exact, resolve_source, run_stream


class PartialStream:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def read(self, size):
        return self.stream.read(min(size, 3))


class AudioTests(unittest.TestCase):
    @patch("only_voice.audio.AudioStream")
    @patch("only_voice.audio.VirtualMicrophone")
    @patch("only_voice.audio.resolve_source", return_value="physical_mic")
    def test_meters_include_audio_between_updates_and_publish_more_than_twice_per_second(self, _, virtual, audio):
        clock = [1000.0]
        frames = iter(enumerate(np.full(640, value, dtype=np.float32) for value in (1.0, 0.0, 0.5)))
        def read():
            try:
                block = next(frames)
            except StopIteration:
                raise KeyboardInterrupt
            clock[0] += 0.041
            return block
        audio.return_value.__enter__.return_value.read.side_effect = read
        class Processor:
            rate, frame_size = 16000, 640
            def process(self, value):
                return value * 0.5
            def reset(self):
                pass
        events = []
        with patch("only_voice.audio.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(KeyboardInterrupt):
                run_stream(Processor(), on_event=lambda phase, **values: events.append(values))
        self.assertEqual(len(events), 2)
        self.assertAlmostEqual(events[1]["input_db"], 10 * np.log10(0.125), places=5)
        self.assertAlmostEqual(events[1]["output_db"], 10 * np.log10(0.125 / 4), places=5)

    def test_reads_full_frame_across_partial_pipe_reads(self):
        stream = PartialStream(b"0123456789")
        self.assertEqual(read_exact(stream, 10), b"0123456789")
        self.assertIsNone(read_exact(stream, 10))
        with self.assertRaises(RuntimeError):
            read_exact(PartialStream(b"short"), 10)

    def test_queue_retains_recent_audio_and_remains_bounded(self):
        frames = queue.Queue(maxsize=3)
        for sequence in range(100):
            put_latest(frames, sequence)
        self.assertEqual(frames.qsize(), 3)
        self.assertEqual([frames.get_nowait() for _ in range(3)], [97, 98, 99])

    @patch("only_voice.audio.pactl")
    def test_cleanup_rolls_back_partial_creation(self, command):
        command.side_effect = ["101", RuntimeError("remap failed"), ""]
        with self.assertRaisesRegex(RuntimeError, "remap failed"):
            with VirtualMicrophone():
                self.fail("No debe llegar a crear ambos módulos.")
        self.assertEqual(command.call_args.args, ("unload-module", "101"))

    @patch("only_voice.audio.pactl")
    def test_cleanup_only_unloads_owned_modules_in_reverse_order(self, command):
        command.side_effect = ["101", "102", "", ""]
        with self.assertRaisesRegex(ValueError, "processing failed"):
            with VirtualMicrophone():
                raise ValueError("processing failed")
        self.assertEqual([call.args for call in command.call_args_list[-2:]],
                         [("unload-module", "102"), ("unload-module", "101")])

    @patch("only_voice.audio.sources")
    @patch("only_voice.audio.pactl")
    def test_default_virtual_or_monitor_input_is_rejected(self, command, available):
        available.return_value = [{"name": "only_voice_abc_mic"}, {"name": "output.monitor"},
                                  {"name": "physical_mic"}]
        for name in ("only_voice_abc_mic", "output.monitor"):
            command.return_value = name
            with self.assertRaises(ValueError):
                resolve_source()
        self.assertEqual(resolve_source("physical_mic"), "physical_mic")

    @patch("only_voice.audio.AudioStream")
    @patch("only_voice.audio.VirtualMicrophone")
    @patch("only_voice.audio.resolve_source", return_value="physical_mic")
    def test_discontinuity_resets_state_and_keyboard_interrupt_cleans_up(self, _, virtual, audio):
        frame = np.zeros(480, dtype=np.float32)
        stream = audio.return_value.__enter__.return_value
        stream.read.side_effect = [(0, frame), (4, frame), KeyboardInterrupt]
        class Processor:
            def __init__(self):
                self.resets = 0

            def process(self, value):
                return value

            def reset(self):
                self.resets += 1

        processor = Processor()
        with self.assertRaises(KeyboardInterrupt):
            run_stream(processor)
        self.assertEqual(processor.resets, 2)  # warm-up, then the sequence gap
        self.assertEqual(stream.write.call_count, 2)
        audio.return_value.__exit__.assert_called_once()
        virtual.return_value.__exit__.assert_called_once()
