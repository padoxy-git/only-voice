"""Regression coverage for launching a Wayland UI outside the audio venv."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from only_voice.application import Paths, audio_python
from only_voice.desktop import launch


class DesktopTests(unittest.TestCase):
    def test_wayland_uses_native_python_and_retains_audio_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            with patch('only_voice.desktop.Paths', return_value=paths), \
                 patch('only_voice.desktop.gtk_python', return_value='/usr/bin/python3'), \
                 patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-1', 'GDK_BACKEND': 'x11'}), \
                 patch('only_voice.desktop.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertEqual(launch(), 0)
            command = run.call_args.args[0]
            self.assertEqual(command, ['/usr/bin/python3', '-m', 'only_voice.gtk_gui'])
            self.assertEqual(run.call_args.kwargs['env']['GDK_BACKEND'], 'wayland')
            self.assertEqual(run.call_args.kwargs['env']['GSK_RENDERER'], os.environ.get('GSK_RENDERER', 'cairo'))
            self.assertIn('GTK 4', paths.file('gui.log').read_text())

    def test_menu_launch_failure_has_persistent_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = Paths(Path(directory))
            def failed_run(*args, **kwargs):
                kwargs['stderr'].write('Cannot connect to display\n')
                return subprocess.CompletedProcess(args[0], 1)
            with patch('only_voice.desktop.Paths', return_value=paths), \
                 patch('only_voice.desktop.gtk_python', return_value='/usr/bin/python3'), \
                 patch('only_voice.desktop.shutil.which', return_value=None), \
                 patch('only_voice.desktop.subprocess.run', side_effect=failed_run):
                with self.assertRaisesRegex(RuntimeError, 'gui.log'):
                    launch()
            self.assertIn('Cannot connect to display', paths.file('gui.log').read_text())
            self.assertEqual(paths.file('gui.log').stat().st_mode & 0o777, 0o600)

    def test_audio_python_does_not_follow_system_gui_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = root / '.venv-voice/bin/python'
            prepared.parent.mkdir(parents=True)
            prepared.write_text('#!/bin/sh\n')
            prepared.chmod(0o700)
            with patch('only_voice.application.PROJECT', root), \
                 patch('only_voice.application.sys.executable', '/usr/bin/python3'):
                self.assertEqual(audio_python(), str(prepared))


class NativeWindowTests(unittest.TestCase):
    def test_native_window_and_controls(self):
        try:
            from only_voice.gtk_gui import Gtk, Gdk, Gio, GLib, Window, CSS
        except ImportError:
            self.skipTest('PyGObject no disponible en este intérprete')
        if not Gtk.init_check() or Gdk.Display.get_default() is None:
            self.skipTest('La sesión gráfica no es accesible')
        provider = Gtk.CssProvider()
        css_errors = []
        provider.connect('parsing-error', lambda *args: css_errors.append(str(args[-1])))
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        application = Gtk.Application(application_id='io.onlyvoice.Test', flags=Gio.ApplicationFlags.NON_UNIQUE)
        application.register(None)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(Window, 'refresh_devices'):
            from only_voice.application import Application
            window = Window(application, Application(Paths(Path(directory))))
            try:
                window.present()
                import time
                deadline = time.monotonic() + 2
                while not window.initialized and time.monotonic() < deadline:
                    window.tick()
                    time.sleep(0.01)
                window.complete([{'name': 'physical_mic', 'description': 'Mi micrófono'}], None, True)
                for _ in range(30):
                    GLib.MainContext.default().iteration(False)
                self.assertTrue(window.get_visible())
                self.assertFalse(window.action.get_sensitive())
                window.noise_mode.set_active(True)
                self.assertTrue(window.action.get_sensitive())
                window.complete(None, 'Error de prueba', False)
                self.assertEqual(window.message.get_text(), 'Error de prueba')
                self.assertEqual(css_errors, [])
            finally:
                window.close()
