"""RNNoise and normalized mono frame validation (default: 48 kHz / 10 ms)."""

import ctypes
import ctypes.util

import numpy as np

RATE = 48_000
FRAME_SIZE = 480


def frame_array(frame, size=FRAME_SIZE):
    result = np.asarray(frame, dtype=np.float32)
    if result.shape != (size,) or not np.isfinite(result).all():
        raise ValueError(f"Se esperaba un bloque finito de {size} muestras mono.")
    return np.ascontiguousarray(result)


class RNNoise:
    """Noise suppression only; it does not identify a target speaker."""

    def __init__(self):
        library = ctypes.util.find_library("rnnoise")
        if not library:
            raise RuntimeError("No se encuentra librnnoise. Instala RNNoise en el sistema.")
        self.lib = ctypes.CDLL(library)
        self.lib.rnnoise_create.argtypes = [ctypes.c_void_p]
        self.lib.rnnoise_create.restype = ctypes.c_void_p
        self.lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        self.lib.rnnoise_destroy.restype = None
        pointer = ctypes.POINTER(ctypes.c_float)
        self.lib.rnnoise_process_frame.argtypes = [ctypes.c_void_p, pointer, pointer]
        self.lib.rnnoise_process_frame.restype = ctypes.c_float
        self.lib.rnnoise_get_frame_size.argtypes = []
        self.lib.rnnoise_get_frame_size.restype = ctypes.c_int
        if self.lib.rnnoise_get_frame_size() != FRAME_SIZE:
            raise RuntimeError("Esta versión de RNNoise no usa bloques de 480 muestras.")
        self.state = None
        self.reset()

    def reset(self):
        self.close()
        self.state = self.lib.rnnoise_create(None)
        if not self.state:
            raise RuntimeError("RNNoise no pudo crear su estado.")

    def process(self, frame):
        if not self.state:
            raise RuntimeError("El procesador RNNoise está cerrado.")
        # The C API expects float samples on the int16 scale, not [-1, 1].
        samples = frame_array(frame) * np.float32(32768.0)
        result = np.empty(FRAME_SIZE, dtype=np.float32)
        pointer = ctypes.POINTER(ctypes.c_float)
        self.lib.rnnoise_process_frame(
            self.state, result.ctypes.data_as(pointer), samples.ctypes.data_as(pointer)
        )
        return result / np.float32(32768.0)

    def close(self):
        if self.state:
            self.lib.rnnoise_destroy(self.state)
            self.state = None
