"""Exercise the real window handlers without a display or microphone."""

from collections import Counter
from pathlib import Path
import tempfile
import threading
import time
import unittest

try:
    from only_voice.gtk_gui import Window
except ImportError:
    Window = None

from only_voice.application import Application, Paths
from only_voice.desktop_backend import DesktopBackend
from only_voice.metering import MeterEnvelope


class Widget:
    def __init__(self):
        self.values = {}
        self.calls = Counter()
        self.selected = 0
        self.active = False

    def __getattr__(self, name):
        if name.startswith('set_'):
            def setter(value):
                self.calls[name] += 1
                self.values[name] = value
                if name == 'set_selected':
                    self.selected = value
                if name == 'set_active':
                    self.active = value
            return setter
        raise AttributeError(name)

    def get_selected(self):
        return self.selected

    def get_active(self):
        return self.active

    def add_css_class(self, name):
        self.calls['add:' + name] += 1

    def remove_css_class(self, name):
        self.calls['remove:' + name] += 1


class SimulatedController(Application):
    def __init__(self, paths):
        super().__init__(paths)
        self.state = {'active': False, 'phase': 'stopped'}
        self.actions = []

    def status(self):
        return dict(self.state)

    def start(self, source, mode, precision='int8'):
        self.actions.append(('start', source, mode, precision, threading.get_ident()))
        self.state = {'active': True, 'phase': 'running', 'task': 'filter', 'mode': mode, 'precision': precision}
        return self.status()

    def stop(self):
        self.actions.append(('stop', threading.get_ident()))
        self.state = {'active': False, 'phase': 'stopped'}
        return self.status()

    def register(self, source):
        self.actions.append(('profile', source, threading.get_ident()))
        self.state = {'active': True, 'phase': 'recording', 'task': 'profile'}
        return self.status()


class Harness:
    def __init__(self, controller):
        self.controller = controller
        self.backend = DesktopBackend(controller, interval=0.01)
        self.pending = self.refreshing = self.closed = self.closing = False
        self.error = None
        self.mode, self.saved_source = 'voice', None
        self.precision = 'int8'
        self.initialized = self.has_profile = self.devices_loaded = False
        self.device_names, self.device_records = [None], []
        self.available_sources = set()
        self.state, self._values = {'active': False, 'phase': 'stopped'}, {}
        names = ('badge', 'title', 'message', 'description', 'profile_label', 'profile_button',
                 'microphone', 'voice_mode', 'noise_mode', 'refresh_button', 'action', 'progress', 'level_box',
                 'variant_box', 'variant', 'variant_description')
        self.widgets = [Widget() for _ in names]
        for name, widget in zip(names, self.widgets):
            setattr(self, name, widget)
        self.levels = [Widget(), Widget()]
        self.meter_envelopes = [MeterEnvelope(), MeterEnvelope()]
        self.meter_tick = self.meter_frame_time = None

    def add_tick_callback(self, callback):
        return 1

    def remove_tick_callback(self, identifier):
        pass

    def __getattr__(self, name):
        # These are the production Python handlers, not a second implementation.
        method = getattr(Window, name)
        return method.__get__(self, Harness)

    def destroy(self):
        pass

    def until(self, predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.tick()
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError('No se completó la operación de la ventana')


@unittest.skipIf(Window is None, 'Ejecutar con Python del sistema para usar GTK')
class WindowControllerTests(unittest.TestCase):
    def test_variant_restoration_selection_persistence_and_active_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = SimulatedController(Paths(Path(directory)))
            controller.save_settings(precision='fp16')
            controller.paths.profile.parent.mkdir()
            controller.paths.profile.touch()
            window = Harness(controller)
            try:
                window.until(lambda: window.initialized)
                self.assertEqual(window.precision, 'fp16')
                self.assertEqual(window.variant.get_selected(), 2)
                window.complete([], None, True)
                window.variant.set_selected(3)
                window.variant_changed(window.variant)
                self.assertEqual(window.precision, 'fp32')
                window.toggle()
                window.until(lambda: not window.pending and window.state['active'])
                self.assertEqual(controller.actions[0][3], 'fp32')
                self.assertEqual(controller.settings()['precision'], 'fp32')
                self.assertFalse(window.variant.values['set_sensitive'])
                self.assertIn('FP32', window.message.values['set_text'])
                window.toggle()
                window.until(lambda: not window.pending and not window.state['active'])
                self.assertTrue(window.variant.values['set_sensitive'])
                window.noise_mode.set_active(True)
                window.mode_changed(window.noise_mode, 'noise')
                self.assertFalse(window.variant_box.values['set_visible'])
            finally:
                window.backend.close()
                window.backend._poll_thread.join(timeout=1)

    def test_select_microphone_start_stop_register_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = SimulatedController(Paths(Path(directory)))
            window = Harness(controller)
            try:
                window.until(lambda: window.initialized)
                window.complete([{'name': 'physical_mic', 'description': 'Mi micrófono'}], None, True)
                window.microphone.set_selected(1)
                self.assertEqual(window.selected_source(), 'physical_mic')
                window.noise_mode.set_active(True)
                window.mode_changed(window.noise_mode, 'noise')
                self.assertTrue(window.action.values['set_sensitive'])
                window.toggle()
                window.until(lambda: not window.pending and window.state['active'])
                self.assertEqual(window.action.values['set_label'], 'Desactivar filtro')
                window.toggle()
                window.until(lambda: not window.pending and not window.state['active'])
                window.register()
                window.until(lambda: not window.pending and window.state.get('task') == 'profile')
                self.assertEqual(window.action.values['set_label'], 'Cancelar grabación')
                window.on_close()
                window.until(lambda: window.closed)
                self.assertEqual([action[0] for action in controller.actions], ['start', 'stop', 'profile', 'stop'])
                self.assertEqual(controller.actions[0][1:3], ('physical_mic', 'noise'))
                self.assertEqual(controller.actions[2][1], 'physical_mic')
                self.assertTrue(all(action[-1] != threading.get_ident() for action in controller.actions))
            finally:
                window.backend.close()
                window.backend._poll_thread.join(timeout=1)

    def test_idle_refresh_does_not_rebuild_controls_and_meter_updates_are_local(self):
        with tempfile.TemporaryDirectory() as directory:
            window = Harness(SimulatedController(Paths(Path(directory))))
            try:
                window.until(lambda: window.initialized)
                window.state = {'active': True, 'phase': 'running', 'task': 'filter', 'input_db': -35}
                window.render()
                before = [dict(widget.calls) for widget in window.widgets]
                levels = [dict(widget.calls) for widget in window.levels]
                for _ in range(100):
                    window.render()
                self.assertEqual(before, [dict(widget.calls) for widget in window.widgets])
                self.assertEqual(levels, [dict(widget.calls) for widget in window.levels])
                window.state['input_db'] = -25
                window.render()
                self.assertEqual(before, [dict(widget.calls) for widget in window.widgets])
                self.assertEqual(window.meter_envelopes[0].target, 35)
                from types import SimpleNamespace
                samples = []
                for frame in range(1, 61):
                    clock = SimpleNamespace(get_frame_time=lambda: frame * 1_000_000 / 60)
                    window.animate_meters(window, clock)
                    samples.append(window.levels[0].values['set_value'])
                self.assertTrue(0 < samples[0] < 35)
                self.assertEqual(samples[-1], 35)
                self.assertEqual(before, [dict(widget.calls) for widget in window.widgets])
                self.assertIsNone(window.meter_tick)
                window.state = {'active': False, 'phase': 'stopped'}
                window.render()
                self.assertEqual(window.levels[0].values['set_value'], 0)
            finally:
                window.backend.close()
                window.backend._poll_thread.join(timeout=1)
