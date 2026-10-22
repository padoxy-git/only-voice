<div align="center">
  <img src="assets/only-voice.svg" alt="Icono de Only Voice" width="88" height="88">
  <h1>Only Voice</h1>
  <p><strong>Tu voz, en primer plano.</strong></p>
  <p>Un micrófono virtual para reducir el ruido o aislar tu voz en llamadas desde Linux.</p>
  <p>Procesamiento local · Interfaz gráfica y terminal · PipeWire / PulseAudio</p>
  <p>
    <a href="#inicio-rápido">Inicio rápido</a> ·
    <a href="#uso-diario">Uso diario</a> ·
    <a href="#solución-de-problemas">Ayuda</a> ·
    <a href="#desarrollo">Desarrollo</a>
  </p>
</div>

---

## Qué hace

Only Voice procesa el audio de tu micrófono en tu equipo y crea una entrada
llamada **`Only_Voice`**. Selecciónala en tu aplicación de llamadas para usar
el audio filtrado.

```text
Tu micrófono → Filtro local → Only_Voice → Aplicación de llamadas
```

| Modo | Qué hace | Qué necesita |
| --- | --- | --- |
| **Solo mi voz** · VoxLock | Intenta extraer tu voz cuando hay otras voces o ruido. | Modelos descargados y un perfil de tu voz. |
| **Reducir ruido** · RNNoise | Reduce el ruido ambiental; conserva también las voces de otras personas. | `librnnoise`. No necesita un perfil. |

El audio de las llamadas se procesa localmente: no se graba ni se envía a un
servidor. Tras la preparación inicial, los modelos y el perfil se reutilizan
sin conexión.

> **Antes de tu primera llamada:** prueba el resultado con tu micrófono.
> El aislamiento puede dejar pasar otras voces, distorsionar la tuya o recortar palabras.

## Requisitos

| Componente | Requisito |
| --- | --- |
| Sistema | Linux con PulseAudio o PipeWire con `pipewire-pulse`. |
| Audio | Utilidades `pactl`, `parec` y `pacat`, con acceso a la sesión de audio del escritorio. |
| Python | Python 3.11 o superior. El preparador de voz obtiene Python 3.12 si hace falta. |
| Primera instalación | Git, Internet y `pip` si no tienes `uv` instalado. |
| Ventana | GTK 4 y PyGObject del sistema; como alternativa en X11, Tk. |
| Reducción de ruido | `librnnoise`, necesaria solo para el modo RNNoise. |

En Arch Linux, las dependencias de la ventana se instalan con:

```sh
sudo pacman -S gtk4 python-gobject
```

## Inicio rápido

### 1. Descarga el proyecto

```sh
git clone https://github.com/padoxy-git/only-voice.git
cd only-voice
```

### 2. Prepara tu voz y activa el filtro

Desde una terminal de tu escritorio, ejecuta:

```sh
./voice.sh
```

El primer arranque prepara el entorno, descarga y comprueba los modelos y,
si aún no tienes un perfil, graba **15 segundos** de referencia tras una cuenta
atrás. Habla tú solo, con volumen natural y sin otras voces de fondo.

Al terminar, el filtro queda activo en segundo plano. Los siguientes arranques
reutilizan la instalación y tu perfil. Esta preparación no necesita `sudo`.

### 3. Selecciona la entrada en tu llamada

En los ajustes de audio de tu aplicación de llamadas, elige
**`Only_Voice`** como micrófono.

### 4. Abre los controles

```sh
./only-voice gui
```

Desde la ventana puedes ver los niveles de audio, detener el filtro o cambiar
sus ajustes. Para detenerlo desde la terminal, usa `./only-voice stop`.

<details>
<summary><strong>Solo quiero reducir ruido, sin registrar mi voz</strong></summary>

Con `librnnoise` instalada, prepara el entorno básico y comprueba el audio:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
./start.sh doctor
./start.sh devices
./start.sh
```

Este lanzador utiliza RNNoise y permanece en primer plano. Selecciona
**`Only_Voice`** en la llamada y pulsa **Ctrl+C** en la terminal para detenerlo.
Para elegir una entrada concreta:

```sh
./start.sh denoise --source NOMBRE_DE_ENTRADA
```

También puedes abrir la ventana y elegir **Reducir ruido**, o iniciarlo en
segundo plano con `./only-voice start --mode noise`.

</details>

## Uso diario

### Desde la ventana

1. Abre `./only-voice gui` y selecciona tu micrófono.
2. Elige **Solo mi voz** o **Reducir ruido**.
3. Pulsa **Activar filtro** y usa **`Only_Voice`** en la llamada.
4. Al terminar, pulsa **Desactivar filtro**.

La ventana y la terminal controlan el mismo proceso: puedes iniciarlo desde una
y detenerlo desde la otra. Se recuerdan el último micrófono, modo y variante usados.
Detén el filtro antes de cambiar estos ajustes o actualizar tu perfil.

> **Cerrar la ventana no detiene el filtro.** Continúa en segundo plano hasta
> que pulses **Desactivar filtro** o ejecutes `./only-voice stop`.
> No se inicia automáticamente al arrancar Linux.

### Desde la terminal

| Comando | Acción |
| --- | --- |
| `./only-voice` o `./only-voice start` | Activar el filtro en segundo plano. |
| `./only-voice stop` | Detener el filtro o cancelar el registro de voz. |
| `./only-voice status` | Consultar el estado y la variante activa. |
| `./only-voice gui` | Abrir los controles. |
| `./only-voice devices` | Listar los micrófonos disponibles. |
| `./only-voice profile` | Crear o actualizar tu perfil con una grabación de 15 segundos. |
| `./only-voice logs` | Consultar los detalles de actividad y errores. |
| `./only-voice doctor` | Comprobar dependencias y conexión al servidor de audio. |

Para elegir los ajustes al iniciar:

```sh
./only-voice start --source NOMBRE_DE_ENTRADA
./only-voice start --mode noise
./only-voice start --mode voice --precision fp32
```

Para consultar el estado desde otro programa, usa `./only-voice status --json`.

### Añadir al menú de aplicaciones

Una vez preparado el entorno, ejecuta:

```sh
./install.sh
```

Añade **Only Voice** al menú y crea el comando `~/.local/bin/only-voice`.
Después puedes ejecutar `only-voice gui` desde cualquier carpeta.
No necesita `sudo` ni sustituye un comando ajeno con el mismo nombre.

Si el instalador lo indica, añade `~/.local/bin` a tu `PATH`.
**Mantén el proyecto en su ubicación:** el acceso instalado enlaza a esta carpeta.

## Tu perfil de voz

El perfil permite que VoxLock use tu voz como referencia. Para crearlo o
renovarlo, detén el filtro y pulsa **Grabar mi voz** o **Actualizar mi voz**
en la ventana. También puedes ejecutar `./only-voice profile`.

| Operación | Comportamiento |
| --- | --- |
| Grabar | Registra 15 segundos tras una cuenta atrás. Habla tú solo y con naturalidad. |
| Actualizar | Sustituye el perfil anterior únicamente si el registro termina correctamente. |
| Cancelar | Usa el botón de cancelar o `./only-voice stop`. Cerrar la ventana durante el registro también lo cancela. |
| Guardar | `profiles/me.npz` contiene características de referencia. La grabación temporal se elimina. |

Para utilizar una muestra que ya tengas:

```sh
./only-voice profile --wav recordings/me.wav
```

Debe ser un **WAV PCM16 de entre 5 y 60 segundos**, con una sola persona
hablando. Se convierte a mono y 16 kHz si hace falta. Se rechazan muestras casi
silenciosas, pero no se comprueba automáticamente cuántas personas hablan.

## Variantes de voz

En **Solo mi voz**, el selector **Variante de voz** ofrece estas opciones:

| Variante | Valor en la CLI | Características |
| --- | --- | --- |
| **Equilibrado** · predeterminada | `int8` | Equilibrio entre precisión y consumo de CPU. |
| **Rápido** | `int8-full` | Prioriza el rendimiento en CPU, con algo más de pérdida de precisión. |
| **Alta precisión** | `fp16` | Precisión cercana a FP32 y menor descarga; puede consumir más CPU que INT8. |
| **Precisión completa** | `fp32` | Modelo de referencia sin cuantización; puede consumir más CPU que INT8. |

Tu perfil sirve para las cuatro: **no necesitas volver a grabarte**.
Detén el filtro para cambiar de variante. La selección se recuerda al activarlo;
si faltan archivos, se descargan durante la preparación y puedes cancelar el inicio.
Si una variante falla, se muestra el error sin cambiar a otra automáticamente.

La precisión numérica no garantiza una mejora audible. Una inferencia más
rápida tampoco equivale por sí sola a una menor latencia total de la llamada.

## Privacidad y límites

- **Audio local:** no se graban llamadas ni se envía su audio a un servidor.
- **Perfil local:** contiene características de tu voz, no el WAV original; se carga sin `pickle`.
- **Descargas públicas:** los modelos se solicitan sin utilizar credenciales guardadas.
- **Datos fuera de Git:** `.gitignore` excluye modelos, perfiles, grabaciones, entornos y credenciales locales.
- **Micrófono temporal:** no se cambian los dispositivos de audio predeterminados del sistema.

Quedan por validar español, voces solapadas, reverberación, carga elevada de
CPU y latencia de extremo a extremo. **No hay cancelación de eco acústico.**

## Solución de problemas

| Problema | Qué comprobar |
| --- | --- |
| La llamada recibe audio sin filtrar | Selecciona **`Only_Voice`** como entrada en la aplicación de llamadas. |
| El filtro no arranca | Ejecuta `./only-voice doctor`, `./only-voice status` y `./only-voice logs`. |
| No aparece la ventana | Abre `./only-voice gui` desde una terminal del escritorio. Consulta `.runtime/gui.log` y comprueba GTK 4 y PyGObject. |
| Aparece «Falta la instalación local» | Ejecuta `./voice.sh` o prepara el entorno básico de RNNoise. |
| Falla la descarga de un modelo | Comprueba la conexión y el error mostrado. Un HTTP 401/403 o 404 indica que el archivo no está disponible desde esa conexión. |
| El audio se corta o el equipo no sigue el ritmo | Revisa los tiempos y bloques descartados en los registros y compara las variantes con tu equipo. |
| El filtro sigue activo al cerrar la ventana | Ejecuta `./only-voice stop`; cerrar los controles no detiene el proceso. |

Si falla la descarga o carga de un modelo, el inicio se detiene sin pasar a
transmitir el micrófono original.

<details>
<summary><strong>Retirar el micrófono virtual tras un cierre abrupto</strong></summary>

Ctrl+C y SIGTERM intentan retirar los módulos de esa ejecución. Si un cierre
abrupto los deja cargados, localiza los que tengan nombres `only_voice_…`:

```sh
pactl list modules short
```

Retira únicamente los módulos de Only Voice con `pactl unload-module ID`,
primero el `module-remap-source` y después el `module-null-sink`.

</details>

<details>
<summary><strong>Compatibilidad con perfiles antiguos</strong></summary>

El adaptador anterior basado en `penta2himajin/tse-conv-tasnet-48k` se retiró.
Sus perfiles JSON no son compatibles con VoxLock. Crea un perfil NPZ con
`./only-voice profile` o mediante la ventana.

</details>

## Referencia técnica

<details>
<summary><strong>Comandos avanzados y perfiles adicionales</strong></summary>

El preparador admite entrada, muestra y variante:

```sh
./voice.sh --source NOMBRE_DE_ENTRADA
./voice.sh --wav recordings/me.wav
./voice.sh --precision int8-full
```

`voice.sh` reutiliza el perfil existente; `--wav` no lo sobrescribe.
Para actualizarlo utiliza `./only-voice profile --wav recordings/me.wav`.

Para crear y utilizar un perfil adicional sin sustituir el principal:

```sh
./start.sh enroll --record --profile profiles/other.npz
./start.sh run --profile profiles/other.npz
```

Para descargar o comprobar modelos y ajustar la ejecución:

```sh
./start.sh download-model --precision fp16
./start.sh check-model --precision fp16
./start.sh run --precision fp16
./start.sh run --threads 4
./start.sh run --model models/voxlock/onnx --profile profiles/me.npz
```

`download-model`, `check-model` y `run` usan `int8` si se omite `--precision`:
no consultan las preferencias de la ventana. `run` requiere los modelos locales
y permanece en primer plano. `check-model` comprueba que cargan, no su calidad acústica.

`start.sh` usa `.venv-voice` para los comandos de voz cuando está instalado.
El preparador guarda herramientas y cachés en `.tools/`. El flujo de voz utiliza
VoxLock y ONNX Runtime; no importa SpeechBrain, PyTorch ni torchaudio.

</details>

<details>
<summary><strong>Modelos y archivos ONNX</strong></summary>

El adaptador usa [VoxLock 1.1.1](https://pypi.org/project/voxlock/1.1.1/) y
los modelos de [arbazsiddiqui/voxlock](https://huggingface.co/arbazsiddiqui/voxlock),
con la revisión fijada a `a50f4e1d109301d4b6f61dec57ebb1a61e7d8f03`.

| Variante | Codificador | Extractor |
| --- | --- | --- |
| `int8` | `enroll.onnx` | `chunk_int8.onnx` |
| `int8-full` | `enroll.onnx` | `chunk_int8_full.onnx` |
| `fp16` | `enroll_fp16.onnx` | `chunk_fp16.onnx` |
| `fp32` | `enroll.onnx` | `chunk.onnx` |

El registro utiliza siempre `enroll.onnx`: selecciona los tres segundos de
mayor energía de la muestra y calcula las características de referencia.
En el primer registro con FP16 también se preparan los modelos predeterminados.
Los archivos compartidos se descargan una sola vez. Los pesos no se redistribuyen
con el proyecto; consulta su licencia en el repositorio del modelo.

</details>

<details>
<summary><strong>Audio, latencia e interfaz</strong></summary>

| Procesador | Audio | Bloque de procesamiento | Búfer solicitado al servidor |
| --- | --- | --- | --- |
| RNNoise | Mono, 48 kHz | 480 muestras · 10 ms | 20 ms |
| VoxLock | Mono, 16 kHz | 640 muestras · 40 ms | 80 ms |

El servidor puede ajustar los búferes y convertir la frecuencia para la llamada.
La banda de audio del aislamiento queda limitada por los 16 kHz del extractor.
VoxLock admite salidas más cortas al comenzar el procesamiento.

La cola de Python admite tres bloques. Si se descartan bloques antiguos por
retraso, se reinicia el extractor conservando la identidad del perfil, sin
repetir la inferencia de registro. La comprobación de arranque detiene el proceso
si el tiempo medio de procesamiento supera la duración del bloque. Cada cinco
segundos se muestran el tiempo medio y los bloques descartados.
**Estas cifras no miden la latencia total de una llamada.**

La interfaz GTK 4 admite Wayland y usa un tema oscuro con acento verde, definido
en `only_voice/styles/zephyx.css`. Las barras reúnen intervalos de unos 80 ms,
con subida rápida y caída gradual. Las consultas y operaciones de audio se
ejecutan fuera del hilo gráfico. El renderizador predeterminado es Cairo;
para probar otro solo en Only Voice:

```sh
GSK_RENDERER=gl ./only-voice gui
```

</details>

## Desarrollo

### Trabajar con Git

Empieza cada mejora desde `main` actualizada y crea una rama:

```sh
git switch main
git pull --ff-only
git switch -c mejora/nombre-del-cambio
```

Después de editar y comprobar los cambios:

```sh
git status
git diff
git add ruta/al/archivo
git diff --cached
git commit -m "Describe el cambio"
git push -u origin HEAD
```

**`commit`** guarda una versión local. **`push`** la sube a GitHub.
Abre una pull request hacia `main` para revisar e integrar la mejora.
En los siguientes envíos de esa rama basta con `git push`.

### Ejecutar las pruebas

Con el entorno de voz preparado:

```sh
.venv-voice/bin/python -m unittest discover -s tests -v
/usr/bin/python3 -m unittest discover -s tests -p test_gtk_controller.py -v
bash -n only-voice install.sh start.sh voice.sh
```

Las pruebas cubren perfiles, registro, variantes, errores de descarga, transporte
de audio, limpieza de recursos, controles de CLI/GUI e instalación. RNNoise usa
ruido sintético si está instalado; VoxLock utiliza un doble de su API y procesos
de audio simulados. Los controles GTK se comprueban también sin pantalla; la
prueba de la ventana nativa se omite si no hay sesión gráfica disponible.

No descargan pesos, no acceden al micrófono y no validan la calidad acústica.
Se ha comprobado además el arranque y la parada con pesos reales y un servidor
de audio simulado, y ambos modos se han probado en el escritorio de desarrollo.
Esto no sustituye una medición de latencia de extremo a extremo en una llamada.

### Referencias

- [API de VoxLock](https://github.com/arbazsiddiqui/voxlock/blob/main/voxlock/core.py).
- [Módulos PulseAudio en PipeWire](https://pipewire.pages.freedesktop.org/pipewire/page_pulse_modules.html).
- [Null sink](https://pipewire.pages.freedesktop.org/pipewire/page_pulse_module_null_sink.html) y [remap source](https://pipewire.pages.freedesktop.org/pipewire/page_pulse_module_remap_source.html).
- [Ejemplo de procesamiento RNNoise de Xiph](https://github.com/xiph/rnnoise/blob/main/examples/rnnoise_demo.c).
