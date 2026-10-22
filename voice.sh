#!/usr/bin/env bash
# Development environment setup; everyday configuration is in the tray GUI.
set -euo pipefail
project_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_directory"
if [[ ! -x .venv-voice/bin/python ]]; then
    python3 -m venv .venv-voice
fi
.venv-voice/bin/python -m pip install -e '.[voice]'
exec .venv-voice/bin/python -m only_voice
