"""Exercise real child-process I/O with a simulated audio server, never a mic."""

import ctypes.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np

from only_voice.voice import MODEL_REVISION
from only_voice.variants import PRECISIONS, model_files


FAKE_AUDIO_TOOL = r'''
import json
import math
import os
from pathlib import Path
import struct
import sys
import time

directory = Path(os.environ["ONLY_VOICE_TEST_DIRECTORY"])
command = Path(sys.argv[0]).name
arguments = sys.argv[1:]
if command == "pactl":
    with (directory / "commands.jsonl").open("a") as log:
        log.write(json.dumps(arguments) + "\n")
    if arguments == ["get-default-source"]:
        print("fake_input")
    elif arguments == ["--format=json", "list", "sources"]:
        print(json.dumps([{"name": "fake_input", "description": "Simulated input"}]))
    elif arguments[0] == "load-module":
        print("101" if arguments[1] == "module-null-sink" else "102")
    elif arguments[0] != "unload-module":
        raise SystemExit(2)
elif command == "parec":
    rate = int(next(arg.split("=", 1)[1] for arg in arguments if arg.startswith("--rate=")))
    duration = 0.04 if rate == 16000 else 0.01
    size = int(rate * duration)
    frame = struct.pack(f"<{size}f", *[0.2 * math.sin(2 * math.pi * 220 * n / rate) for n in range(size)])
    while True:
        sys.stdout.buffer.write(frame)
        sys.stdout.buffer.flush()
        time.sleep(duration)
elif command == "pacat":
    with (directory / "output.raw").open("wb", buffering=0) as output:
        while True:
            chunk = sys.stdin.buffer.read(1920)
            if not chunk:
                break
            output.write(chunk)
'''


class CLIIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(ctypes.util.find_library("rnnoise"), "RNNoise no instalado")
    def test_processes_audio_and_sigterm_removes_virtual_microphone(self):
        self.exercise_cli("denoise")

    def test_voice_transport_handles_16khz_and_variable_stream_output(self):
        for precision in PRECISIONS:
            with self.subTest(precision=precision):
                self.exercise_cli("run", precision)

    def exercise_cli(self, mode, precision="int8"):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            for command in ("pactl", "parec", "pacat"):
                executable = location / command
                executable.write_text(f"#!{sys.executable}\n" + FAKE_AUDIO_TOOL)
                executable.chmod(0o700)
            environment = dict(os.environ, ONLY_VOICE_TEST_DIRECTORY=directory)
            environment["PATH"] = directory + os.pathsep + environment.get("PATH", "")
            arguments = [mode]
            if mode == "run":
                # A simulated dependency proves our transport integration, not
                # acoustic separation or compatibility with the real weights.
                package = location / "voxlock"
                package.mkdir()
                (package / "__init__.py").write_text(
                    'import os\n'
                    'class VoxLock:\n'
                    '    def __init__(self, **kwargs):\n'
                    '        assert kwargs["precision"] == os.environ["TEST_PRECISION"]\n'
                    '        self.chunk = None\n'
                    'class Stream:\n'
                    '    def __init__(self, engine, sample):\n'
                    '        self.features = engine.enroll.run(None, {"enroll": sample})\n'
                    '        self.first = True\n'
                    '    def push(self, x):\n'
                    '        if self.first:\n'
                    '            self.first = False\n'
                    '            return x[384:] * 0.5\n'
                    '        return x * 0.5\n'
                )
                environment["PYTHONPATH"] = directory
                environment["TEST_PRECISION"] = precision
                for name in model_files(precision):
                    (location / name).touch()
                profile = location / "profile.npz"
                np.savez(profile, version=2, backend="voxlock", revision=MODEL_REVISION,
                         mag=np.ones((1, 2)), context=np.ones((1, 2)))
                arguments += ["--profile", str(profile), "--model", directory, "--precision", precision]
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(
                    [sys.executable, "-m", "only_voice", *arguments],
                    cwd=Path(__file__).resolve().parents[1], env=environment,
                    stdout=subprocess.DEVNULL, stderr=errors,
                )
                try:
                    deadline = time.monotonic() + 5
                    output = location / "output.raw"
                    while time.monotonic() < deadline and process.poll() is None:
                        if output.exists() and output.stat().st_size >= 1920 * 10:
                            break
                        time.sleep(0.02)
                    self.assertIsNone(process.poll(), "La CLI salió antes de procesar audio.")
                    self.assertTrue(output.exists())
                    self.assertGreaterEqual(output.stat().st_size, 1920 * 10)
                    process.terminate()
                    process.wait(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    errors.seek(0)
                    diagnostics = errors.read().decode()
                self.assertEqual(process.returncode, 0, diagnostics)
            commands = [json.loads(line) for line in (location / "commands.jsonl").read_text().splitlines()]
            self.assertEqual(commands[-2:], [["unload-module", "102"], ["unload-module", "101"]])
            self.assertFalse(any("set-default-source" in command for command in commands))
            if mode == "run":
                loads = [command for command in commands if command[0] == "load-module"]
                self.assertTrue(all("rate=16000" in command for command in loads))
            samples = np.frombuffer(output.read_bytes(), dtype="<f4")
            self.assertTrue(np.isfinite(samples).all())
            self.assertLessEqual(float(np.max(np.abs(samples))), 1)
            self.assertGreater(float(np.max(np.abs(samples))), 0)
