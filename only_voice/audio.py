"""Temporary PulseAudio/PipeWire routing and bounded microphone capture."""

from collections import deque
from contextlib import ExitStack
import json
import os
import queue
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path

import numpy as np

from .processing import FRAME_SIZE, RATE, frame_array
from .metering import LEVEL_INTERVAL

FRAME_BYTES = FRAME_SIZE * 4


def pactl(*arguments):
    try:
        result = subprocess.run(
            ["pactl", *arguments], capture_output=True, text=True, timeout=10, check=False
        )
    except FileNotFoundError as error:
        raise RuntimeError("Falta pactl. Instala las utilidades de PulseAudio.") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("El servidor de audio no responde a pactl.") from error
    if result.returncode:
        raise RuntimeError(f"pactl: {result.stderr.strip() or 'falló la conexión al servidor de audio'}")
    return result.stdout.strip()


def sources():
    return json.loads(pactl("--format=json", "list", "sources"))


def is_microphone(source):
    name = source["name"]
    return not name.endswith(".monitor") and not name.startswith("only_voice_")


def resolve_source(requested=None):
    name = requested if requested else pactl("get-default-source")
    for source in sources():
        if source["name"] == name:
            if not is_microphone(source):
                raise ValueError("Selecciona un micrófono físico en Configuración; evita monitores y Only Voice.")
            return name
    raise ValueError(f"No existe la entrada {name!r}. Actualiza los micrófonos desde Configuración.")


class VirtualMicrophone:
    def __init__(self, rate=RATE):
        self.rate = rate
        token = uuid.uuid4().hex[:10]
        self.sink = f"only_voice_{token}_sink"
        self.source = f"only_voice_{token}_mic"
        self.modules = []

    def _load(self, module, *arguments):
        index = pactl("load-module", module, *arguments)
        if not index.isdigit():
            raise RuntimeError("El servidor no devolvió un identificador de módulo válido.")
        self.modules.append(index)

    def __enter__(self):
        try:
            self._load(
                "module-null-sink", f"sink_name={self.sink}",
                "sink_properties=device.description=Only_Voice_Processing",
                f"rate={self.rate}", "channels=1", "channel_map=mono", "format=float32le",
            )
            self._load(
                "module-remap-source", f"master={self.sink}.monitor",
                f"source_name={self.source}", "source_properties=device.description=Only_Voice",
                f"rate={self.rate}", "channels=1", "channel_map=mono", "remix=no",
            )
        except BaseException:
            self.close()
            raise
        return self

    def close(self):
        while self.modules:
            index = self.modules.pop()
            try:
                pactl("unload-module", index)
            except RuntimeError as error:
                print(f"No se pudo retirar el módulo {index}: {error}", file=sys.stderr)

    def __exit__(self, *_):
        self.close()


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            if data:
                raise RuntimeError("El flujo de audio terminó en mitad de un bloque.")
            return None
        data.extend(chunk)
    return bytes(data)


def put_latest(frames, value):
    """Single producer, single consumer. Drop old audio rather than grow latency."""
    try:
        frames.put_nowait(value)
    except queue.Full:
        try:
            frames.get_nowait()
        except queue.Empty:
            pass
        frames.put_nowait(value)


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            stream.close()


def record_reference(destination, seconds=15, requested_source=None, on_event=None):
    """Capture a bounded PCM16 sample; the caller controls retention of the WAV."""
    if not 5 <= seconds <= 60:
        raise ValueError("La grabación debe durar entre 5 y 60 segundos.")
    if Path(destination).exists():
        raise FileExistsError(f"Ya existe la grabación {destination}.")
    if not shutil.which("parec"):
        raise RuntimeError("Falta parec. Instala las utilidades de PulseAudio.")
    source = resolve_source(requested_source)
    print(f"Referencia de voz desde: {source}.\n"
          f"Habla tú solo durante {seconds} segundos, con volumen natural.\n"
          "La muestra temporal se elimina después de crear el perfil.", file=sys.stderr)
    for remaining in (3, 2, 1):
        if on_event:
            on_event("countdown", message=f"Empieza a hablar en {remaining}…", progress=0.0)
        print(f"Comienza en {remaining}…", file=sys.stderr, flush=True)
        time.sleep(1)
    print("Grabando: habla ahora.", file=sys.stderr, flush=True)
    if on_event:
        on_event("recording", message=f"Habla con naturalidad durante {seconds} segundos.", progress=0.0)
    target_bytes = 16_000 * 2 * seconds
    data = bytearray()
    last_progress = 0.0
    with tempfile.TemporaryFile() as errors:
        capture = subprocess.Popen(
            ["parec", "--record", "--raw", "--format=s16le", "--rate=16000",
             "--channels=1", f"--device={source}", "--client-name=Only Voice Enrollment"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors, bufsize=0,
        )
        try:
            descriptor = capture.stdout.fileno()
            os.set_blocking(descriptor, False)
            deadline = time.monotonic() + seconds + 5
            while len(data) < target_bytes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("La grabación no recibió suficiente audio del micrófono.")
                if not select.select([descriptor], [], [], min(remaining, 1))[0]:
                    continue
                try:
                    chunk = os.read(descriptor, min(65536, target_bytes - len(data)))
                except BlockingIOError:
                    continue
                if not chunk:
                    errors.seek(0)
                    message = errors.read(4096).decode(errors="replace").strip()
                    raise RuntimeError(f"La grabación se interrumpió. {message}".strip())
                data.extend(chunk)
                if on_event and (len(data) == target_bytes or time.monotonic() - last_progress >= 0.1):
                    progress = len(data) / target_bytes
                    on_event("recording", message=f"Sigue hablando… {max(0, seconds - int(progress * seconds))} s",
                             progress=progress)
                    last_progress = time.monotonic()
        finally:
            stop_process(capture)
    with Path(destination).open("xb") as file:
        with wave.open(file, "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(16_000)
            recording.writeframes(data)
    print("Muestra capturada. Calculando el perfil de voz…", file=sys.stderr, flush=True)


class AudioStream:
    def __init__(self, source, sink, rate=RATE, frame_size=FRAME_SIZE):
        self.source, self.sink = source, sink
        self.rate, self.frame_size = rate, frame_size
        self.frames = queue.Queue(maxsize=3)
        self.stopping = threading.Event()
        self.resources = ExitStack()

    def __enter__(self):
        block_ms = int(self.frame_size * 1000 / self.rate)
        common = ["--raw", "--format=float32le", f"--rate={self.rate}", "--channels=1",
                  f"--latency-msec={max(20, block_ms * 2)}", f"--process-time-msec={block_ms}",
                  "--client-name=Only Voice"]
        try:
            for binary in ("parec", "pacat"):
                if not shutil.which(binary):
                    raise RuntimeError(f"Falta {binary}. Instala las utilidades de PulseAudio.")
            self.capture_errors = self.resources.enter_context(tempfile.TemporaryFile())
            self.playback_errors = self.resources.enter_context(tempfile.TemporaryFile())
            self.playback = subprocess.Popen(
                ["pacat", "--playback", f"--device={self.sink}", *common],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=self.playback_errors, bufsize=0,
            )
            self.resources.callback(stop_process, self.playback)
            self.capture = subprocess.Popen(
                ["parec", "--record", f"--device={self.source}", *common],
                stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                stderr=self.capture_errors, bufsize=0,
            )
            self.resources.callback(stop_process, self.capture)
            os.set_blocking(self.playback.stdin.fileno(), False)
            self.reader = threading.Thread(target=self._capture, daemon=True)
            self.reader.start()
        except BaseException:
            self.resources.close()
            raise
        return self

    def _capture(self):
        sequence = 0
        try:
            while not self.stopping.is_set():
                data = read_exact(self.capture.stdout, self.frame_size * 4)
                if data is None:
                    raise RuntimeError("Se ha desconectado la entrada de audio.")
                put_latest(self.frames, (sequence, data))
                sequence += 1
        except Exception as error:
            if not self.stopping.is_set():
                put_latest(self.frames, error)

    def read(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.playback.poll() is not None:
                raise RuntimeError("Se ha desconectado la salida de audio.")
            try:
                value = self.frames.get(timeout=0.25)
            except queue.Empty:
                if self.capture.poll() is not None:
                    raise RuntimeError("El proceso de captura ha terminado.")
                continue
            if isinstance(value, Exception):
                raise value
            sequence, data = value
            frame = np.frombuffer(data, dtype="<f4").astype(np.float32)
            return sequence, frame_array(frame, self.frame_size)
        raise RuntimeError("No se recibe audio del micrófono desde hace 3 segundos.")

    def write(self, frame):
        frame = np.asarray(frame, dtype=np.float32)
        if frame.ndim != 1 or not np.isfinite(frame).all():
            raise ValueError("Audio de salida no válido.")
        data = memoryview(np.clip(frame, -1, 1).astype("<f4").tobytes())
        descriptor = self.playback.stdin.fileno()
        deadline = time.monotonic() + 0.25
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [descriptor], [], remaining)[1]:
                raise RuntimeError("La salida de audio está bloqueada; se detiene para evitar retrasos.")
            try:
                written = os.write(descriptor, data)
            except BlockingIOError:
                continue
            if written == 0:
                raise RuntimeError("No se puede escribir en la salida de audio.")
            data = data[written:]

    def __exit__(self, error_type, *_):
        self.stopping.set()
        # Stop children before closing their pipes or joining the blocking reader.
        for process in (self.capture, self.playback):
            if process.poll() is None:
                process.terminate()
        try:
            if error_type is not None and error_type is not KeyboardInterrupt:
                for log in (self.capture_errors, self.playback_errors):
                    log.seek(0)
                    message = log.read(4096).decode(errors="replace").strip()
                    if message:
                        print(message, file=sys.stderr)
        finally:
            self.resources.close()
            self.reader.join(timeout=2)


def run_stream(processor, requested_source=None, on_event=None, *, routing=None, stream_factory=None, source_resolver=None):
    # Resolve before creating a source to avoid capturing our own output.
    source = (source_resolver or resolve_source)(requested_source)
    rate = getattr(processor, "rate", RATE)
    frame_size = getattr(processor, "frame_size", FRAME_SIZE)
    block_ms = frame_size * 1000 / rate
    durations = []
    for _ in range(20):
        start = time.perf_counter()
        processor.process(np.zeros(frame_size, dtype=np.float32))
        durations.append(time.perf_counter() - start)
    processor.reset()
    average = sum(durations[5:]) / len(durations[5:])
    if average >= frame_size / rate:
        raise RuntimeError(
            f"El motor tarda {average * 1000:.1f} ms por bloque de {block_ms:g} ms en este equipo. "
            "No puede seguir el audio en tiempo real."
        )
    with (routing or VirtualMicrophone)(rate) as microphone, (stream_factory or AudioStream)(source, microphone.sink, rate, frame_size) as stream:
        print(f"Entrada: {source}\nEn la llamada selecciona el micrófono Only_Voice.\n"
              "Desactiva el filtro desde el icono de la bandeja para retirar el micrófono virtual.", file=sys.stderr)
        timings = deque(maxlen=500)
        previous = -1
        dropped = 0
        last_report = time.monotonic()
        last_event = 0.0
        ready = False
        input_energy = output_energy = 0.0
        input_samples = output_samples = 0
        while True:
            sequence, frame = stream.read()
            if sequence != previous + 1:
                dropped += sequence - previous - 1
                processor.reset()
            previous = sequence
            start = time.perf_counter()
            result = processor.process(frame)
            timings.append((time.perf_counter() - start) * 1000)
            if result.size:
                stream.write(result)
            if on_event:
                # Include every block in the displayed RMS window, including
                # short syllables between updates. This only measures the audio.
                input_energy += float(np.dot(frame, frame))
                output_energy += float(np.dot(result, result))
                input_samples += frame.size
                output_samples += result.size
            if on_event and (not ready or time.monotonic() - last_event >= LEVEL_INTERVAL):
                input_db = float(10 * np.log10(max(input_energy / max(1, input_samples), 1e-18)))
                output_db = float(10 * np.log10(max(output_energy / max(1, output_samples), 1e-18)))
                on_event("running", message=f"Selecciona {microphone.source if sys.platform == 'win32' else 'Only_Voice'} como micrófono en tu llamada.",
                         source=source, virtual_source=microphone.source,
                         input_db=input_db, output_db=output_db,
                         processing_ms=sum(timings) / len(timings), dropped=dropped)
                ready = True
                last_event = time.monotonic()
                input_energy = output_energy = 0.0
                input_samples = output_samples = 0
            if time.monotonic() - last_report >= 5:
                print(f"Procesamiento medio: {sum(timings) / len(timings):.2f} ms/bloque; "
                      f"bloques descartados: {dropped}. Esto no mide la latencia total.",
                      file=sys.stderr)
                last_report = time.monotonic()
