#!/usr/bin/env bash
set -euo pipefail

project_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_arguments=()
reference_arguments=()
precision_arguments=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --precision)
            [[ $# -ge 2 ]] || { printf '%s\n' 'Falta la variante después de --precision.' >&2; exit 2; }
            case "$2" in
                int8|int8-full|fp16|fp32) precision_arguments=(--precision "$2") ;;
                *) printf '%s\n' 'Variante no válida. Elige int8, int8-full, fp16 o fp32.' >&2; exit 2 ;;
            esac
            shift 2
            ;;
        --source)
            [[ $# -ge 2 ]] || { printf '%s\n' 'Falta el nombre después de --source.' >&2; exit 2; }
            source_arguments=(--source "$2")
            shift 2
            ;;
        --wav)
            [[ $# -ge 2 ]] || { printf '%s\n' 'Falta el archivo después de --wav.' >&2; exit 2; }
            reference_arguments=(--wav "$(realpath -e -- "$2")")
            shift 2
            ;;
        -h|--help)
            printf '%s\n' \
                'Uso: ./voice.sh [--source NOMBRE] [--wav MUESTRA.wav] [--precision int8|int8-full|fp16|fp32]' \
                'Prepara el entorno CPU y los modelos; crea tu perfil si falta y activa el aislamiento.' \
                'Sin --wav, graba 15 segundos de referencia con una cuenta atrás.' \
                'En siguientes arranques reutiliza el perfil existente.'
            exit 0
            ;;
        *) printf 'Opción no reconocida: %s\n' "$1" >&2; exit 2 ;;
    esac
done

cd -- "$project_directory"
trap 'printf "%s\n" "No se ha podido completar el arranque de voz. Revisa el error anterior; puedes repetir ./voice.sh." >&2' ERR

# All tools, Python versions and caches stay inside this project.
export UV_CACHE_DIR="$project_directory/.tools/uv-cache"
export UV_PYTHON_INSTALL_DIR="$project_directory/.tools/python"
export UV_PYTHON_INSTALL_BIN=0
export PIP_CACHE_DIR="$project_directory/.tools/pip-cache"

if [[ ! -x .venv-voice/bin/only-voice ]] || [[ ! -f .venv-voice/.voxlock-ready ]]; then
    printf '%s\n' 'Preparando el modo de voz con Python 3.12 y VoxLock CPU. La primera descarga puede tardar.'
    if command -v uv >/dev/null 2>&1; then
        uv_command="$(command -v uv)"
    else
        uv_command="$project_directory/.tools/uv/bin/uv"
        if [[ ! -x "$uv_command" ]]; then
            bootstrap_python="$project_directory/.venv/bin/python"
            if [[ ! -x "$bootstrap_python" ]]; then
                bootstrap_python="$(command -v python3)"
            fi
            "$bootstrap_python" -m pip install --retries 0 --timeout 30 \
                --target "$project_directory/.tools/uv" 'uv>=0.8,<1'
        fi
    fi

    if [[ ! -x .venv-voice/bin/python ]]; then
        "$uv_command" venv --python 3.12 --seed .venv-voice
    fi
    .venv-voice/bin/python -c \
        'import sys; assert sys.version_info[:2] == (3, 12), "El entorno .venv-voice debe usar Python 3.12."'
    "$uv_command" pip install --python .venv-voice/bin/python \
        -e '.[voice]'
    .venv-voice/bin/python -c \
        'import voxlock, soxr; print("VoxLock", voxlock.__version__, "cargado correctamente.")'
    touch .venv-voice/.voxlock-ready
fi

if [[ ${#precision_arguments[@]} -eq 0 ]]; then
    saved_precision="$(.venv-voice/bin/python -c 'from only_voice.application import Application; print(Application().settings()["precision"])')"
    precision_arguments=(--precision "$saved_precision")
fi
.venv-voice/bin/only-voice download-model "${precision_arguments[@]}"
.venv-voice/bin/only-voice check-model "${precision_arguments[@]}"
if [[ ! -f profiles/me.npz ]]; then
    # Profiles always use the canonical encoder and work with every variant.
    .venv-voice/bin/only-voice download-model
    if [[ ${#reference_arguments[@]} -eq 0 ]]; then
        reference_arguments=(--record --seconds 15)
    fi
    .venv-voice/bin/only-voice enroll "${reference_arguments[@]}" "${source_arguments[@]}"
elif [[ ${#reference_arguments[@]} -gt 0 ]]; then
    printf '%s\n' 'Ya existe profiles/me.npz. Se reutiliza el perfil; no se sobrescribe con el WAV indicado.' >&2
fi

printf '%s\n' 'Activando la extracción de tu voz. Selecciona Only_Voice en la llamada.'
exec .venv-voice/bin/only-voice start --mode voice "${source_arguments[@]}" "${precision_arguments[@]}"
