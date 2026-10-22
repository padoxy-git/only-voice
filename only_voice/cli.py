import argparse
import ctypes.util
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import time

from .audio import is_microphone, pactl, record_reference, run_stream, sources
from .processing import RNNoise
from .voice import MODEL_DIRECTORY, PROFILE_PATH, TargetVoice, download_model, enroll, load_engine
from .application import Application, wait_ready
from .variants import DEFAULT_PRECISION, PRECISIONS, VARIANTS, model_files


def doctor():
    success = True
    for command in ("pactl", "parec", "pacat"):
        found = shutil.which(command)
        print(f"{command}: {found or 'FALTA'}")
        success &= bool(found)
    print(f"RNNoise: {ctypes.util.find_library('rnnoise') or 'FALTA (necesario para denoise)'}")
    for module in ("onnxruntime", "voxlock"):
        print(f"{module}: {'disponible' if importlib.util.find_spec(module) else 'no instalado'}")
    try:
        print(pactl("info"))
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        success = False
    return 0 if success else 1


def parser():
    root = argparse.ArgumentParser(
        prog="only-voice",
        description="Only Voice · tu voz, en primer plano.",
        epilog="Uso diario: only-voice start · only-voice stop · only-voice status · only-voice gui",
    )
    commands = root.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Activar el filtro en segundo plano.")
    start.add_argument("--source", help="Micrófono de entrada (recuerda el último usado).")
    start.add_argument("--mode", choices=("voice", "noise"), help="voice: solo mi voz; noise: reducir ruido.")
    start.add_argument("--precision", choices=PRECISIONS, help="Variante de voz (recuerda la última usada; inicialmente int8).")
    commands.add_parser("stop", help="Detener el filtro o cancelar el registro de voz.")
    status = commands.add_parser("status", help="Consultar si el filtro está activo.")
    status.add_argument("--json", action="store_true", help="Mostrar el estado en formato JSON.")
    commands.add_parser("gui", help="Abrir la ventana de Only Voice.")
    profile = commands.add_parser("profile", help="Grabar 15 segundos para crear o actualizar tu voz.")
    profile.add_argument("--source", help="Micrófono para la grabación.")
    profile.add_argument("--wav", type=Path, help="Usar una muestra existente en lugar de grabar.")
    commands.add_parser("logs", help="Ver los últimos detalles de actividad.")
    install = commands.add_parser("install", help="Añadir el comando y el acceso al menú de aplicaciones.")
    install.add_argument("--prefix", type=Path, default=Path.home() / ".local", help="Destino de instalación del usuario.")
    commands.add_parser("doctor", help="Comprobar utilidades y conexión al servidor de audio.")
    devices = commands.add_parser("devices", help="Listar entradas de micrófono.")
    devices.add_argument("--json", action="store_true", help="Formato para otras interfaces.")
    download = commands.add_parser("download-model", help="Descargar el modelo TSE fijado a una revisión.")
    download.add_argument("--directory", type=Path, default=MODEL_DIRECTORY.parent)
    check = commands.add_parser("check-model", help="Comprobar que los modelos de voz locales cargan.")
    for command in (download, check):
        command.add_argument("--precision", choices=PRECISIONS, default=DEFAULT_PRECISION,
                             help="Variante de voz; por defecto int8.")
    register = commands.add_parser("enroll", help="Crear un perfil a partir de una muestra limpia de voz.")
    reference = register.add_mutually_exclusive_group(required=True)
    reference.add_argument("--wav", type=Path, help="WAV PCM16, 5–60 s, solo tu voz.")
    reference.add_argument("--record", action="store_true", help="Grabar la muestra desde el micrófono.")
    register.add_argument("--seconds", type=int, default=15, help="Duración de --record, entre 5 y 60 s.")
    register.add_argument("--source", help="Entrada de micrófono para --record.")
    register.add_argument("--profile", type=Path, default=PROFILE_PATH)
    register.add_argument("--model", type=Path, default=MODEL_DIRECTORY, help="Directorio de los modelos ONNX.")
    run = commands.add_parser("run", help="Extraer la voz de un perfil y crear el micrófono virtual.")
    run.add_argument("--profile", type=Path, default=PROFILE_PATH)
    run.add_argument("--model", type=Path, default=MODEL_DIRECTORY, help="Directorio de los modelos ONNX.")
    run.add_argument("--threads", type=int, choices=range(1, 17), default=4, help="Hilos de inferencia (1–16).")
    run.add_argument("--precision", choices=PRECISIONS, default=DEFAULT_PRECISION, help="Variante de voz; por defecto int8.")
    run.add_argument("--source", help="Nombre exacto de la entrada; por defecto usa la del sistema.")
    denoise = commands.add_parser("denoise", help="Reducir ruido con RNNoise; no distingue personas.")
    denoise.add_argument("--source", help="Nombre exacto de la entrada; por defecto usa la del sistema.")
    return root


def _terminate(*_):
    # Let context managers clean up on SIGTERM as well as Ctrl+C.
    raise KeyboardInterrupt


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    options = parser().parse_args(arguments or ["start"])
    old_handler = signal.signal(signal.SIGTERM, _terminate)
    try:
        if options.command == "install":
            from .install import install
            destination = install(options.prefix)
            print(f"Instalado: {destination}\nAbre Only Voice desde el menú o ejecuta only-voice gui.")
            if str(destination.parent) not in __import__("os").environ.get("PATH", "").split(":"):
                print(f"Para usar el comando, añade {destination.parent} a tu PATH.")
            return 0
        if options.command == "gui":
            from .desktop import launch
            return launch()
        if options.command in ("start", "stop", "status", "profile", "logs"):
            application = Application()
            if options.command == "start":
                settings = application.settings()
                if (options.mode or settings["mode"]) == "voice" and not application.paths.profile.is_file():
                    raise FileNotFoundError("Primero registra tu voz: only-voice profile (o abre only-voice gui).")
                print("Preparando Only Voice…", flush=True)
                try:
                    application.start(options.source, options.mode, options.precision)
                    state = wait_ready(application)
                except KeyboardInterrupt:
                    application.stop()
                    raise
                if state.get("phase") == "running":
                    print("Filtro activo. Selecciona Only_Voice como micrófono en tu llamada.\n"
                          "Puedes cerrar esta terminal. Para detenerlo: only-voice stop")
                else:
                    print(state.get("message", "Preparando… Consulta only-voice status."))
                return 0
            if options.command == "stop":
                application.stop()
                print("Only Voice detenido.")
                return 0
            if options.command == "logs":
                print(application.details())
                return 0
            if options.command == "status":
                state = application.status()
                if options.json:
                    print(json.dumps(state, ensure_ascii=False))
                else:
                    labels = {"running": "Activo", "starting": "Preparando", "stopped": "Detenido",
                              "error": "Error", "countdown": "Preparando la grabación",
                              "recording": "Grabando tu voz", "processing": "Creando tu perfil"}
                    print(f"Only Voice: {labels.get(state['phase'], state['phase'])}.")
                    if state.get("message"):
                        print(state["message"])
                    if state.get("task") == "filter" and state.get("mode") == "voice":
                        precision = state.get("precision", DEFAULT_PRECISION)
                        print(f"Variante: {VARIANTS.get(precision, VARIANTS[DEFAULT_PRECISION])['label']}.")
                return 0
            application.register(options.source, options.wav)
            previous = None
            try:
                while True:
                    state = application.status()
                    if state.get("message") != previous:
                        print(state.get("message", "Preparando…"), flush=True)
                        previous = state.get("message")
                    if not state["active"]:
                        if state.get("phase") == "error":
                            return 1
                        break
                    time.sleep(0.2)
            except KeyboardInterrupt:
                application.stop()
                raise
            return 0
        if options.command == "doctor":
            return doctor()
        if options.command == "devices":
            microphones = [source for source in sources() if is_microphone(source)]
            if options.json:
                print(json.dumps(microphones, ensure_ascii=False))
            else:
                for source in microphones:
                    print(f"{source['name']}\t{source.get('description', '')}")
            return 0
        if options.command == "download-model":
            print(download_model(options.directory, options.precision))
            return 0
        if options.command == "check-model":
            load_engine(MODEL_DIRECTORY, precision=options.precision)
            print(f"Los modelos locales de VoxLock ({options.precision}) cargan correctamente.")
            return 0
        if options.command == "enroll":
            if options.profile.exists():
                raise FileExistsError(f"Ya existe {options.profile}; elige otra ruta con --profile.")
            if options.record:
                with tempfile.TemporaryDirectory(prefix="only-voice-reference-") as directory:
                    reference = Path(directory) / "reference.wav"
                    record_reference(reference, options.seconds, options.source)
                    enroll(reference, options.profile, options.model)
            else:
                enroll(options.wav, options.profile, options.model)
            print(f"Perfil guardado en {options.profile}.")
            return 0
        if options.command == "run":
            if any(not (options.model / name).is_file() for name in model_files(options.precision)):
                raise FileNotFoundError(f"Faltan los modelos de voz: ejecuta ./voice.sh --precision {options.precision}.")
            if not options.profile.is_file():
                raise FileNotFoundError("Falta tu perfil de voz: ejecuta only-voice enroll --wav tu_voz.wav.")
            processor = TargetVoice(options.model, options.profile, options.threads, options.precision)
        else:
            print("Modo reducción de ruido: RNNoise conserva también las voces de otras personas.",
                  file=sys.stderr)
            processor = RNNoise()
        try:
            run_stream(processor, options.source)
        finally:
            processor.close()
        return 0
    except KeyboardInterrupt:
        print("Only Voice detenido.", file=sys.stderr)
        return 0
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, old_handler)
