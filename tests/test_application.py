from contextlib import redirect_stderr
import ctypes.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

from only_voice.application import Application, Paths, process_identity, read_json, wait_ready, write_json
from only_voice.gui import presentation
from only_voice.install import desktop_entry, install, quote_exec
from only_voice import worker
from test_cli_integration import FAKE_AUDIO_TOOL


class ApplicationTests(unittest.TestCase):
    def test_old_settings_default_to_int8_and_new_selection_is_remembered(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(Paths(Path(directory)))
            write_json(app.paths.file("settings.json"), {"source": "mic", "mode": "voice"})
            self.assertEqual(app.settings()["precision"], "int8")
            with patch.object(app, "_launch", return_value={"phase": "starting"}) as launch:
                app.start(precision="fp16")
                launch.assert_called_with("filter", "mic", "voice", precision="fp16")
                self.assertEqual(Application(app.paths).settings()["precision"], "fp16")
                app.start()
                launch.assert_called_with("filter", "mic", "voice", precision="fp16")

    def test_running_filter_cannot_change_variant_until_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(Paths(Path(directory)))
            active = {"active": True, "phase": "running", "task": "filter", "mode": "voice",
                      "requested_source": None, "precision": "int8"}
            with patch.object(app, "status", return_value=active):
                self.assertEqual(app.start(), active)
                with self.assertRaisesRegex(RuntimeError, "variante"):
                    app.start(precision="fp32")
                self.assertEqual(app.settings()["precision"], "int8")

    @patch("only_voice.worker.signal.signal")
    @patch("only_voice.worker.run_stream")
    @patch("only_voice.worker.TargetVoice")
    @patch("only_voice.worker.ensure_model")
    def test_worker_downloads_and_processes_selected_variant(self, ensure, target, stream, *_):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            result = worker.main(["--project", directory, "--task", "filter", "--precision", "fp16"])
            self.assertEqual(result, 0)
            ensure.assert_called_once_with(paths.models, "fp16")
            target.assert_called_once_with(paths.models, paths.profile, precision="fp16")
            self.assertIs(stream.call_args.args[0], target.return_value)
            self.assertEqual(read_json(paths.file("state.json"))["precision"], "fp16")

    @patch("only_voice.worker.signal.signal")
    @patch("only_voice.worker.run_stream")
    @patch("only_voice.worker.TargetVoice")
    @patch("only_voice.worker.ensure_model", side_effect=RuntimeError("HTTP 404"))
    def test_download_failure_reports_error_without_starting_audio_or_touching_profile(self, ensure, target, stream, *_):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            paths.profile.parent.mkdir()
            paths.profile.write_bytes(b"saved profile")
            with redirect_stderr(io.StringIO()):
                result = worker.main(["--project", directory, "--task", "filter", "--precision", "fp32"])
            self.assertEqual(result, 1)
            target.assert_not_called()
            stream.assert_not_called()
            state = read_json(paths.file("state.json"))
            self.assertEqual(state["phase"], "error")
            self.assertEqual(state["precision"], "fp32")
            self.assertIn("HTTP 404", state["message"])
            self.assertEqual(paths.profile.read_bytes(), b"saved profile")

    def test_invalid_saved_preferences_have_usable_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(Paths(Path(directory)))
            write_json(app.paths.file("settings.json"), {"source": 4, "mode": "unknown", "precision": "unknown"})
            write_json(app.paths.file("state.json"), {})
            self.assertEqual(app.settings(), {"source": None, "mode": "voice", "precision": "int8"})
            self.assertEqual(app.status()["phase"], "stopped")

    def test_stale_or_unrelated_pid_is_never_signalled(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(Paths(Path(directory)))
            for identity in ("stale-start-time", process_identity(os.getpid())):
                write_json(app.paths.file("state.json"), {"pid": os.getpid(), "identity": identity,
                                                         "phase": "running", "task": "filter"})
                with patch("only_voice.application.os.kill") as kill:
                    self.assertFalse(app.stop()["active"])
                    kill.assert_not_called()

    @unittest.skipUnless(ctypes.util.find_library("rnnoise"), "RNNoise no instalado")
    def test_two_controllers_share_one_worker_and_cleanup_on_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            binaries = location / "bin"
            binaries.mkdir()
            for command in ("pactl", "parec", "pacat"):
                path = binaries / command
                path.write_text(f"#!{sys.executable}\n" + FAKE_AUDIO_TOOL)
                path.chmod(0o700)
            paths = Paths(location / "app")
            app, second = Application(paths), Application(paths)
            environment = {"PATH": str(binaries) + os.pathsep + os.environ.get("PATH", ""),
                           "ONLY_VOICE_TEST_DIRECTORY": directory}
            with patch.dict(os.environ, environment):
                try:
                    app.start(mode="noise")
                    active = wait_ready(app, timeout=8)
                    self.assertEqual(active["phase"], "running", app.details())
                    self.assertTrue(active["active"])
                    self.assertIn("input_db", active)
                    self.assertIn("output_db", active)
                    self.assertEqual(second.start()["pid"], active["pid"])
                    with self.assertRaises(RuntimeError):
                        second.start(mode="voice")
                    with self.assertRaises(RuntimeError):
                        second.register()
                    self.assertFalse(second.stop()["active"])
                    self.assertFalse(app.status()["active"])
                finally:
                    app.stop()
            commands = [json.loads(line) for line in (location / "commands.jsonl").read_text().splitlines()]
            loads = [command for command in commands if command[0] == "load-module"]
            self.assertEqual(len(loads), 2)
            self.assertEqual(commands[-2:], [["unload-module", "102"], ["unload-module", "101"]])
            self.assertEqual(app.settings()["mode"], "noise")

    @patch("only_voice.worker.signal.signal")
    @patch("only_voice.worker.ensure_model")
    @patch("only_voice.worker.load_engine")
    @patch("only_voice.worker.record_reference", side_effect=KeyboardInterrupt)
    def test_cancelled_profile_preserves_previous_identity(self, *_):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            paths.profile.parent.mkdir(parents=True)
            paths.profile.write_bytes(b"previous profile")
            result = worker.main(["--project", directory, "--task", "profile"])
            self.assertEqual(result, 0)
            self.assertEqual(paths.profile.read_bytes(), b"previous profile")
            self.assertEqual(read_json(paths.file("state.json"))["phase"], "stopped")

    @patch("only_voice.worker.signal.signal")
    @patch("only_voice.worker.ensure_model")
    @patch("only_voice.worker.load_engine")
    @patch("only_voice.worker.enroll", side_effect=RuntimeError("bad sample"))
    @patch("only_voice.worker.record_reference")
    def test_failed_profile_preserves_previous_identity(self, record, *_):
        record.side_effect = lambda destination, *args, **kwargs: destination.write_bytes(b"sample")
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            paths.profile.parent.mkdir(parents=True)
            paths.profile.write_bytes(b"previous profile")
            with redirect_stderr(io.StringIO()):
                result = worker.main(["--project", directory, "--task", "profile"])
            self.assertEqual(result, 1)
            self.assertEqual(paths.profile.read_bytes(), b"previous profile")
            self.assertEqual(read_json(paths.file("state.json"))["phase"], "error")
            self.assertFalse(record.call_args.args[0].exists())

    def test_gui_exposes_cancel_during_recording_and_requires_identity_for_voice(self):
        self.assertFalse(presentation({"active": False}, False)["enabled"])
        self.assertTrue(presentation({"active": False}, False, "noise")["enabled"])
        view = presentation({"active": True, "phase": "recording", "task": "profile"}, False)
        self.assertEqual(view["action"], "Cancelar grabación")
        self.assertTrue(view["enabled"])
        view = presentation({"active": True, "phase": "running", "task": "filter"}, True)
        self.assertEqual(view["action"], "Desactivar filtro")


class InstallerTests(unittest.TestCase):
    def test_install_is_idempotent_and_does_not_replace_unrelated_command(self):
        with tempfile.TemporaryDirectory(prefix="only voice ") as directory:
            prefix = Path(directory) / "local"
            destination = install(prefix)
            self.assertTrue(destination.is_symlink())
            self.assertEqual(install(prefix), destination)
            desktop = prefix / "share/applications/only-voice.desktop"
            self.assertIn(" gui\n", desktop.read_text())
            self.assertIn("Terminal=false", desktop.read_text())
            destination.unlink()
            destination.write_text("another application")
            with self.assertRaises(FileExistsError):
                install(prefix)
            self.assertEqual(destination.read_text(), "another application")

    def test_desktop_exec_handles_spaces_and_literal_field_codes(self):
        entry = desktop_entry(Path('/tmp/a project/100%'))
        self.assertIn('Exec="/tmp/a project/100%%/only-voice" gui', entry)
        with self.assertRaises(ValueError):
            quote_exec("/tmp/project\nExec=wrong")
