"""Display state shared by the native desktop frontends."""

from .variants import DEFAULT_PRECISION, VARIANTS

def presentation(state, has_profile, mode="voice"):
    """Keep wording and action availability consistent across UI refreshes."""
    phase = state.get("phase", "stopped")
    active = state.get("active", False)
    if active and state.get("task") == "profile":
        titles = {"countdown": "Prepárate para hablar", "recording": "Grabando tu voz",
                  "processing": "Creando tu perfil"}
        return dict(badge="Registro de voz", title=titles.get(phase, "Preparando tu voz"),
                    message=state.get("message", "Un momento…"), action="Cancelar grabación", enabled=True)
    if active:
        running = phase == "running"
        variant = VARIANTS.get(state.get("precision", DEFAULT_PRECISION), VARIANTS[DEFAULT_PRECISION])["label"]
        message = ("En tu llamada, selecciona Only_Voice como micrófono."
                   + (f" Variante: {variant}." if state.get("mode", mode) == "voice" else "")) if running else state.get(
                       "message", "Preparando el micrófono y tu voz…")
        return dict(badge="Activo" if running else "Preparando", title="Filtro activado" if running else "Activando el filtro",
                    message=message,
                    action="Desactivar filtro" if running else "Cancelar inicio", enabled=True)
    if phase == "error":
        return dict(badge="Revisar", title="No se pudo completar", message=state.get("message", "Consulta los detalles."),
                    action="Volver a intentar", enabled=has_profile or mode == "noise")
    if mode == "voice" and not has_profile:
        return dict(badge="Primer uso", title="Primero, prepara tu voz", message="Graba una muestra de 15 segundos para que el filtro reconozca tu voz.",
                    action="Activa el filtro después de grabar", enabled=False)
    return dict(badge="Detenido", title="Todo listo para tu llamada", message="Activa el filtro y elige Only_Voice en tu aplicación de llamadas.",
                action="Activar filtro", enabled=True)

