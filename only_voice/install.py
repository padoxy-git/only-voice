"""User-scoped CLI and desktop-menu integration; no administrative privileges."""

import os
from pathlib import Path

from .application import PROJECT


def quote_exec(value):
    value = str(value)
    if any(char in value for char in ("\n", "\r", "\0", "=")):
        raise ValueError("La ruta de instalación contiene caracteres no admitidos por el lanzador del escritorio.")
    value = value.replace("\\", "\\\\\\\\").replace("%", "%%")
    for char in ('"', '$', '`'):
        value = value.replace(char, "\\\\" + char)
    return '"' + value + '"'


def desktop_entry(project=PROJECT):
    project = Path(project).resolve()
    icon = str(project / "assets/only-voice.svg").replace("\\", "\\\\")
    return ("[Desktop Entry]\nType=Application\nName=Only Voice\n"
            "Comment=Tu voz, en primer plano\n"
            f"Exec={quote_exec(project / 'only-voice')}\n"
            f"Icon={icon}\nTerminal=false\nCategories=AudioVideo;Audio;\n"
            "StartupNotify=true\nX-OnlyVoice-Launcher=true\n")


def install(prefix, project=PROJECT):
    prefix, project = Path(prefix).expanduser().resolve(), Path(project).resolve()
    launcher = project / "only-voice"
    destination = prefix / "bin/only-voice"
    desktop = prefix / "share/applications/only-voice.desktop"
    content = desktop_entry(project)
    if not launcher.is_file():
        raise FileNotFoundError(f"No se encuentra el lanzador {launcher}.")
    if destination.exists() or destination.is_symlink():
        if not destination.is_symlink() or destination.resolve() != launcher:
            raise FileExistsError(f"Ya existe {destination}; no se ha sobrescrito.")
    if desktop.exists() and "X-OnlyVoice-Launcher=true" not in desktop.read_text():
        raise FileExistsError(f"Ya existe otro lanzador en {desktop}; no se ha sobrescrito.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    desktop.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_symlink():
        destination.symlink_to(launcher)
    temporary = desktop.with_name(f".only-voice-{os.getpid()}.desktop")
    try:
        temporary.write_text(content)
        temporary.chmod(0o755)
        os.replace(temporary, desktop)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
