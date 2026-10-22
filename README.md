<div align="center">
  <img src="assets/only-voice.svg" width="88" alt="Only Voice">
  <h1>Only Voice</h1>
  <p>Tu voz, en primer plano. Micrófono virtual para Windows y Linux.</p>
</div>

Only Voice reduce el ruido con RNNoise o aísla tu voz con VoxLock, procesando el audio en tu equipo. Es una aplicación gráfica: se controla desde el icono de la bandeja del sistema y no necesita una terminal.

## Descarga e instalación

Descarga los paquetes de [Releases](https://github.com/padoxy-git/only-voice/releases/latest).

| Sistema | Paquete | Requisitos |
|---|---|---|
| Windows 10/11 x64 | `OnlyVoice-…-windows-x64-setup.exe` o ZIP portable | VB-CABLE, permisos de micrófono para aplicaciones de escritorio |
| Debian/Ubuntu x86_64 | `.deb` | Ubuntu 22.04+, Debian 12+, PulseAudio o PipeWire con `pipewire-pulse` |
| Fedora x86_64 | `.rpm` | Fedora 40+, PulseAudio o PipeWire con compatibilidad PulseAudio |
| Arch Linux x86_64 | `.pkg.tar.zst` | PulseAudio o PipeWire con `pipewire-pulse` |

Los paquetes incluyen Python, Qt, ONNX y RNNoise. Las dependencias del escritorio y de PulseAudio se declaran en los paquetes Linux. Se necesita una bandeja habilitada; GNOME requiere una extensión como AppIndicator. El programa informa si no encuentra bandeja.

### Windows

1. Instala Only Voice con el instalador, o extrae el ZIP completo y abre `OnlyVoice.exe` dentro de la carpeta. No se abre una consola.
2. Instala [VB-CABLE desde el sitio oficial](https://vb-audio.com/Cable/) y reinicia Windows. La ventana de Configuración también incluye este enlace. El controlador se instala por separado y puede requerir permisos de administrador.
3. Abre Only Voice desde el menú Inicio. Aparecerá su icono en la bandeja, quizá dentro del menú de iconos ocultos.
4. Haz clic en el icono y selecciona tu micrófono físico. Only Voice usa WASAPI y envía el audio filtrado a **CABLE Input (VB-Audio Virtual Cable)**.
5. En tu aplicación de llamadas selecciona **CABLE Output (VB-Audio Virtual Cable)** como micrófono. Conserva tus auriculares como salida de la llamada.

Si falta VB-CABLE, la GUI explica cómo instalarlo al intentar activar el filtro. No se cambian los dispositivos predeterminados de Windows. No selecciones el cable como micrófono de entrada de Only Voice.

### Linux

Instala el paquete de tu distribución con su gestor habitual y abre **Only Voice** desde el menú de aplicaciones. El icono aparecerá en la bandeja. En tu aplicación de llamadas selecciona **Only_Voice** como micrófono después de activar el filtro. El micrófono virtual se retira al detener el filtro; no se cambian los dispositivos predeterminados.

## Uso desde la bandeja

El programa arranca con la ventana oculta. Haz clic en el icono para abrir **Configuración**, o usa su menú contextual:

- **Configuración…**: micrófono, modo, variante de voz, perfil y niveles.
- **Activar/Desactivar filtro**: controla el audio con los ajustes guardados.
- **Salir**: detiene el filtro y cierra la aplicación.

Cerrar la ventana de Configuración la oculta y mantiene el filtro activo. El programa no se inicia automáticamente con el sistema. Solo puede haber una instancia de la bandeja para cada directorio de datos.

### Modos

**Reducir ruido** usa RNNoise y funciona sin registrar la voz ni descargar modelos. No distingue entre la persona objetivo y otras voces.

**Solo mi voz** requiere un perfil: pulsa **Registrar mi voz (15 s)** y habla tú solo con volumen natural después de la cuenta atrás. También puedes importar un WAV PCM de 16 bits de entre 5 y 60 segundos. La grabación temporal se elimina tras crear el perfil; se conservan características numéricas. Puedes cancelar con el botón principal. Un registro fallido o cancelado conserva el perfil anterior.

Los modelos de VoxLock 1.1.1 se descargan en el primer uso de este modo desde la revisión pública fijada `a50f4e1d109301d4b6f61dec57ebb1a61e7d8f03` de [arbazsiddiqui/voxlock](https://huggingface.co/arbazsiddiqui/voxlock). Una vez descargados, funcionan sin conexión. El audio no se envía al servidor de modelos.

| Variante | Uso |
|---|---|
| Equilibrado · INT8 | Opción inicial con consumo de CPU moderado |
| Rápido · INT8-full | Prioriza rendimiento |
| Alta precisión · FP16 | Precisión cercana a FP32 con menor descarga |
| Precisión completa · FP32 | Modelo de referencia; mayor consumo |

Detén el filtro antes de cambiar el micrófono, modo o variante. El medidor muestra los niveles de entrada y salida; no mide la latencia total. El motor comprueba que puede procesar los bloques en tiempo real antes de activar el audio. La eficacia depende del micrófono, la muestra de voz y el entorno.

## Datos y diagnóstico

| Sistema | Ubicación predeterminada |
|---|---|
| Windows | `%LOCALAPPDATA%\Only Voice` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/only-voice` |

Dentro están `models/`, `profiles/me.npz` y `.runtime/` con preferencias, estado y registro de actividad. No se guardan en la carpeta del programa, por lo que las actualizaciones no requieren escribir en `/opt` y conservan los ajustes. La variable de entorno `ONLY_VOICE_DATA` permite elegir otro directorio.

Si usabas la versión anterior desde el código fuente, copia `profiles/` y `models/` del proyecto al nuevo directorio de datos con el filtro detenido. El perfil VoxLock anterior es compatible.

En Configuración, **Ver registro de actividad** muestra los errores del motor. Si no hay audio, comprueba el micrófono físico, los permisos en Windows, VB-CABLE y el dispositivo elegido en la llamada; en Linux comprueba que esté activo PulseAudio o `pipewire-pulse`.

## Desarrollo y releases

Python 3.12 recomendado. Para preparar el entorno de desarrollo:

```sh
python -m venv .venv
# Activa .venv con el mecanismo de tu sistema.
python -m pip install -e '.[voice]'
python -m only_voice
```

El punto de entrada público abre la aplicación de bandeja. Los módulos históricos CLI permanecen como código interno de compatibilidad y no se instalan como comandos de usuario. `start.bat` abre el entorno Windows con `pythonw.exe`; el lanzador `only-voice` usa el entorno Linux local.

El workflow [Desktop packages](.github/workflows/release.yml) compila y prueba en Ubuntu 22.04 y Windows Server 2022 con Python 3.12. Usa PyInstaller, RNNoise en la revisión `2cb77862b17c43eb78e4ed0531763f3e7854e49b`, nFPM para deb/rpm, tar con metadatos pacman e Inno Setup para Windows. Los binarios incluyen los avisos de licencia de las dependencias; VB-CABLE no se redistribuye.

Para ejecutar las pruebas sin escritorio:

```sh
python -m pip install -r packaging/requirements.txt
python packaging/build_native.py
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH="$PWD/build/native" python -m pytest -q
```

En Windows el workflow ejecuta las pruebas de WASAPI, controles de bandeja, bloqueo y procesos, y las pruebas del motor independientes de PulseAudio. El audio Windows se prueba con dispositivos simulados; no se afirma validación acústica en hardware real. Los ejecutables congelados se comprueban con `packaging/smoke.py` para verificar la carga de RNNoise y el diagnóstico de entrada ausente. Los paquetes se publican al crear un tag `v…`, después de completar ambos trabajos, junto con `SHA256SUMS`. El instalador Windows no está firmado digitalmente.
