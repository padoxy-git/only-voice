from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from only_voice.audio import record_reference
from only_voice.cli import main


class EnrollmentTests(unittest.TestCase):
    def test_recording_has_exact_duration_and_pcm_format(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            executable = location / "parec"
            executable.write_text(
                f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write(b'\\x10\\x00' * 80000)\n"
            )
            executable.chmod(0o700)
            destination = location / "reference.wav"
            events = []
            with patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ.get("PATH", "")}):
                with patch("only_voice.audio.resolve_source", return_value="test_input"):
                    with patch("only_voice.audio.time.sleep"), redirect_stderr(io.StringIO()):
                        record_reference(destination, seconds=5, on_event=lambda phase, **values: events.append((phase, values)))
            self.assertEqual([phase for phase, _ in events[:3]], ["countdown"] * 3)
            self.assertEqual(events[-1][1]["progress"], 1.0)
            with wave.open(str(destination), "rb") as recording:
                self.assertEqual(recording.getframerate(), 16000)
                self.assertEqual(recording.getnchannels(), 1)
                self.assertEqual(recording.getsampwidth(), 2)
                self.assertEqual(recording.getnframes(), 80000)
                self.assertEqual(recording.readframes(80000), b"\x10\x00" * 80000)

    def test_early_capture_failure_leaves_no_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            executable = location / "parec"
            executable.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write(b'xx')\n")
            executable.chmod(0o700)
            destination = location / "reference.wav"
            with patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ.get("PATH", "")}):
                with patch("only_voice.audio.resolve_source", return_value="test_input"):
                    with patch("only_voice.audio.time.sleep"), redirect_stderr(io.StringIO()):
                        with self.assertRaisesRegex(RuntimeError, "interrumpió"):
                            record_reference(destination, seconds=5)
            self.assertFalse(destination.exists())

    def test_recording_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "existing.wav"
            destination.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                record_reference(destination)
            self.assertEqual(destination.read_bytes(), b"original")

    @patch("only_voice.cli.enroll", side_effect=RuntimeError("encoder failed"))
    @patch("only_voice.cli.record_reference")
    def test_cli_deletes_temporary_reference_when_encoder_fails(self, record, encode):
        def capture(destination, *_):
            destination.write_bytes(b"temporary audio")
        record.side_effect = capture
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            original_handler = signal.getsignal(signal.SIGTERM)
            with redirect_stderr(io.StringIO()):
                result = main(["enroll", "--record", "--profile", str(profile)])
            self.assertEqual(result, 1)
            reference = encode.call_args.args[0]
            self.assertFalse(reference.exists())
            self.assertFalse(reference.parent.exists())
            self.assertFalse(profile.exists())
            self.assertEqual(signal.getsignal(signal.SIGTERM), original_handler)

    @patch("only_voice.cli.enroll")
    @patch("only_voice.cli.record_reference", side_effect=KeyboardInterrupt)
    def test_cli_interrupt_does_not_attempt_enrollment(self, record, encode):
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stderr(io.StringIO()):
                result = main(["enroll", "--record", "--profile", str(Path(directory) / "p.json")])
            self.assertEqual(result, 0)
            reference = record.call_args.args[0]
            self.assertFalse(reference.parent.exists())
            encode.assert_not_called()
