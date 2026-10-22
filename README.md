# Only Voice

Micrófono virtual local para llamadas en Linux. Hay dos modos:

- `denoise`: RNNoise reduce ruido ambiental; no identifica personas.
- `run`: VoxLock usa un perfil previo para intentar extraer una voz de una mezcla.

La reducción de ruido y el aislamiento con VoxLock ya se han probado en el
escritorio del usuario. La CLI y la ventana comparten un proceso de audio, por
lo que puedes iniciarlo desde una y detenerlo desde la otra.

## Uso diario

Desde el proyecto, abre la ventana:

```sh
./only-voice gui
```

Selecciona el micrófono, deja **Solo mi voz** y pulsa **Activar filtro**. En tu
aplicación de llamadas, elige **Only_Voice** como entrada. La ventana muestra el
estado del perfil y los niveles reales de entrada y salida. El modo **Reducir
ruido** permite usar RNNoise cuando no quieras seleccionar una voz.
Los niveles reúnen el audio de cada intervalo de unos 80 ms; las barras suavizan
el movimiento al ritmo de la pantalla, con subida rápida y caída gradual.

En **Solo mi voz**, el selector **Variante de voz** permite elegir:

| Variante | Uso |
| --- | --- |
| **Equilibrado · INT8** | Predeterminada. Buen equilibrio entre precisión y consumo de CPU. |
| **Rápido · INT8-full** | Prioriza el rendimiento en CPU, con algo más de pérdida de precisión. |
| **Alta precisión · FP16** | Precisión cercana a FP32 y descarga menor; puede consumir más CPU que INT8. |
| **Precisión completa · FP32** | Modelo de referencia sin cuantización; puede consumir más CPU que INT8. |

La selección se recuerda al activar el filtro. Detén el filtro para cambiar de
variante. Tu perfil actual sirve para las cuatro: no tienes que volver a grabarte.
Los archivos que falten se descargan al activar la variante por primera vez;
la ventana muestra la preparación y permite cancelar el inicio. Después se
reutilizan sin conexión. Si la descarga o carga falla, se muestra el error sin
cambiar a otra variante. **Reducir ruido** sigue usando RNNoise y no necesita
estos modelos.

La precisión numérica no garantiza una mejora audible. Compara las variantes
con tu micrófono y equipo. No cambian los bloques de 40 ms ni los búferes de
audio del proyecto; una inferencia más rápida no equivale por sí sola a reducir
la latencia total de una llamada.

La interfaz GTK usa un tema oscuro basado en `~/.config/eww/DESING.MD`:
negro OLED, tarjetas `#0a0a0a`, acento verde `#8ac7b0`, Adwaita Sans y controles
tonales. Su hoja GTK 4 está en `only_voice/styles/zephyx.css`.

**Grabar mi voz** registra 15 segundos tras una cuenta atrás. **Actualizar mi
voz** sustituye el perfil solo cuando el registro termina correctamente: si
cancelas o falla, conserva el anterior. Mientras grabas, el botón principal
permite cancelar. Detén el filtro antes de actualizar la voz o cambiar entrada.

Puedes cerrar la ventana o terminal con el filtro activo: continúa en segundo
plano hasta que lo desactives. Cerrar la ventana durante un registro cancela
esa grabación. No se inicia automáticamente al arrancar Linux.

También puedes usar únicamente la terminal:

| Comando | Acción |
| --- | --- |
| `./only-voice` o `./only-voice start` | Activar el filtro en segundo plano |
| `./only-voice stop` | Detenerlo o cancelar el registro |
| `./only-voice status` | Consultar el estado |
| `./only-voice profile` | Crear o actualizar la voz con 15 s de grabación |
| `./only-voice devices` | Ver micrófonos disponibles |
| `./only-voice logs` | Consultar detalles si algo falla |

Se recuerdan el último micrófono, modo y variante usados. Para elegirlos desde la CLI:

```sh
./only-voice start --source NOMBRE_DE_ENTRADA
./only-voice start --mode noise
./only-voice start --mode voice --precision fp32
./only-voice profile --wav recordings/me.wav
```

`start --precision` acepta `int8`, `int8-full`, `fp16` y `fp32`. Sin esa opción
reutiliza la última selección (inicialmente `int8`). Para cambiar con el filtro
activo, ejecuta primero `./only-voice stop`. `status` muestra la variante del
proceso; `status --json` la incluye en el campo `precision`.

### Comando global y menú de aplicaciones

```sh
./install.sh
```

Instala un enlace en `~/.local/bin/only-voice` y **Only Voice** en el menú de
aplicaciones. No necesita `sudo` y no sustituye un comando ajeno con el mismo
nombre. Después puedes abrir la ventana desde el menú o ejecutar
`only-voice gui` desde cualquier carpeta. Si `~/.local/bin` no está en tu `PATH`, el
instalador lo indica; añade ese directorio a la configuración de tu shell.
No muevas el proyecto después de instalar el enlace.

La ventana usa GTK 4 y PyGObject del sistema, con soporte nativo de Wayland.
En Arch se instalan con `sudo pacman -S gtk4 python-gobject`. El audio sigue
usando el entorno preparado por `voice.sh`. Si GTK no está disponible, las
sesiones X11 pueden usar la ventana alternativa con Tk.

Si la ventana no aparece, ejecuta `./only-voice gui` desde un terminal de tu
escritorio. Los errores de arranque quedan en `.runtime/gui.log`; también se
intenta mostrar una notificación del escritorio cuando falla el acceso del menú.

Las lecturas de estado, la consulta de micrófonos y las operaciones de audio se
ejecutan fuera del hilo gráfico. Solo se actualizan los controles que cambian.
El lanzador usa Cairo para esta ventana pequeña; puedes elegir otro renderizador
con `GSK_RENDERER=gl ./only-voice gui`. Esto se aplica únicamente a Only Voice.

## Requisitos e instalación básica

Linux con PulseAudio o PipeWire con `pipewire-pulse`; utilidades `pactl`, `parec`
y `pacat`; Python 3.11 o superior. El modo `denoise` requiere librnnoise.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
./start.sh doctor
./start.sh devices
./start.sh
```

Sin argumentos, `start.sh` mantiene el modo RNNoise. Selecciona **Only_Voice**
como entrada en la aplicación de llamadas. Ctrl+C detiene el procesamiento.

```sh
./start.sh denoise --source NOMBRE_DE_ENTRADA
```

## Preparar el aislamiento de voz

Ejecuta en una terminal del escritorio, con conexión a Internet:

```sh
./voice.sh
```

El lanzador:

1. Prepara `.venv-voice` con Python 3.12 y VoxLock 1.1.1. Obtiene Python con `uv`
   si hace falta y guarda herramientas y cachés en `.tools/`.
2. Descarga los modelos ONNX de la variante elegida y comprueba que cargan antes de grabar.
3. Si falta el perfil, muestra una cuenta atrás y graba 15 segundos. Habla tú
   solo, sin otras voces de fondo y con volumen natural.
4. Selecciona los tres segundos de mayor energía y calcula las características
   de referencia. Guarda `profiles/me.npz` y elimina la grabación temporal.
5. Arranca el micrófono virtual en segundo plano. Selecciona **Only_Voice** en la llamada.

Las siguientes ejecuciones reutilizan entorno, modelos y perfil. No se necesita
`sudo`. El flujo actual no usa SpeechBrain, PyTorch ni torchaudio; los paquetes
instalados durante el intento anterior se conservan, pero no se importan.

Para elegir una entrada o usar una muestra existente:

```sh
./voice.sh --source NOMBRE_DE_ENTRADA
./voice.sh --wav recordings/me.wav
./voice.sh --precision int8-full
```

`voice.sh` también recuerda la última variante cuando se omite `--precision`.
El registro del perfil utiliza siempre el codificador original `enroll.onnx`,
cuyas características son compatibles con las cuatro variantes. En el primer
registro con FP16 también se preparan los modelos del modo predeterminado.

La muestra externa debe ser WAV PCM16 y durar entre 5 y 60 segundos. Se convierte
a mono y 16 kHz si hace falta. Se rechazan muestras casi silenciosas, pero no
se comprueba automáticamente que hable una sola persona.

Para crear otro perfil sin sobrescribir el actual:

```sh
./start.sh enroll --record --profile profiles/other.npz
./start.sh run --profile profiles/other.npz
```

Otros comandos útiles:

```sh
./start.sh check-model
./start.sh download-model --precision fp16
./start.sh check-model --precision fp16
./start.sh run --threads 4
./start.sh run --precision fp16
./start.sh run --model models/voxlock/onnx --profile profiles/me.npz
```

Los comandos de bajo nivel `download-model`, `check-model` y `run` usan INT8
si se omite `--precision`; no consultan las preferencias de la ventana.
`run` requiere los archivos locales de la variante indicada.

`start.sh` usa `.venv-voice` para los comandos de voz cuando está instalado.
`doctor` informa de dependencias y acceso al servidor; `check-model` comprueba
que los modelos locales cargan. Ninguno mide la calidad de separación.

## Modelo y errores de descarga

La primera implementación dependía de `penta2himajin/tse-conv-tasnet-48k`, que
ahora devuelve HTTP 401 en la descarga pública. Se ha retirado ese adaptador;
repetir su descarga no resuelve el problema. Sus perfiles JSON no sirven para
el modelo nuevo: hay que crear un perfil NPZ.

El nuevo adaptador usa la API de streaming de
[VoxLock 1.1.1](https://pypi.org/project/voxlock/1.1.1/) y el repositorio anunciado
por su autor, [arbazsiddiqui/voxlock](https://huggingface.co/arbazsiddiqui/voxlock).
La revisión se fija a `a50f4e1d109301d4b6f61dec57ebb1a61e7d8f03`, igual que en el
[código de esa API](https://github.com/arbazsiddiqui/voxlock/blob/main/voxlock/core.py).
Las variantes utilizan estos archivos de `onnx/`:

| Variante | Codificador | Extractor |
| --- | --- | --- |
| `int8` | `enroll.onnx` | `chunk_int8.onnx` |
| `int8-full` | `enroll.onnx` | `chunk_int8_full.onnx` |
| `fp16` | `enroll_fp16.onnx` | `chunk_fp16.onnx` |
| `fp32` | `enroll.onnx` | `chunk.onnx` |

El autor anuncia unos 75 MB para INT8 y licencia Apache-2.0. Estos pesos no se
redistribuyen en el proyecto. Los archivos compartidos se descargan una sola vez.

El descargador solicita acceso público con `token=False`,
sin usar credenciales guardadas. Si recibe HTTP 401/403 o 404, explica que el
artefacto no está disponible desde esa conexión y se detiene antes de grabar.
No cambia silenciosamente a transmitir el micrófono original.

## Audio, privacidad y latencia

RNNoise procesa mono a 48 kHz en bloques de 480 muestras, 10 ms. VoxLock procesa
mono a 16 kHz en bloques de 640 muestras, 40 ms, y admite salidas más cortas al
iniciar el streaming. El servidor de audio puede convertir la frecuencia para
la aplicación de llamadas. La banda de audio del aislamiento queda limitada
por los 16 kHz del extractor.

Solo se transporta la salida del procesador. El adaptador utiliza el perfil
guardado desde el principio, sin autoinscribirse con la voz más fuerte de la
llamada. El perfil contiene características de referencia, no el WAV original,
y se carga sin pickle. No se graban llamadas ni se envía su audio a un servidor.
`models/`, `profiles/`, `recordings/`, `.venv-voice/` y `.tools/` se excluyen de Git.

La cola de Python admite tres bloques. Si se descartan bloques antiguos por
retraso, se reinicia el estado del extractor manteniendo la identidad del
perfil. No se vuelve a ejecutar la inferencia de registro en ese reinicio.

Se solicitan buffers de 20 ms para RNNoise y de 80 ms para VoxLock, que el
servidor puede ajustar. La comprobación de arranque compara la media de
procesamiento con la duración de cada bloque; si el equipo no sigue el ritmo,
se detiene. Cada cinco segundos muestra tiempo medio y bloques descartados.
**Estos tiempos no equivalen a la latencia total de una llamada.**

Los módulos `module-null-sink` y `module-remap-source` son temporales y tienen
nombres únicos. No se cambian los dispositivos predeterminados del sistema.
Ctrl+C y SIGTERM intentan retirar solo los módulos de esa ejecución, en orden
inverso. Si un cierre abrupto los deja cargados, identifica los `only_voice_…`
con `pactl list modules short` y retira sus identificadores mediante
`pactl unload-module ID`, primero el remap y después el null sink.

La separación puede dejar voces ajenas, distorsionar la voz elegida o recortar
palabras. Falta probar español, voces solapadas, reverberación, CPU bajo carga
y latencia de extremo a extremo. No hay cancelación de eco acústico ni servicio
que se inicie con Linux.

## Desarrollo

### Trabajo con Git

La rama principal es `main`. Para empezar un cambio:

```sh
git switch main
git pull --ff-only
git switch -c mejora/nombre-del-cambio
```

Después de editar y ejecutar las pruebas, revisa y guarda los archivos cambiados:

```sh
git status
git diff
git add ruta/al/archivo
git diff --cached
git commit -m "Describe el cambio"
git push -u origin HEAD
```

`commit` guarda una versión local; `push` la sube a GitHub. Abre allí una pull
request hacia `main` para revisar e integrar la mejora. En los siguientes envíos
de la misma rama basta con `git push`.

No añadas modelos, perfiles de voz, grabaciones ni credenciales: `.gitignore`
los excluye junto con los entornos y archivos temporales locales.

### Pruebas

```sh
.venv-voice/bin/python -m unittest discover -s tests -v
/usr/bin/python3 -m unittest discover -s tests -p test_gtk_controller.py -v
bash -n only-voice install.sh start.sh voice.sh
```

Las pruebas usan RNNoise real con ruido sintético si está instalado. Para
VoxLock usan un doble de la API: comprueban perfiles, registro, salida variable,
reinicio, errores HTTP y el transporte a 16 kHz con procesos de audio simulados.
También comprueban la limpieza de módulos y muestras temporales ante errores o
cancelaciones, el proceso compartido por CLI/GUI y el instalador del menú.
Los controles GTK se comprueban también sin pantalla: seleccionar entrada,
activar, detener, registrar y cancelar, además de evitar actualizaciones
repetidas de controles y bloqueos por lecturas lentas. La prueba de la ventana
nativa se omite cuando no hay acceso a una sesión gráfica; no valida el aspecto
ni la respuesta visual del escritorio en ese caso.
No descargan pesos, no acceden al micrófono y **no prueban la
calidad ni la compatibilidad acústica de los pesos reales**.

Se ha comprobado además el nuevo proceso con los pesos reales de VoxLock y un
servidor de audio simulado: arranque, métricas y parada con retirada de módulos.
Esto no sustituye una prueba de latencia de extremo a extremo en una llamada.

Referencias del transporte:
[módulos PulseAudio en PipeWire](https://pipewire.pages.freedesktop.org/pipewire/page_pulse_modules.html),
[null sink](https://pipewire.pages.freedesktop.org/pipewire/page_pulse_module_null_sink.html),
[remap source](https://pipewire.pages.freedesktop.org/pipewire/page_pulse_module_remap_source.html).
La adaptación PCM de RNNoise sigue el
[ejemplo de Xiph](https://github.com/xiph/rnnoise/blob/main/examples/rnnoise_demo.c).
