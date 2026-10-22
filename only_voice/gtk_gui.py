"""Wayland-native window. GTK stays on the main thread; audio stays in its venv."""

from pathlib import Path
import queue
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .application import Application, PROJECT
from .desktop_backend import DesktopBackend, microphones
from .gui_state import presentation
from .metering import LEVEL_INTERVAL, MeterEnvelope
from .variants import DEFAULT_PRECISION, PRECISIONS, VARIANTS

CSS = (Path(__file__).with_name("styles") / "zephyx.css").read_text()


def box(vertical=True, spacing=12):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                   spacing=spacing)


def label(text="", style=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True)
    widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if style:
        widget.add_css_class(style)
    return widget


class Window(Gtk.ApplicationWindow):
    def __init__(self, gtk_application, controller=None):
        super().__init__(application=gtk_application, title="Only Voice", default_width=540, default_height=720)
        self.controller = controller or Application()
        self.pending = False
        self.refreshing = False
        self.closed = False
        self.closing = False
        self.error = None
        self.devices_loaded = False
        self.device_names = [None]
        self.available_sources = set()
        self.saved_source = None
        self.mode = "voice"
        self.precision = DEFAULT_PRECISION
        self.state = {"phase": "stopped", "active": False}
        self.has_profile = False
        self.initialized = False
        self._values = {}
        self.device_records = []
        self.meter_envelopes = [MeterEnvelope(), MeterEnvelope()]
        self.meter_tick = None
        self.meter_frame_time = None
        self.add_css_class("only-voice")
        self.set_size_request(420, 480)
        self.connect("close-request", self.on_close)
        self.build()
        self.backend = DesktopBackend(self.controller)
        self.refresh_devices()
        self.tick()
        self.timer = GLib.timeout_add(round(LEVEL_INTERVAL * 1000), self.tick)

    def build(self):
        main = box(spacing=16)
        main.add_css_class("main")
        self.set_child(main)
        header = box(False, 12)
        icon = Gtk.Image.new_from_file(str(PROJECT / "assets/only-voice.svg"))
        icon.set_pixel_size(40)
        header.append(icon)
        heading = box(spacing=2)
        heading.set_hexpand(True)
        heading.append(label("Only Voice", "heading"))
        heading.append(label("Tu voz, en primer plano.", "subtitle"))
        header.append(heading)
        self.badge = label("Detenido", "badge")
        self.badge.set_valign(Gtk.Align.CENTER)
        header.append(self.badge)
        main.append(header)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        body = box()
        scroller.set_child(body)
        main.append(scroller)

        audio = box()
        audio.add_css_class("card")
        row = box(False)
        caption = label("MICRÓFONO", "caption")
        caption.set_hexpand(True)
        row.append(caption)
        self.refresh_button = Gtk.Button(label="Actualizar")
        self.refresh_button.connect("clicked", lambda *_: self.refresh_devices())
        row.append(self.refresh_button)
        audio.append(row)
        self.microphone = Gtk.DropDown.new_from_strings(["Micrófono del sistema"])
        self.microphone.set_enable_search(True)
        audio.append(self.microphone)
        modes = box(False, 20)
        self.voice_mode = Gtk.CheckButton(label="Solo mi voz")
        self.noise_mode = Gtk.CheckButton(label="Reducir ruido")
        self.noise_mode.set_group(self.voice_mode)
        (self.voice_mode if self.mode == "voice" else self.noise_mode).set_active(True)

        modes.append(self.voice_mode)
        modes.append(self.noise_mode)
        audio.append(modes)
        self.description = label(style="muted")
        audio.append(self.description)
        self.variant_box = box(spacing=8)
        self.variant_box.append(label("VARIANTE DE VOZ", "caption"))
        self.variant = Gtk.DropDown.new_from_strings([VARIANTS[key]["label"] for key in PRECISIONS])
        self.variant.connect("notify::selected", self.variant_changed)
        self.variant_box.append(self.variant)
        self.variant_description = label(style="muted")
        self.variant_box.append(self.variant_description)
        self.variant_box.append(label("La primera vez se descarga el modelo. Tu perfil sirve para las cuatro variantes.", "muted"))
        audio.append(self.variant_box)
        body.append(audio)

        voice = box()
        voice.add_css_class("card")
        voice.append(label("Tu voz", "card-title"))
        self.profile_label = label(style="muted")
        voice.append(self.profile_label)
        self.profile_button = Gtk.Button(label="Grabar mi voz")
        self.profile_button.set_halign(Gtk.Align.START)
        self.profile_button.connect("clicked", self.register)
        voice.append(self.profile_button)
        body.append(voice)

        status = box()
        status.add_css_class("card")
        self.title = label(style="card-title")
        self.message = label(style="muted")
        status.append(self.title)
        status.append(self.message)
        self.progress = Gtk.ProgressBar()
        status.append(self.progress)
        self.level_box = box(spacing=10)
        self.levels = []
        for text in ("Entrada", "Salida"):
            row = box(False)
            caption = label(text, "muted")
            caption.set_width_chars(7)
            row.append(caption)
            meter = Gtk.LevelBar(min_value=0, max_value=60, value=0, hexpand=True)
            meter.set_valign(Gtk.Align.CENTER)
            row.append(meter)
            self.levels.append(meter)
            self.level_box.append(row)
        status.append(self.level_box)
        body.append(status)
        self.action = Gtk.Button(label="Activar filtro")
        self.action.add_css_class("primary")
        self.action.connect("clicked", self.toggle)
        main.append(self.action)
        footer = box(False)
        caption = label("● Procesamiento local", "muted")
        caption.set_hexpand(True)
        footer.append(caption)
        details = Gtk.Button(label="Ver detalles")
        details.connect("clicked", self.details)
        footer.append(details)
        main.append(footer)
        main.append(label("Al cerrar la ventana, el filtro sigue activo.", "muted"))
        self.voice_mode.connect("toggled", self.mode_changed, "voice")
        self.noise_mode.connect("toggled", self.mode_changed, "noise")

    def mode_changed(self, button, mode):
        if button.get_active():
            self.mode = mode
            self.render()

    def variant_changed(self, dropdown, *_):
        index = dropdown.get_selected()
        if index < len(PRECISIONS):
            self.precision = PRECISIONS[index]
            self.render()

    def selected_source(self):
        index = self.microphone.get_selected()
        return self.device_names[index] if index < len(self.device_names) else None

    def async_call(self, function, devices=False):
        if devices:
            self.refreshing = True
        else:
            self.pending = True
            self.error = None
        self.render()
        self.backend.submit("devices" if devices else "job", function)

    def populate_devices(self, devices, selected):
        self.device_records = devices
        self.available_sources = {item["name"] for item in devices}
        self.device_names = [None] + [item["name"] for item in devices]
        labels = ["Micrófono del sistema"] + [item.get("description") or item["name"] for item in devices]
        if selected and selected not in self.available_sources:
            self.device_names.append(selected)
            labels.append(f"No conectado · {selected}")
        self.microphone.set_model(Gtk.StringList.new(labels))
        self.microphone.set_selected(self.device_names.index(selected) if selected else 0)
        self.devices_loaded = True

    def complete(self, result, error, devices):
        if self.closed:
            return False
        if devices:
            self.refreshing = False
            if not error:
                self.error = None
                selected = self.selected_source() if self.devices_loaded else self.saved_source
                self.populate_devices(result, selected)
        else:
            self.pending = False
            if isinstance(result, dict) and "phase" in result:
                self.state = result
        if error:
            self.error = error
        self.render()
        return False

    def refresh_devices(self):
        if not self.refreshing:
            self.async_call(microphones, devices=True)

    def toggle(self, *_):
        if self.pending or not self.initialized:
            return
        if self.state["active"]:
            self.async_call(self.controller.stop)
        else:
            source, mode, precision = self.selected_source(), self.mode, self.precision
            def start():
                self.controller.save_settings(source=source, mode=mode, precision=precision)
                return self.controller.start(source, mode, precision)
            self.async_call(start)

    def register(self, *_):
        if self.pending or self.state["active"] or not self.initialized:
            return
        source, mode, precision = self.selected_source(), self.mode, self.precision
        def record():
            self.controller.save_settings(source=source, mode=mode, precision=precision)
            return self.controller.register(source)
        self.async_call(record)

    def details(self, *_):
        dialog = Gtk.Window(title="Detalles · Only Voice", transient_for=self, default_width=700, default_height=400)
        dialog.add_css_class("only-voice")
        scroller = Gtk.ScrolledWindow()
        view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=16, right_margin=16,
                            top_margin=16, bottom_margin=16)
        view.get_buffer().set_text("Cargando detalles…")
        scroller.set_child(view)
        dialog.set_child(scroller)
        dialog.present()
        self.backend.submit("details", lambda: (view, self.controller.details()))

    def update(self, widget, method, value):
        """Do not rebuild button labels or invalidate layouts on each meter sample."""
        key = (widget, method)
        if self._values.get(key, object()) != value:
            getattr(widget, method)(value)
            self._values[key] = value

    def css_state(self, widget, name, enabled):
        key = (widget, name)
        if self._values.get(key) != enabled:
            (widget.add_css_class if enabled else widget.remove_css_class)(name)
            self._values[key] = enabled

    def render(self):
        if self.closed:
            return
        state = self.state
        active = state["active"]
        busy = active or self.pending
        has_profile = self.has_profile
        display = presentation(state, has_profile, self.mode)
        if not self.initialized:
            display.update(title="Preparando los controles", message="Conectando con Only Voice…", enabled=False)
        if self.error:
            display.update(title="No se pudo completar", badge="Revisar", message=self.error)
        missing = self.selected_source() not in self.available_sources and self.selected_source() is not None
        if missing and not active:
            display["message"] = "El micrófono guardado no está conectado. Selecciona otra entrada."
        self.update(self.badge, "set_text", display["badge"])
        self.css_state(self.badge, "running", active and state.get("phase") == "running")
        self.css_state(self.badge, "error", bool(self.error) or state.get("phase") == "error")
        self.update(self.title, "set_text", display["title"])
        self.update(self.message, "set_text", display["message"])
        self.update(self.description, "set_text", "Conserva la voz de tu perfil y atenúa los demás sonidos." if self.mode == "voice"
                    else "Reduce el ruido de fondo. También deja pasar otras voces.")
        self.update(self.profile_label, "set_text", "Perfil guardado en este equipo" if has_profile else "Graba 15 segundos hablando tú solo")
        self.update(self.profile_button, "set_label", "Actualizar mi voz" if has_profile else "Grabar mi voz")
        self.update(self.profile_button, "set_sensitive", self.initialized and not busy and self.devices_loaded and not missing)
        self.update(self.profile_button, "set_tooltip_text", "Desactiva el filtro para actualizar tu voz." if active else "Graba una muestra hablando tú solo.")
        self.update(self.microphone, "set_sensitive", self.initialized and not busy)
        self.update(self.microphone, "set_tooltip_text", "Desactiva el filtro para cambiar de micrófono." if active else (self.selected_source() or "Usar la entrada predeterminada del sistema"))
        self.update(self.voice_mode, "set_sensitive", self.initialized and not busy)
        self.update(self.noise_mode, "set_sensitive", self.initialized and not busy)
        self.update(self.variant_box, "set_visible", self.mode == "voice")
        self.update(self.variant, "set_sensitive", self.initialized and not busy and self.mode == "voice")
        self.update(self.variant, "set_tooltip_text", "Desactiva el filtro para cambiar de variante." if active
                    else "Elige el equilibrio entre precisión y rendimiento.")
        self.update(self.variant_description, "set_text", VARIANTS[self.precision]["description"])
        self.update(self.refresh_button, "set_sensitive", not busy and not self.refreshing)
        self.update(self.action, "set_label", "Un momento…" if self.pending else display["action"])
        self.update(self.action, "set_sensitive", self.initialized and not self.pending and
                    (active or (display["enabled"] and self.devices_loaded and not missing)))
        self.css_state(self.action, "stop", active)
        recording = active and state.get("task") == "profile"
        self.update(self.progress, "set_visible", recording)
        self.update(self.progress, "set_fraction", round(max(0, min(1, state.get("progress", 0))), 2))
        self.update(self.level_box, "set_visible", not recording)
        if active and state.get("phase") == "running":
            for envelope, key in zip(self.meter_envelopes, ("input_db", "output_db")):
                envelope.set_db(state.get(key, -60))
            if self.meter_tick is None and any(meter.moving for meter in self.meter_envelopes):
                self.meter_frame_time = None
                self.meter_tick = self.add_tick_callback(self.animate_meters)
        else:
            self.reset_meters()

    def animate_meters(self, widget, frame_clock):
        if self.closed:
            self.meter_tick = None
            return False
        now = frame_clock.get_frame_time() / 1_000_000
        elapsed = now - self.meter_frame_time if self.meter_frame_time is not None else 1 / 60
        self.meter_frame_time = now
        for meter, envelope in zip(self.levels, self.meter_envelopes):
            self.update(meter, "set_value", envelope.advance(elapsed))
        moving = any(meter.moving for meter in self.meter_envelopes)
        if not moving:
            self.meter_tick = None
            self.meter_frame_time = None
        return moving

    def reset_meters(self):
        if self.meter_tick is not None:
            self.remove_tick_callback(self.meter_tick)
            self.meter_tick = None
        self.meter_frame_time = None
        for meter, envelope in zip(self.levels, self.meter_envelopes):
            envelope.reset()
            self.update(meter, "set_value", 0.0)

    def tick(self):
        if self.closed:
            return False
        update = self.backend.take_update()
        if update is not None:
            self.state = update["state"]
            self.has_profile = update["has_profile"]
            if not self.initialized:
                self.initialized = True
                self.saved_source = update["settings"]["source"]
                self.mode = update["settings"]["mode"]
                self.precision = update["settings"].get("precision", DEFAULT_PRECISION)
                if self.state["active"] and self.state.get("task") == "filter":
                    self.mode = self.state.get("mode", self.mode)
                    self.precision = self.state.get("precision", self.precision)
                if self.precision not in PRECISIONS:
                    self.precision = DEFAULT_PRECISION
                self.variant.set_selected(PRECISIONS.index(self.precision))
                (self.voice_mode if self.mode == "voice" else self.noise_mode).set_active(True)
                if self.devices_loaded:
                    self.populate_devices(self.device_records, self.saved_source)
        while True:
            try:
                kind, result, error = self.backend.events.get_nowait()
            except queue.Empty:
                break
            if kind == "details":
                if error:
                    self.error = error
                else:
                    view, contents = result
                    view.get_buffer().set_text(contents)
            elif kind == "status-error":
                self.error = error
            else:
                self.complete(result, error, kind == "devices")
        if self.closing and not self.pending:
            if self.state["active"] and self.state.get("task") == "profile":
                self.async_call(self.controller.stop)
            else:
                self.closed = True
                self.backend.close()
                self.destroy()
                return False
        self.render()
        return True

    def on_close(self, *_):
        self.closing = True
        self.tick()
        return True


def main():
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        raise RuntimeError("No se puede acceder a la sesión gráfica. Abre Only Voice desde tu escritorio.")
    Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    application = Gtk.Application(application_id="io.onlyvoice.Desktop", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
    failures = []
    def activate(app):
        try:
            window = app.get_active_window()
            if window is None:
                window = Window(app)
            window.present()
        except Exception:
            traceback.print_exc()
            failures.append(True)
            app.quit()
    application.connect("activate", activate)
    result = application.run(None)
    return 1 if failures else result


if __name__ == "__main__":
    raise SystemExit(main())
