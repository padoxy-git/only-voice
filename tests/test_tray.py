import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent
from only_voice.application import Application, Paths
from only_voice.tray import TrayController


class TrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Paths(Path(self.temp.name)))
        self.app.save_settings(source='mic', mode='voice', precision='fp16')
        self.discover = patch('only_voice.tray.discover', return_value=[{'name': 'mic', 'description': 'Micrófono'}])
        self.discover.start()
        self.controller = TrayController(self.qt, self.app)
        self.wait_for(lambda: self.controller.loaded and self.controller.devices_loaded)

    def tearDown(self):
        self.controller.timer.stop()
        self.controller.backend.close()
        self.controller.backend._poll_thread.join(1)
        self.controller.tray.hide()
        self.controller.window.deleteLater()
        self.qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.discover.stop()
        self.temp.cleanup()

    def wait_for(self, check):
        deadline = time.monotonic() + 3
        while not check() and time.monotonic() < deadline:
            self.qt.processEvents()
            self.controller.tick()
            time.sleep(.01)
        self.assertTrue(check())

    def test_starts_hidden_opens_from_tray_and_close_keeps_filter(self):
        c = self.controller
        self.assertFalse(c.window.isVisible())
        self.assertEqual(c.window.source.currentData(), 'mic')
        self.assertEqual(c.window.precision.currentData(), 'fp16')
        c.settings_action.trigger()
        self.assertTrue(c.window.isVisible())
        with patch.object(self.app, 'stop') as stop:
            c.window.close()
            self.assertFalse(c.window.isVisible())
            stop.assert_not_called()
        self.assertTrue(c.timer.isActive())

    def test_modes_profile_requirement_and_persisted_preferences(self):
        c = self.controller
        self.assertFalse(c.window.action.isEnabled())
        c.window.mode.setCurrentIndex(1)
        self.assertTrue(c.window.action.isEnabled())
        self.wait_for(lambda: self.app.settings()['mode'] == 'noise')
        self.assertEqual(self.app.settings()['precision'], 'fp16')
        c.state = dict(active=True, phase='running', task='filter', mode='noise')
        c.active = True
        c.render()
        self.assertFalse(c.window.source.isEnabled())
        self.assertTrue(c.window.action.isEnabled())
        self.assertEqual(c.window.action.text(), 'Desactivar filtro')

    def test_toggle_and_quit_use_async_worker_controls(self):
        c = self.controller
        c.window.mode.setCurrentIndex(1)
        with patch.object(self.app, 'start', return_value={}) as start:
            c.toggle_action.trigger()
            self.wait_for(lambda: not c.pending)
            start.assert_called_once_with(source='mic', mode='noise', precision='fp16')
        with patch.object(self.app, 'stop', return_value={}) as stop, patch.object(self.qt, 'quit') as quit:
            c.quit_action.trigger()
            self.wait_for(lambda: not c.timer.isActive())
            stop.assert_called_once()
            quit.assert_called_once()
