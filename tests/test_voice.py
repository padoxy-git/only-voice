from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import numpy as np

from only_voice import voice
from only_voice.variants import PRECISIONS, model_files


def write_profile(path, **changes):
    fields = dict(version=2, backend="voxlock", revision=voice.MODEL_REVISION,
                  mag=np.ones((1, 257, 10), dtype=np.float32),
                  context=np.ones((1, 32, 256), dtype=np.float32))
    fields.update(changes)
    with Path(path).open("wb") as stream:
        np.savez_compressed(stream, **fields)


class FakeStream:
    def __init__(self, engine, reference):
        self.features = engine.enroll.run(None, {"enroll": reference})
        self.first = True

    def push(self, frame):
        result = frame * 0.5
        if self.first:
            self.first = False
            return result[384:]
        return result


class VoiceTests(unittest.TestCase):
    def test_variant_loading_requires_exact_files_and_never_falls_back(self):
        constructor = Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # FP32 is present, but cannot substitute for an absent INT8 chunk.
            for name in ("enroll.onnx", "chunk.onnx"):
                (root / name).touch()
            with patch.dict(sys.modules, {"voxlock": SimpleNamespace(VoxLock=constructor)}):
                with self.assertRaisesRegex(FileNotFoundError, "chunk_int8.onnx"):
                    voice.load_engine(root, precision="int8")
                constructor.assert_not_called()
                for precision in PRECISIONS:
                    with self.subTest(precision=precision):
                        for name in model_files(precision):
                            (root / name).touch()
                        voice.load_engine(root, threads=2, precision=precision)
                        constructor.assert_called_with(model_dir=str(root), threads=2, precision=precision)

    def test_downloads_only_the_missing_files_of_the_requested_variant(self):
        expected = {"int8": ("enroll.onnx", "chunk_int8.onnx"),
                    "int8-full": ("enroll.onnx", "chunk_int8_full.onnx"),
                    "fp16": ("enroll_fp16.onnx", "chunk_fp16.onnx"),
                    "fp32": ("enroll.onnx", "chunk.onnx")}
        class HTTPError(Exception):
            pass
        for precision, files in expected.items():
            with self.subTest(precision=precision), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "onnx").mkdir()
                (root / "onnx" / files[0]).touch()
                fetch = Mock()
                modules = {"huggingface_hub": SimpleNamespace(hf_hub_download=fetch),
                           "huggingface_hub.utils": SimpleNamespace(HfHubHTTPError=HTTPError)}
                with patch.dict(sys.modules, modules):
                    voice.download_model(root, precision)
                    fetch.assert_called_once_with(voice.MODEL_REPO, f"onnx/{files[1]}",
                                                  revision=voice.MODEL_REVISION, local_dir=str(root), token=False)
                    (root / "onnx" / files[1]).touch()
                    fetch.reset_mock()
                    voice.ensure_model(root / "onnx", precision)
                    voice.download_model(root, precision)
                    fetch.assert_not_called()

    @patch("only_voice.voice.load_engine")
    def test_existing_profile_is_reused_by_all_variants(self, engine):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "p.npz"
            write_profile(profile)
            original = profile.read_bytes()
            with patch.dict(sys.modules, {"voxlock": SimpleNamespace(Stream=FakeStream)}):
                for precision in PRECISIONS:
                    processor = voice.TargetVoice(directory, profile, precision=precision)
                    self.assertGreater(processor.process(np.ones(640, np.float32)).size, 0)
                    engine.assert_called_with(directory, 4, precision)
                    engine.return_value.enroll.run.assert_not_called()
                    processor.close()
            self.assertEqual(profile.read_bytes(), original)

    @patch("only_voice.voice.load_engine")
    def test_stream_accepts_variable_output_and_resets_without_reenrolling(self, engine):
        engine.return_value.chunk = object()
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "p.npz"
            write_profile(profile)
            with patch.dict(sys.modules, {"voxlock": SimpleNamespace(Stream=FakeStream)}):
                processor = voice.TargetVoice(directory, profile)
                frame = np.ones(640, dtype=np.float32) * 0.2
                np.testing.assert_array_equal(processor.process(frame), frame[384:] * 0.5)
                np.testing.assert_array_equal(processor.process(frame), frame * 0.5)
                processor.reset()
                np.testing.assert_array_equal(processor.process(frame), frame[384:] * 0.5)
                engine.return_value.enroll.run.assert_not_called()
                with self.assertRaises(ValueError):
                    processor.process(np.zeros(480, dtype=np.float32))

    @patch("only_voice.voice.load_engine")
    def test_stream_rejects_invalid_output(self, engine):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "p.npz"
            write_profile(profile)
            with patch.dict(sys.modules, {"voxlock": SimpleNamespace(Stream=FakeStream)}):
                processor = voice.TargetVoice(directory, profile)
                for bad in (np.full(640, np.nan), np.zeros((1, 640)), np.zeros(641)):
                    processor.stream = SimpleNamespace(push=lambda _, result=bad: result)
                    with self.assertRaises(RuntimeError):
                        processor.process(np.zeros(640, dtype=np.float32))

    def test_profiles_reject_bad_revision_or_nonfinite_features(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "p.npz"
            for changes in (dict(revision="other"), dict(version=1),
                            dict(mag=np.array([np.nan])), dict(context=np.array([]))):
                write_profile(profile, **changes)
                with self.assertRaises(ValueError):
                    voice.load_profile(profile)

    @patch("only_voice.voice.load_engine")
    def test_enrollment_saves_only_features_and_selects_non_silent_reference(self, engine):
        features = (np.ones((1, 257, 10), np.float32), np.ones((1, 32, 256), np.float32))
        engine.return_value.enroll.run.return_value = features
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "ref.wav"
            samples = np.concatenate([np.zeros(32000), np.ones(48000) * 3000]).astype("<i2")
            with wave.open(str(reference), "wb") as recording:
                recording.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                recording.writeframes(samples.tobytes())
            profile = Path(directory) / "p.npz"
            voice.enroll(reference, profile, "unused")
            chosen = engine.return_value.enroll.run.call_args.args[1]["enroll"]
            self.assertEqual(chosen.shape, (1, 48000))
            np.testing.assert_array_equal(chosen, np.full((1, 48000), 3000 / 32768, np.float32))
            loaded = voice.load_profile(profile)
            for expected, actual in zip(features, loaded):
                np.testing.assert_array_equal(expected, actual)
            with np.load(profile, allow_pickle=False) as saved:
                self.assertEqual(set(saved.files), {"version", "backend", "revision", "mag", "context"})

    def test_public_download_pins_revision_and_disables_implicit_credentials(self):
        fetch = Mock()
        class HTTPError(Exception):
            pass
        modules = {"huggingface_hub": SimpleNamespace(hf_hub_download=fetch),
                   "huggingface_hub.utils": SimpleNamespace(HfHubHTTPError=HTTPError)}
        with patch.dict(sys.modules, modules):
            self.assertEqual(voice.download_model("somewhere"), Path("somewhere/onnx"))
        self.assertEqual(fetch.call_count, 2)
        for call in fetch.call_args_list:
            self.assertEqual(call.args[0], voice.MODEL_REPO)
            self.assertEqual(call.kwargs["revision"], voice.MODEL_REVISION)
            self.assertIs(call.kwargs["token"], False)

    def test_unavailable_public_model_explains_failure_without_authentication_advice(self):
        class HTTPError(Exception):
            response = SimpleNamespace(status_code=401)
        fetch = Mock(side_effect=HTTPError("unavailable"))
        modules = {"huggingface_hub": SimpleNamespace(hf_hub_download=fetch),
                   "huggingface_hub.utils": SimpleNamespace(HfHubHTTPError=HTTPError)}
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                voice.download_model("somewhere")
        self.assertEqual(fetch.call_count, 1)
