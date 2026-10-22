"""Detached worker shared by the desktop app and short CLI commands."""

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import traceback

from .application import Paths, lock, process_identity, write_json
if sys.platform == "win32":
    from .windows_audio import record_reference, run_stream
else:
    from .audio import record_reference, run_stream
from .processing import RNNoise
from .voice import TargetVoice, enroll, ensure_model, load_engine
from .variants import DEFAULT_PRECISION, PRECISIONS, VARIANTS


def terminate(*_):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--task", choices=("filter", "profile"), required=True)
    parser.add_argument("--mode", choices=("voice", "noise"), default="voice")
    parser.add_argument("--precision", choices=PRECISIONS, default=DEFAULT_PRECISION)
    parser.add_argument("--source")
    parser.add_argument("--wav", type=Path)
    options = parser.parse_args(argv)
    paths = Paths(options.project.resolve())
    state = {"pid": os.getpid(), "identity": process_identity(os.getpid()),
             "task": options.task, "mode": options.mode, "precision": options.precision, "source": options.source,
             "requested_source": options.source,
             "phase": "starting", "message": "Preparando el audio…", "started_at": time.time()}

    def update(phase=None, **values):
        if phase != "stopped" and paths.file("stop").exists():
            raise KeyboardInterrupt
        if phase:
            state["phase"] = phase
        state.update(values)
        state["updated_at"] = time.time()
        write_json(paths.file("state.json"), state)

    resources = ExitStack()
    try:
        resources.enter_context(lock(paths.file("worker.lock"), blocking=False))
    except BlockingIOError:
        print("Ya hay un proceso de Only Voice activo.", file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        update()
        if options.task == "profile":
            update("processing", message="Preparando el registro de voz…")
            # One canonical encoder keeps profiles reusable across all variants.
            ensure_model(paths.models)
            load_engine(paths.models)  # Fail before recording if models are missing.
            with tempfile.TemporaryDirectory(prefix="only-voice-profile-") as directory:
                reference = options.wav or Path(directory) / "reference.wav"
                if options.wav is None:
                    record_reference(reference, 15, options.source, on_event=update)
                update("processing", message="Guardando tu perfil de voz…", progress=1.0)
                profile = Path(directory) / "new.npz"
                enroll(reference, profile, paths.models)
                paths.profile.parent.mkdir(parents=True, exist_ok=True)
                # The new profile lives on the same filesystem for atomic replace.
                temporary = paths.profile.with_name(f".new-{os.getpid()}.npz")
                try:
                    temporary.write_bytes(profile.read_bytes())
                    temporary.chmod(0o600)
                    os.replace(temporary, paths.profile)
                finally:
                    temporary.unlink(missing_ok=True)
            update("stopped", message="Tu perfil de voz está listo.")
        else:
            if options.mode == "voice":
                update(message=f"Preparando {VARIANTS[options.precision]['label']}. "
                       "Descargando los modelos si faltan; la primera vez puede tardar…")
                ensure_model(paths.models, options.precision)
                processor = TargetVoice(paths.models, paths.profile, precision=options.precision)
            else:
                processor = RNNoise()
            resources.callback(processor.close)
            run_stream(processor, options.source, on_event=update)
    except KeyboardInterrupt:
        update("stopped", message="Grabación cancelada." if options.task == "profile" else "Filtro detenido.",
               input_db=-60, output_db=-60)
    except Exception as error:
        traceback.print_exc()
        update("error", message=str(error), input_db=-60, output_db=-60)
        return 1
    finally:
        resources.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
