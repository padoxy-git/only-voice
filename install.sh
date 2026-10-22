#!/usr/bin/env bash
# Optional per-user desktop shortcut for a source checkout.
set -euo pipefail
project_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_directory"
for environment in .venv-voice .venv; do
    if [[ -x "$environment/bin/python" ]]; then
        exec "$environment/bin/python" -c 'from pathlib import Path; from only_voice.install import install; install(Path.home() / ".local")'
    fi
done
printf '%s\n' 'Prepara el entorno de desarrollo con ./voice.sh.' >&2
exit 1
