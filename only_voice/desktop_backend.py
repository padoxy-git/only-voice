"""Desktop I/O runs here, never in GTK's event loop. No audio/ML imports."""

import json
import queue
import subprocess
import threading

from .application import Application
from .metering import LEVEL_INTERVAL


def microphones():
    """Query PulseAudio directly, without booting the audio Python environment."""
    try:
        result = subprocess.run(["pactl", "--format=json", "list", "sources"],
                                capture_output=True, text=True, timeout=5)
    except FileNotFoundError as error:
        raise RuntimeError("Falta pactl. Instala las utilidades de PulseAudio.") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("El servidor de audio no responde. Pulsa Actualizar para reintentar.") from error
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "No se pudo conectar con el servidor de audio.")
    sources = json.loads(result.stdout)
    return [{"name": source["name"], "description": source.get("description") or source["name"]}
            for source in sources if source.get("name") and not source["name"].endswith(".monitor")
            and not source["name"].startswith("only_voice_")]


class DesktopBackend:
    def __init__(self, controller=None, interval=LEVEL_INTERVAL):
        self.controller = controller or Application()
        self.interval = interval
        self.events = queue.Queue()
        self._lock = threading.Lock()
        self._snapshot = None
        self._dirty = False
        self._stop = threading.Event()
        self._poll_thread = threading.Thread(target=self._poll, daemon=True, name="only-voice-status")
        self._poll_thread.start()

    def _poll(self):
        previous_error = None
        while not self._stop.is_set():
            try:
                snapshot = {"state": self.controller.status(),
                            "has_profile": self.controller.paths.profile.is_file(),
                            "settings": self.controller.settings()}
                with self._lock:
                    if self._snapshot != snapshot:
                        self._snapshot = snapshot
                        self._dirty = True
                previous_error = None
            except Exception as error:
                if str(error) != previous_error:
                    self.events.put(("status-error", None, str(error)))
                    previous_error = str(error)
            self._stop.wait(self.interval)

    def take_update(self):
        with self._lock:
            if not self._dirty:
                return None
            self._dirty = False
            return self._snapshot

    def submit(self, kind, function):
        def work():
            try:
                result, error = function(), None
            except Exception as caught:
                result, error = None, str(caught)
            if not self._stop.is_set():
                self.events.put((kind, result, error))
        threading.Thread(target=work, daemon=True, name=f"only-voice-{kind}").start()

    def close(self):
        # Closing a window must not stop a running call's filter.
        self._stop.set()
