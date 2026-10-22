"""VoxLock 1.1.1 integration; models and enrollment features stay local."""

from pathlib import Path
from types import SimpleNamespace
import wave

import numpy as np

from .processing import frame_array
from .application import Paths
from .variants import DEFAULT_PRECISION, model_files

MODEL_REPO = "arbazsiddiqui/voxlock"
MODEL_REVISION = "a50f4e1d109301d4b6f61dec57ebb1a61e7d8f03"
MODEL_FILES = model_files()
MODEL_DIRECTORY = Paths().models
PROFILE_PATH = Paths().profile


def download_model(directory, precision=DEFAULT_PRECISION):
    files = model_files(precision)
    directory = Path(directory)
    if all((directory / "onnx" / name).is_file() for name in files):
        return directory / "onnx"
    try:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import HfHubHTTPError
    except ImportError as error:
        raise RuntimeError("Faltan dependencias de voz. Ejecuta ./voice.sh.") from error
    for name in files:
        if (directory / "onnx" / name).is_file():
            continue
        try:
            hf_hub_download(
                MODEL_REPO, f"onnx/{name}", revision=MODEL_REVISION,
                local_dir=str(directory), token=False,
            )
        except HfHubHTTPError as error:
            status = getattr(error.response, "status_code", None)
            if status in (401, 403):
                raise RuntimeError(
                    f"El servidor rechaza el acceso público al modelo {MODEL_REPO} (HTTP {status}). "
                    "La descarga se ha solicitado sin credenciales. "
                    "El modelo no está disponible desde esta conexión; no se ha grabado tu voz."
                ) from error
            if status == 404:
                raise RuntimeError(
                    f"No se encuentra onnx/{name} en {MODEL_REPO}, revisión {MODEL_REVISION}. "
                    "Se necesita un artefacto disponible antes de activar el aislamiento."
                ) from error
            raise
    return directory / "onnx"


def ensure_model(directory, precision=DEFAULT_PRECISION):
    """Download missing files only; existing local models work offline."""
    directory = Path(directory)
    if any(not (directory / name).is_file() for name in model_files(precision)):
        download_model(directory.parent, precision)
    return directory


def load_engine(directory, threads=4, precision=DEFAULT_PRECISION):
    directory = Path(directory)
    missing = [name for name in model_files(precision) if not (directory / name).is_file()]
    if missing:
        raise FileNotFoundError("Faltan modelos de voz: " + ", ".join(missing)
                                + f". Ejecuta only-voice download-model --precision {precision}.")
    try:
        from voxlock import VoxLock
    except ImportError as error:
        raise RuntimeError("Falta VoxLock 1.1.1. Ejecuta ./voice.sh para instalarlo.") from error
    # Explicit local path prevents the library from downloading another revision.
    return VoxLock(model_dir=str(directory), precision=precision, threads=threads)


def load_profile(path):
    with np.load(path, allow_pickle=False) as profile:
        if (int(profile["version"]) != 2 or str(profile["backend"]) != "voxlock"
                or str(profile["revision"]) != MODEL_REVISION):
            raise ValueError("Perfil incompatible con VoxLock. Crea uno nuevo con enroll.")
        features = tuple(np.asarray(profile[key], dtype=np.float32) for key in ("mag", "context"))
    if any(not value.size or not np.isfinite(value).all() for value in features):
        raise ValueError("El perfil contiene características vacías o no finitas.")
    return features


def read_reference(path):
    with wave.open(str(path), "rb") as recording:
        if recording.getsampwidth() != 2 or recording.getcomptype() != "NONE":
            raise ValueError("Usa un WAV PCM de 16 bits con una sola persona hablando.")
        rate = recording.getframerate()
        if not 5 <= recording.getnframes() / rate <= 60:
            raise ValueError("La muestra debe durar entre 5 y 60 segundos.")
        raw = recording.readframes(recording.getnframes())
        channels = recording.getnchannels()
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32).reshape(-1, channels).mean(axis=1)
    samples /= np.float32(32768.0)
    if np.sqrt(np.mean(samples**2)) < 0.001:
        raise ValueError("La muestra está vacía o tiene un volumen demasiado bajo.")
    if rate != 16_000:
        try:
            import soxr
        except ImportError as error:
            raise RuntimeError("Falta soxr para convertir la muestra a 16 kHz. Ejecuta ./voice.sh.") from error
        samples = soxr.resample(samples, rate, 16_000).astype(np.float32)
    # Select the highest-energy contiguous three seconds, matching the upstream
    # enrollment recipe, rather than accidentally enrolling the opening silence.
    energies = np.mean(samples[:len(samples) // 160 * 160].reshape(-1, 160)**2, axis=1)
    start = int(np.argmax(np.convolve(energies, np.ones(300), "valid"))) * 160
    return np.ascontiguousarray(samples[start:start + 48_000], dtype=np.float32)


def enroll(wav_path, profile_path, model_directory):
    destination = Path(profile_path)
    if destination.exists():
        raise FileExistsError(f"Ya existe {destination}.")
    reference = read_reference(wav_path)
    engine = load_engine(model_directory)
    features = engine.enroll.run(None, {"enroll": reference[None]})
    if len(features) != 2 or any(not value.size or not np.isfinite(value).all() for value in features):
        raise RuntimeError("El modelo no ha producido un perfil válido.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Features only: no raw enrollment recording or pickle is stored.
    with destination.open("xb") as stream:
        np.savez_compressed(stream, version=2, backend="voxlock", revision=MODEL_REVISION,
                            mag=features[0], context=features[1])


class ProfileEncoder:
    """Supply saved enrollment features to the pinned public Stream API."""

    def __init__(self, features):
        self.features = features

    def run(self, *_):
        return self.features


class TargetVoice:
    rate = 16_000
    frame_size = 640

    def __init__(self, directory, profile, threads=4, precision=DEFAULT_PRECISION):
        try:
            from voxlock import Stream
        except ImportError as error:
            raise RuntimeError("Falta VoxLock 1.1.1. Ejecuta ./voice.sh.") from error
        engine = load_engine(directory, threads, precision)
        features = load_profile(profile)
        # Stream calls the encoder once at construction. Cached features avoid
        # repeating enrollment inference on every dropped-frame reset.
        self.engine = SimpleNamespace(chunk=engine.chunk, enroll=ProfileEncoder(features))
        self.stream_type = Stream
        self.reset()

    def reset(self):
        self.stream = self.stream_type(self.engine, np.zeros(1, dtype=np.float32))

    def process(self, frame):
        result = self.stream.push(frame_array(frame, self.frame_size))
        result = np.asarray(result, dtype=np.float32)
        if result.ndim != 1 or not np.isfinite(result).all() or result.size > self.frame_size:
            raise RuntimeError("El extractor ha producido un bloque de audio no válido.")
        return result

    def close(self):
        self.stream = self.engine = None
