"""Shared desktop/CLI control of one local audio worker."""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import threading
import uuid

from .variants import DEFAULT_PRECISION, PRECISIONS

PROJECT = Path(__file__).resolve().parents[1]
WINDOWS = sys.platform == "win32"


def data_root():
    override = os.environ.get("ONLY_VOICE_DATA")
    if override:
        return Path(override)
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Only Voice"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "only-voice"
ACTIVE_PHASES = {"starting", "running", "countdown", "recording", "processing", "stopping"}


def audio_python():
    """GTK uses system Python; audio keeps its prepared, isolated dependencies."""
    if getattr(sys, "frozen", False):
        return sys.executable
    for environment in (".venv-voice", ".venv"):
        executable = PROJECT / environment / "bin/python"
        if executable.is_file() and os.access(executable, os.X_OK):
            return str(executable)
    return sys.executable


@dataclass(frozen=True)
class Paths:
    root: Path = None

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root if self.root is not None else data_root()).resolve())

    @property
    def runtime(self):
        return self.root / ".runtime"

    @property
    def models(self):
        return self.root / "models/voxlock/onnx"

    @property
    def profile(self):
        return self.root / "profiles/me.npz"

    def file(self, name):
        return self.runtime / name


def read_json(path, default=None):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else (default or {})
    except (OSError, ValueError):
        return default or {}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def lock(path, blocking=True):
    Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        if WINDOWS:
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write("0")
                stream.flush()
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if not blocking:
                        raise BlockingIOError("Only Voice ya está activo") from error
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(stream, flags)
            yield


def process_identity(pid):
    if WINDOWS:
        import psutil
        try:
            return str(psutil.Process(int(pid)).create_time())
        except psutil.Error:
            return None
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return fields[19]  # /proc stat field 22: start time since boot
    except (OSError, ValueError, IndexError):
        return None


def is_worker(state, paths):
    pid = state.get("pid")
    if not pid or not state.get("identity") or process_identity(pid) != state["identity"]:
        return False
    try:
        if WINDOWS:
            import psutil
            try:
                arguments = psutil.Process(int(pid)).cmdline()
            except psutil.Error:
                return False
        else:
            arguments = Path(f"/proc/{int(pid)}/cmdline").read_bytes().decode().split("\0")
        position = arguments.index("--project")
        return ("only_voice.worker" in arguments or "--worker" in arguments) and arguments[position + 1] == str(paths.root)
    except (OSError, ValueError, IndexError):
        return False


class Application:
    def __init__(self, paths=None):
        self.paths = paths or Paths()
        self.children = []
        self.children_lock = threading.Lock()

    def settings(self):
        settings = {"source": None, "mode": "voice", "precision": DEFAULT_PRECISION,
                    **read_json(self.paths.file("settings.json"))}
        if settings["mode"] not in ("voice", "noise"):
            settings["mode"] = "voice"
        if not isinstance(settings["source"], str) or not settings["source"]:
            settings["source"] = None
        if settings["precision"] not in PRECISIONS:
            settings["precision"] = DEFAULT_PRECISION
        return settings

    def save_settings(self, **changes):
        settings = self.settings()
        settings.update(changes)
        write_json(self.paths.file("settings.json"), settings)

    def status(self):
        with self.children_lock:
            for child in self.children[:]:
                if child.poll() is not None:
                    self.children.remove(child)
        state = {"phase": "stopped", **read_json(self.paths.file("state.json"))}
        active = is_worker(state, self.paths)
        if state.get("phase") in ACTIVE_PHASES and not active:
            state = {**state, "phase": "stopped", "message": "El filtro está detenido."}
        return {**state, "active": active}

    def details(self):
        try:
            with self.paths.file("worker.log").open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - 12000))
                return stream.read().decode(errors="replace")
        except OSError:
            return "Todavía no hay un registro de actividad."

    def start(self, source=None, mode=None, precision=None):
        settings = self.settings()
        source = source if source is not None else settings["source"]
        mode = mode or settings["mode"]
        precision = precision if precision is not None else settings["precision"]
        if precision not in PRECISIONS:
            raise ValueError(f"Variante de voz desconocida: {precision}.")
        state = self._launch("filter", source, mode, precision=precision)
        self.save_settings(source=source, mode=mode, precision=precision)
        return state

    def register(self, source=None, wav=None):
        source = source if source is not None else self.settings()["source"]
        return self._launch("profile", source, "voice", wav)

    def _launch(self, task, source, mode, wav=None, precision=DEFAULT_PRECISION):
        with lock(self.paths.file("launch.lock")):
            state = self.status()
            if state["active"]:
                if task == "filter" and state.get("task") == "filter":
                    if (state.get("mode") != mode or state.get("requested_source") != source
                            or (mode == "voice" and state.get("precision", DEFAULT_PRECISION) != precision)):
                        raise RuntimeError("El filtro ya está activo. Deténlo antes de cambiar el modo, la variante o el micrófono.")
                    return state
                raise RuntimeError("Detén el filtro o cancela la grabación antes de continuar.")
            self.paths.file("stop").unlink(missing_ok=True)
            command = ([sys.executable, "--worker"] if getattr(sys, "frozen", False)
                       else [audio_python(), "-m", "only_voice.worker"])
            command += ["--project", str(self.paths.root),
                       "--task", task, "--mode", mode, "--precision", precision]
            if source:
                command += ["--source", source]
            if wav:
                command += ["--wav", str(Path(wav).resolve())]
            log_path = self.paths.file("worker.log")
            if log_path.exists() and log_path.stat().st_size > 2_000_000:
                os.replace(log_path, log_path.with_suffix(".previous.log"))
            descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "ab", buffering=0) as log:
                child = subprocess.Popen(command, cwd=PROJECT, stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=log, start_new_session=not WINDOWS,
                                         creationflags=subprocess.CREATE_NO_WINDOW if WINDOWS else 0)
            with self.children_lock:
                self.children.append(child)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    state = self.status()
                    if state.get("pid") == child.pid:
                        if state.get("phase") == "error":
                            raise RuntimeError(state.get("message", "No se pudo iniciar."))
                        return state
                    if child.poll() is not None:
                        raise RuntimeError("No se pudo iniciar Only Voice. Consulta los detalles de actividad.")
                    time.sleep(0.05)
                raise RuntimeError("Only Voice no ha respondido al iniciar.")
            except BaseException:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
                raise

    def stop(self):
        state = self.status()
        if not state["active"]:
            return state
        # Check start time and command again immediately before signalling. Never
        # signal an unrelated process just because a stale PID file mentions it.
        if is_worker(state, self.paths):
            try:
                if WINDOWS:
                    self.paths.file("stop").touch()
                else:
                    os.kill(state["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = self.status()
            if not result["active"]:
                return result
            time.sleep(0.05)
        if WINDOWS and is_worker(state, self.paths):
            # Downloads and ONNX initialization cannot poll the stop marker.
            # Windows closes WASAPI handles when terminating this verified worker.
            import psutil
            process = psutil.Process(state["pid"])
            if str(process.create_time()) == state["identity"]:
                process.terminate()
                process.wait(timeout=5)
                write_json(self.paths.file("state.json"), {**state, "phase": "stopped",
                           "message": "Operación cancelada.", "input_db": -60, "output_db": -60})
                return self.status()
        raise RuntimeError("El proceso sigue cerrando el audio. Vuelve a consultar el estado.")


def wait_ready(application, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = application.status()
        if state.get("phase") == "running" or not state["active"]:
            if state.get("phase") == "error":
                raise RuntimeError(state.get("message", "No se pudo iniciar el filtro."))
            return state
        time.sleep(0.1)
    return application.status()
