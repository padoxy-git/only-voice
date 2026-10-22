Only Voice ahora funciona como aplicación gráfica controlada desde el icono de la bandeja en Windows y Linux. Se inicia oculto; el icono permite abrir Configuración, activar/desactivar el filtro y salir. Cerrar la ventana mantiene el filtro activo; Salir detiene el audio.

- Windows x64: instalador `setup.exe` por usuario y ZIP portable, sin consola. Necesita Windows 10/11 y [VB-CABLE](https://vb-audio.com/Cable/) instalado por separado (enlace también disponible en Configuración). Reinicia después de instalar el controlador. Only Voice envía el audio a CABLE Input; en la llamada selecciona CABLE Output.
- Linux x86_64: paquetes `.deb`, `.rpm` y `.pkg.tar.zst`, con Python, Qt, ONNX y RNNoise incluidos. Necesita PulseAudio o PipeWire con compatibilidad PulseAudio y una bandeja del sistema (en GNOME, una extensión AppIndicator).
- Configuración gráfica de micrófono, modo de filtro, variante del modelo, registro de voz e importación de WAV; niveles y registro de actividad.
- Los modelos se descargan en el primer uso de «Solo mi voz». «Reducir ruido» funciona sin descarga. Los datos se guardan en el directorio del usuario y se conservan al actualizar.

Paquetes sin firma digital. `SHA256SUMS` contiene los hashes de los cinco archivos. Las pruebas de CI comprueban el transporte de audio simulado, los controles de la GUI y la carga de RNNoise en los ejecutables; no equivalen a una prueba acústica en hardware Windows real.
