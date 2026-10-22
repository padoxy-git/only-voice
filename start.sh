#!/usr/bin/env bash
set -euo pipefail

project_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_directory"

if [[ $# -eq 0 ]]; then
    set -- denoise
fi

environment_directory="$project_directory/.venv"
case "$1" in
    run|enroll|download-model|check-model)
        if [[ -x "$project_directory/.venv-voice/bin/only-voice" ]]; then
            environment_directory="$project_directory/.venv-voice"
        fi
        ;;
esac

if [[ ! -x "$environment_directory/bin/only-voice" ]]; then
    printf '%s\n' 'Falta la instalación local. Para preparar el aislamiento ejecuta ./voice.sh.' >&2
    exit 1
fi

exec "$environment_directory/bin/only-voice" "$@"
