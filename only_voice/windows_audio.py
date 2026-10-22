"""WASAPI capture and playback into the user-installed VB-CABLE driver."""
from contextlib import ExitStack
from pathlib import Path
import queue
import threading
import time
import wave

import numpy as np
import sounddevice as sd

from .audio import put_latest, run_stream as process_stream

CABLE_URL = "https://vb-audio.com/Cable/"


def devices():
    hosts = sd.query_hostapis()
    return [(index, info) for index, info in enumerate(sd.query_devices())
            if hosts[info['hostapi']]['name'] == 'Windows WASAPI']


def microphones():
    return [{'name': info['name'], 'description': info['name']}
            for _, info in devices() if info['max_input_channels'] > 0
            and not any(word in info['name'].lower() for word in ('cable', 'stereo mix', 'mezcla estéreo'))]


def resolve_source(requested=None):
    available = microphones()
    if not available:
        raise RuntimeError('No hay micrófonos WASAPI. Comprueba los permisos de micrófono en Windows.')
    if requested:
        if requested not in [item['name'] for item in available]:
            raise RuntimeError('El micrófono guardado no está conectado. Actualiza y selecciona otra entrada.')
        return requested
    default = sd.query_devices(kind='input')['name']
    return default if default in [item['name'] for item in available] else available[0]['name']


def device_index(name, direction):
    for index, info in devices():
        if info['name'] == name and info[f'max_{direction}_channels']:
            return index
    raise RuntimeError(f'El dispositivo {name} se ha desconectado.')


class Cable:
    def __init__(self, rate):
        self.rate = rate

    def __enter__(self):
        outputs = [info['name'] for _, info in devices() if info['max_output_channels']
                   and 'cable input' in info['name'].lower()]
        if len(outputs) != 1:
            raise RuntimeError('Instala VB-CABLE desde el enlace de Configuración y reinicia Windows. '
                               'Se necesita una salida CABLE Input (VB-Audio Virtual Cable).')
        self.sink = outputs[0]
        self.source = 'CABLE Output (VB-Audio Virtual Cable)'
        return self

    def __exit__(self, *_):
        pass  # The driver belongs to the user; closing streams releases our routing.


class AudioStream:
    def __init__(self, source, sink, rate, frame_size):
        self.source, self.sink = source, sink
        self.rate, self.frame_size = rate, frame_size
        self.frames = queue.Queue(maxsize=3)
        self.resources = ExitStack()
        self.sequence = 0
        self.stopping = threading.Event()

    def _capture(self, data, frames, timing, status):
        if self.stopping.is_set():
            raise sd.CallbackStop
        if status.input_overflow:
            self.sequence += 1  # Reset the model after lost capture audio.
        put_latest(self.frames, (self.sequence, data[:, 0].copy()))
        self.sequence += 1

    def __enter__(self):
        try:
            self.output = self.resources.enter_context(sd.OutputStream(
                device=device_index(self.sink, 'output'), samplerate=self.rate,
                channels=2, dtype='float32', blocksize=self.frame_size,
                extra_settings=sd.WasapiSettings(auto_convert=True)))
            self.input = self.resources.enter_context(sd.InputStream(
                device=device_index(self.source, 'input'), samplerate=self.rate,
                channels=1, dtype='float32', blocksize=self.frame_size,
                extra_settings=sd.WasapiSettings(auto_convert=True), callback=self._capture))
        except BaseException:
            self.resources.close()
            raise
        return self

    def read(self):
        try:
            return self.frames.get(timeout=3)
        except queue.Empty as error:
            raise RuntimeError('No se recibe audio. Comprueba el micrófono y los permisos de Windows.') from error

    def write(self, frame):
        if not self.output.active:
            raise RuntimeError('Se ha desconectado CABLE Input.')
        self.output.write(np.repeat(np.clip(frame, -1, 1)[:, None], 2, axis=1))

    def __exit__(self, *_):
        self.stopping.set()
        self.resources.close()


def run_stream(processor, requested_source=None, on_event=None):
    return process_stream(processor, requested_source, on_event, routing=Cable,
                          stream_factory=AudioStream, source_resolver=resolve_source)


def record_reference(destination, seconds=15, requested_source=None, on_event=None):
    if not 5 <= seconds <= 60:
        raise ValueError('La grabación debe durar entre 5 y 60 segundos.')
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    source = resolve_source(requested_source)
    for remaining in (3, 2, 1):
        if on_event:
            on_event('countdown', message=f'Empieza a hablar en {remaining}…', progress=0)
        time.sleep(1)
    samples = []
    with sd.InputStream(device=device_index(source, 'input'), channels=1, samplerate=16000,
                        dtype='int16', extra_settings=sd.WasapiSettings(auto_convert=True)) as stream:
        for step in range(seconds * 10):
            block, overflow = stream.read(1600)
            if overflow:
                raise RuntimeError('La grabación perdió audio. Vuelve a registrar tu voz.')
            samples.append(block.copy())
            if on_event:
                on_event('recording', message=f'Habla con naturalidad… {seconds - step // 10} s',
                         progress=(step + 1) / (seconds * 10))
    with destination.open('xb') as file, wave.open(file, 'wb') as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes(np.concatenate(samples).astype('<i2').tobytes())
