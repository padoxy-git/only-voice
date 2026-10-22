"""Select a desktop toolkit independently of the audio Python environment."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from .application import Paths, PROJECT


def gtk_python():
    candidates = dict.fromkeys((sys.executable, "/usr/bin/python3", "/bin/python3"))
    for executable in candidates:
        if not Path(executable).is_file():
            continue
        try:
            result = subprocess.run(
                [executable, "-c", "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if result.returncode == 0:
                return executable
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def launch():
    paths = Paths()
    paths.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = paths.file("gui.log")
    if log_path.exists() and log_path.stat().st_size > 1_000_000:
        os.replace(log_path, paths.file("gui.previous.log"))
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", buffering=1) as log:
        try:
            executable = gtk_python()
            if executable:
                environment = os.environ.copy()
                environment["PYTHONPATH"] = str(PROJECT) + os.pathsep + environment.get("PYTHONPATH", "")
                # A Tk/X11 setting inherited from a terminal must not force GTK onto X11.
                if environment.get("WAYLAND_DISPLAY"):
                    environment["GDK_BACKEND"] = "wayland"
                # This small control window needs no Vulkan/GL context. Avoid
                # graphics-driver startup and preserve an explicit user choice.
                environment.setdefault("GSK_RENDERER", "cairo")
                log.write(f"Abriendo interfaz GTK 4 (renderizador: {environment['GSK_RENDERER']}).\n")
                result = subprocess.run([executable, "-m", "only_voice.gtk_gui"], cwd=PROJECT,
                                        env=environment, stdout=log, stderr=log)
                if result.returncode:
                    raise RuntimeError(f"La ventana no pudo iniciarse. Consulta {log_path}.")
                return 0
            if os.environ.get("DISPLAY"):
                from .gui import launch_tk
                log.write("Abriendo interfaz Tk/X11.\n")
                return launch_tk()
            raise RuntimeError("Para abrir la ventana en Wayland instala GTK 4 y PyGObject "
                               "(Arch: sudo pacman -S gtk4 python-gobject).")
        except Exception as error:
            traceback.print_exc(file=log)
            notifier = shutil.which("notify-send")
            if notifier:
                try:
                    subprocess.run([notifier, "--urgency=critical", "Only Voice", str(error)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            raise
