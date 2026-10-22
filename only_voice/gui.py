"""Small native control window. Audio work always runs outside the Tk thread."""

import queue
import threading

from .application import Application
from .audio import is_microphone, sources
from .variants import DEFAULT_PRECISION, PRECISIONS, VARIANTS

BACKGROUND = "#f4f6fa"
SURFACE = "#ffffff"
TEXT = "#19263b"
MUTED = "#64748b"
LINE = "#e2e8f0"
ACCENT = "#315ee8"


from .gui_state import presentation


class Window:
    def __init__(self, root, tk, ttk, application=None):
        self.root, self.tk, self.ttk = root, tk, ttk
        self.application = application or Application()
        self.events = queue.Queue()
        self.pending = False
        self.closing = False
        self.error = None
        self.device_map = {"Micrófono del sistema": None}
        self.available_sources = set()
        self.devices_loaded = False
        self.refreshing = False
        settings = self.application.settings()
        self.mode = tk.StringVar(value=settings["mode"])
        self.precision = tk.StringVar(value=VARIANTS[settings.get("precision", DEFAULT_PRECISION)]["label"])
        self.device = tk.StringVar(value="Micrófono del sistema")
        self.description = tk.StringVar()
        root.title("Only Voice")
        height = max(480, min(830, root.winfo_screenheight() - 90))
        width = max(450, min(610, root.winfo_screenwidth() - 60))
        root.geometry(f"{width}x{height}")
        root.minsize(min(550, width), min(650, height))
        root.configure(background=BACKGROUND)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._styles()
        self._build()
        self.refresh_devices()
        self.tick()
        if self.application.status()["active"]:
            root.after_idle(lambda: self.scroller.yview_moveto(1.0))

    def _styles(self):
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("TLabel", background=SURFACE, foreground=TEXT, font=("Sans", 11))
        style.configure("Muted.TLabel", foreground=MUTED, font=("Sans", 10))
        style.configure("Caption.TLabel", foreground=MUTED, font=("Sans", 10, "bold"))
        style.configure("TButton", font=("Sans", 10), padding=(12, 8), background=SURFACE, foreground=TEXT,
                        borderwidth=1, bordercolor=LINE, focuscolor=LINE)
        style.map("TButton", background=[("active", "#eef2ff")], foreground=[("disabled", "#94a3b8")])
        style.configure("Primary.TButton", font=("Sans", 12, "bold"), padding=(16, 14),
                        foreground="white", background=ACCENT, bordercolor=ACCENT, focuscolor="white")
        style.map("Primary.TButton", background=[("disabled", "#e2e8f0"), ("active", "#254cc9")],
                  foreground=[("disabled", "#64748b")])
        style.configure("Stop.TButton", font=("Sans", 12, "bold"), padding=(16, 14),
                        foreground="#ac253d", background="#fff0f2", bordercolor="#ffd8df", focuscolor="#ac253d")
        style.map("Stop.TButton", background=[("active", "#ffe2e8"), ("disabled", "#e2e8f0")])
        style.configure("TCombobox", font=("Sans", 11), padding=10, fieldbackground=SURFACE,
                        bordercolor=LINE, arrowcolor=MUTED)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)], foreground=[("readonly", TEXT)])
        style.configure("TRadiobutton", background=SURFACE, foreground=TEXT, font=("Sans", 11), padding=(0, 5))
        style.map("TRadiobutton", background=[("active", SURFACE)])
        style.configure("Level.Horizontal.TProgressbar", troughcolor="#edf1f6", background="#4f7bf3",
                        borderwidth=0, thickness=7)
        style.configure("Record.Horizontal.TProgressbar", troughcolor="#edf1f6", background=ACCENT,
                        borderwidth=0, thickness=7)
        self.root.option_add("*TCombobox*Listbox.font", ("Sans", 11))

    def card(self, parent, **grid):
        outer = self.tk.Frame(parent, background=SURFACE, highlightbackground=LINE, highlightthickness=1)
        outer.grid(sticky="ew", **grid)
        inner = self.ttk.Frame(outer, style="Card.TFrame", padding=20)
        inner.pack(fill="both", expand=True)
        inner.columnconfigure(0, weight=1)
        return inner

    def _build(self):
        main = self.ttk.Frame(self.root, padding=(26, 24))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        header = self.ttk.Frame(main)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.columnconfigure(1, weight=1)
        mark = self.tk.Canvas(header, width=52, height=52, bg=BACKGROUND, highlightthickness=0)
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        mark.create_oval(0, 0, 52, 52, fill="#e6edff", outline="")
        mark.create_line(18, 23, 18, 29, fill=ACCENT, width=3, capstyle="round")
        mark.create_line(26, 16, 26, 36, fill=ACCENT, width=4, capstyle="round")
        mark.create_line(34, 21, 34, 31, fill=ACCENT, width=3, capstyle="round")
        self.tk.Label(header, text="Only Voice", bg=BACKGROUND, fg=TEXT,
                      font=("Sans", 23, "bold"), anchor="w").grid(row=0, column=1, sticky="w")
        self.tk.Label(header, text="Tu voz, en primer plano.", bg=BACKGROUND, fg=MUTED,
                      font=("Sans", 10), anchor="w").grid(row=1, column=1, sticky="w")
        self.badge = self.tk.Label(header, text="Detenido", bg="#e8edf4", fg=MUTED,
                                   padx=10, pady=5, font=("Sans", 9, "bold"))
        self.badge.grid(row=0, column=2, rowspan=2, sticky="e")

        viewport = self.ttk.Frame(main)
        viewport.grid(row=1, column=0, sticky="nsew")
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        self.scroller = self.tk.Canvas(viewport, background=BACKGROUND, highlightthickness=0, height=430)
        self.scroller.grid(row=0, column=0, sticky="nsew")
        scrollbar = self.ttk.Scrollbar(viewport, orient="vertical", command=self.scroller.yview)
        self.scroller.configure(yscrollcommand=scrollbar.set)
        body = self.ttk.Frame(self.scroller)
        body.columnconfigure(0, weight=1)
        body_window = self.scroller.create_window(0, 0, window=body, anchor="nw")

        def layout(_=None):
            self.scroller.configure(scrollregion=self.scroller.bbox("all"))
            if body.winfo_reqheight() > self.scroller.winfo_height():
                scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
            else:
                scrollbar.grid_remove()
        body.bind("<Configure>", layout)
        def resize(event):
            self.scroller.itemconfigure(body_window, width=event.width)
            for name in ("message", "description_label", "variant_description"):
                label = getattr(self, name, None)
                if label is not None:
                    label.configure(wraplength=max(180, event.width - 44))
            layout()
        self.scroller.bind("<Configure>", resize)
        def scroll(event):
            if event.widget is not self.combo and body.winfo_reqheight() > self.scroller.winfo_height():
                direction = -1 if getattr(event, "num", None) == 4 else 1
                if getattr(event, "delta", 0):
                    direction = -1 if event.delta > 0 else 1
                self.scroller.yview_scroll(direction * 2, "units")
        self.root.bind("<MouseWheel>", scroll)
        self.root.bind("<Button-4>", scroll)
        self.root.bind("<Button-5>", scroll)

        audio = self.card(body, row=0, column=0, pady=(0, 12))
        self.ttk.Label(audio, text="MICRÓFONO", style="Caption.TLabel").grid(row=0, column=0, sticky="w")
        self.refresh_button = self.ttk.Button(audio, text="Actualizar", command=self.refresh_devices)
        self.refresh_button.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.combo = self.ttk.Combobox(audio, state="readonly", textvariable=self.device,
                                       values=list(self.device_map))
        self.combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 12))
        modes = self.ttk.Frame(audio, style="Card.TFrame")
        modes.grid(row=2, column=0, columnspan=2, sticky="w")
        self.radios = [self.ttk.Radiobutton(modes, text=text, value=value, variable=self.mode)
                       for text, value in (("Solo mi voz", "voice"), ("Reducir ruido", "noise"))]
        for column, radio in enumerate(self.radios):
            radio.grid(row=0, column=column, padx=(0, 22), sticky="w")
        self.description_label = self.ttk.Label(audio, textvariable=self.description, style="Muted.TLabel", wraplength=460)
        self.description_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.variant_box = self.ttk.Frame(audio, style="Card.TFrame")
        self.variant_box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.variant_box.columnconfigure(0, weight=1)
        self.ttk.Label(self.variant_box, text="VARIANTE DE VOZ", style="Caption.TLabel").grid(row=0, column=0, sticky="w")
        self.variant = self.ttk.Combobox(self.variant_box, state="readonly", textvariable=self.precision,
                                        values=[VARIANTS[key]["label"] for key in PRECISIONS])
        self.variant.grid(row=1, column=0, sticky="ew", pady=(8, 5))
        self.variant_description = self.ttk.Label(self.variant_box, style="Muted.TLabel", wraplength=460)
        self.variant_description.grid(row=2, column=0, sticky="w")
        self.ttk.Label(self.variant_box, text="La primera vez se descarga el modelo. Tu perfil sirve para las cuatro variantes.",
                       style="Muted.TLabel", wraplength=400).grid(row=3, column=0, sticky="w", pady=(5, 0))

        voice = self.card(body, row=1, column=0, pady=(0, 12))
        self.ttk.Label(voice, text="Tu voz", font=("Sans", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.profile_label = self.ttk.Label(voice, style="Muted.TLabel")
        self.profile_label.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.profile_button = self.ttk.Button(voice, command=self.register)
        self.profile_button.grid(row=0, column=1, rowspan=2, padx=(12, 0), sticky="e")

        status = self.card(body, row=2, column=0, pady=(0, 16))
        self.title = self.ttk.Label(status, font=("Sans", 15, "bold"))
        self.title.grid(row=0, column=0, sticky="w")
        self.message = self.ttk.Label(status, style="Muted.TLabel", wraplength=460, justify="left")
        self.message.grid(row=1, column=0, sticky="w", pady=(7, 14))
        self.progress = self.ttk.Progressbar(status, style="Record.Horizontal.TProgressbar", maximum=1)
        self.progress.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.level_frame = self.ttk.Frame(status, style="Card.TFrame")
        self.level_frame.grid(row=3, column=0, sticky="ew")
        self.level_frame.columnconfigure(1, weight=1)
        self.levels = []
        for row, name in enumerate(("Entrada", "Salida")):
            self.ttk.Label(self.level_frame, text=name, style="Muted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 15), pady=5)
            level = self.ttk.Progressbar(self.level_frame, style="Level.Horizontal.TProgressbar", maximum=60)
            level.grid(row=row, column=1, sticky="ew", pady=5)
            self.levels.append(level)

        self.action = self.ttk.Button(main, style="Primary.TButton", command=self.toggle)
        self.action.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        footer = self.ttk.Frame(main)
        footer.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        footer.columnconfigure(0, weight=1)
        self.tk.Label(footer, text="●  Procesamiento local", bg=BACKGROUND, fg=MUTED,
                      font=("Sans", 9)).grid(row=0, column=0, sticky="w")
        self.ttk.Button(footer, text="Ver detalles", command=self.details).grid(row=0, column=1, sticky="e")
        self.tk.Label(main, text="Al cerrar la ventana, el filtro sigue activo.", bg=BACKGROUND,
                      fg=MUTED, font=("Sans", 9)).grid(row=4, column=0, sticky="w", pady=(10, 0))

    def async_call(self, function, kind="job"):
        if kind == "job":
            self.pending = True
            self.error = None

        def work():
            try:
                self.events.put((kind, function(), None))
            except Exception as error:
                self.events.put((kind, None, str(error)))
        threading.Thread(target=work, daemon=True).start()

    def refresh_devices(self):
        if self.refreshing:
            return
        self.refreshing = True
        self.refresh_button.configure(state="disabled")
        self.async_call(lambda: [source for source in sources() if is_microphone(source)], "devices")

    def selected_source(self):
        return self.device_map.get(self.device.get())

    def save_selection(self):
        self.application.save_settings(source=self.selected_source(), mode=self.mode.get(), precision=self.selected_precision())

    def selected_precision(self):
        return next(key for key in PRECISIONS if VARIANTS[key]["label"] == self.precision.get())

    def toggle(self):
        if self.pending:
            return
        if self.application.status()["active"]:
            self.async_call(self.application.stop)
        else:
            self.scroller.yview_moveto(1.0)
            self.save_selection()
            source, mode, precision = self.selected_source(), self.mode.get(), self.selected_precision()
            self.async_call(lambda: self.application.start(source, mode, precision))

    def register(self):
        if not self.pending and not self.application.status()["active"]:
            self.scroller.yview_moveto(1.0)
            self.save_selection()
            self.async_call(lambda: self.application.register(self.selected_source()))

    def details(self):
        dialog = self.tk.Toplevel(self.root)
        dialog.title("Detalles de actividad · Only Voice")
        dialog.geometry("720x390")
        text = self.tk.Text(dialog, background="#172033", foreground="#e2e8f0",
                            insertbackground="white", font=("Monospace", 10), wrap="word", padx=16, pady=16)
        text.pack(fill="both", expand=True)
        content = self.application.details()
        if self.error:
            content = self.error + "\n\n" + content
        text.insert("1.0", content)
        text.configure(state="disabled")

    def tick(self):
        while True:
            try:
                kind, result, error = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "job":
                self.pending = False
            if kind == "devices":
                self.refreshing = False
            if error:
                self.error = error
            elif kind == "devices":
                self.error = None
                previous = self.selected_source() if self.devices_loaded else self.application.settings()["source"]
                self.device_map = {"Micrófono del sistema": None}
                self.available_sources = {source["name"] for source in result}
                for source in result:
                    label = source.get("description") or source["name"]
                    base, counter = label, 2
                    while label in self.device_map:
                        label = f"{base} ({counter})"
                        counter += 1
                    self.device_map[label] = source["name"]
                if previous and previous not in self.available_sources:
                    self.device_map["Micrófono guardado · no conectado"] = previous
                self.combo.configure(values=list(self.device_map))
                self.device.set(next(label for label, name in self.device_map.items() if name == previous))
                self.devices_loaded = True
        state = self.application.status()
        if self.closing and not self.pending:
            if state["active"] and state.get("task") == "profile":
                self.async_call(self.application.stop)
            else:
                self.root.destroy()
                return
        active = state["active"]
        busy = active or self.pending
        has_profile = self.application.paths.profile.is_file()
        display = presentation(state, has_profile, self.mode.get())
        if self.error:
            display.update(title="No se pudo completar", badge="Revisar", message=self.error)
        self.badge.configure(text=display["badge"], bg="#e5f5ee" if state.get("phase") == "running" else "#e8edf4",
                             fg="#16724f" if state.get("phase") == "running" else MUTED)
        self.title.configure(text=display["title"])
        self.message.configure(text=display["message"])
        self.description.set("Conserva la voz de tu perfil y atenúa los demás sonidos." if self.mode.get() == "voice"
                             else "Reduce el ruido de fondo. También deja pasar otras voces.")
        self.profile_label.configure(text="Perfil guardado en este equipo" if has_profile else "Graba 15 segundos hablando tú solo")
        source = self.selected_source()
        missing = source is not None and source not in self.available_sources
        self.profile_button.configure(text="Actualizar mi voz" if has_profile else "Grabar mi voz",
                                      state="disabled" if busy or not self.devices_loaded or missing else "normal")
        self.combo.configure(state="disabled" if busy else "readonly")
        self.variant.configure(state="disabled" if busy else "readonly")
        self.variant_description.configure(text=VARIANTS[self.selected_precision()]["description"])
        if self.mode.get() == "voice":
            self.variant_box.grid()
        else:
            self.variant_box.grid_remove()
        self.refresh_button.configure(state="disabled" if busy or self.refreshing else "normal")
        for radio in self.radios:
            radio.configure(state="disabled" if busy else "normal")
        enabled = display["enabled"] and not self.pending and self.devices_loaded and (not missing or active)
        self.action.configure(text="Un momento…" if self.pending else display["action"],
                              style="Stop.TButton" if active else "Primary.TButton",
                              state="normal" if enabled else "disabled")
        if missing and not active:
            self.message.configure(text="El micrófono guardado no está conectado. Selecciona otra entrada.")
        if active and state.get("task") == "profile":
            self.progress.grid()
            self.progress["value"] = state.get("progress", 0)
            self.level_frame.grid_remove()
        else:
            self.progress.grid_remove()
            self.level_frame.grid()
        for level, key in zip(self.levels, ("input_db", "output_db")):
            level["value"] = max(0, min(60, state.get(key, -60) + 60)) if active else 0
        self.root.after(200, self.tick)

    def close(self):
        self.closing = True


def launch_tk():
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as error:
        raise RuntimeError("Falta Tk para abrir la ventana. Usa el Python preparado por ./voice.sh.") from error
    try:
        root = tk.Tk()
    except tk.TclError as error:
        raise RuntimeError("No se puede abrir la ventana. Ejecuta only-voice gui desde tu sesión gráfica "
                           "(Tk necesita X11 o XWayland).") from error
    Window(root, tk, ttk)
    root.mainloop()
    return 0
