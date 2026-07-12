# Conveyor Camera Monitor

Proyecto de inspección visual automática con **M-Duino 21+** (Industrial Shields) + Webcam + IA (PatchCore). El sensor de la cinta detecta piezas, el PC captura imagen e infiere en GPU (RTX 4070). Si la pieza es defectuosa (NG), el PC ordena al PLC parar la cinta. Todo se controla desde un frontend web.

## Estructura

```
TFMBigSchool/
├── backend/
│   ├── main.py              # API FastAPI + polling Modbus
│   ├── modbus_client.py     # Cliente Modbus TCP (lee PLC)
│   ├── camera.py            # Captura con OpenCV
│   ├── config.py            # Configuración centralizada (IP del PLC)
│   ├── find_plc.py          # Script para descubrir la IP del PLC
│   ├── trainer.py           # Modelo PatchCore + calibración
│   ├── requirements.txt     # Dependencias Python
│   └── images/              # Imágenes guardadas
├── frontend/
│   └── index.html           # Frontend monolítico (HTML+CSS+JS)
├── cctv/
│   ├── mediamtx.yml         # Config MediaMTX (streaming IP PoE)
│   └── nginx.conf           # Config Nginx (proxy opcional)
├── arduino/
│   └── conveyor_modbus_tcp/
│       └── conveyor_modbus_tcp.ino   # Código M-Duino 21+
├── mediamtx.exe             # Servidor streaming nativo (Windows)
├── tools/
│   └── ffmpeg.exe           # Puente RTSP -> RTMP
├── start-all.bat            # Inicio unificado: backend + CCTV
├── stop-all.bat             # Detener todo
├── docker-compose.yml       # Infraestructura CCTV (MediaMTX + FFmpeg + Nginx)
├── README.md                # Este archivo (intro + setup)
└── AGENTS.md                # Detalles técnicos para desarrolladores
```

> **Para detalles técnicos del hardware (pinout, flujo Modbus, calibración del modelo):** ver `AGENTS.md`.

## Requisitos de hardware

- **PC con GPU NVIDIA** (RTX 4070 o superior recomendado) + drivers actualizados
- **Python 3.12** (PyTorch CUDA 12.4 no tiene wheels para 3.14)
- **Webcam** conectada al PC donde corre el backend
- **M-Duino 21+** (Industrial Shields) - Arduino Mega 2560 con Ethernet W5500 integrado
  - Entrada: **I0_0** (pin 2) - Sensor fotoeléctrico de la cinta
  - Salida: **Q0_0** (pin 3) - Relé de parada de la cinta (HIGH = parada)
- **Conexión:** Cable Ethernet directo del M-Duino al PC (adaptador USB-Ethernet)
- **Librerías Arduino:**
  - `Ethernet` (incluida con placas compatibles)
  - `ArduinoModbus` (Library Manager de Arduino IDE)

## Configuración de red

Red link-local por cable Ethernet directo:
- **PC (interfaz USB-Ethernet):** `169.254.241.143`
- **M-Duino 21+ (PLC):** `169.254.241.100` (fija en el sketch .ino)
- **Backend:** se conecta a `169.254.241.100:502` (Modbus TCP)

Si necesitas cambiar la IP del PLC, modifica **ambos** archivos con la **misma IP**:
1. `backend/config.py` → cambia `PLC_HOST`
2. `arduino/conveyor_modbus_tcp/conveyor_modbus_tcp.ino` → cambia `IPAddress ip(...)`

> **Importante:** Ambos deben coincidir. Después de cambiar el .ino, **vuelve a subir el sketch al M-Duino**.

## Cómo descubrir la IP del PLC (si ya tiene una fija de fábrica)

Si no sabes la IP actual del PLC y quizás ya tiene una configurada, usa el script de escaneo:

```bash
cd backend
.\venv\Scripts\python.exe find_plc.py --scan
```

Esto escaneará los equipos que respondan en el puerto 502 (Modbus) dentro de la red `169.254.241.x`.

Si quieres probar una IP específica:
```bash
.\venv\Scripts\python.exe find_plc.py --host 169.254.241.100
```

## Instalación del backend

> **Nota GPU:** El entorno virtual debe crearse con **Python 3.12**. Si tienes Python 3.14, PyTorch CUDA no tiene ruedas oficiales aún.

```bash
cd backend
# Crea el venv con Python 3.12 explicitamente
py -3.12 -m venv venv

# Instala dependencias base
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Instala PyTorch con soporte CUDA 12.4 (para RTX 4070)
.\venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

Verifica que la GPU es detectada:
```bash
.\venv\Scripts\python.exe -c "import torch; print(torch.cuda.get_device_name(0))"
```

## Cámara IP PoE (CCTV en vivo)

El frontend integra una **cámara IP PoE** en tiempo real (vía WebRTC/MediaMTX) a la derecha de la captura de la webcam:

- **Izquierda:** imagen capturada por la webcam (inspección IA)
- **Derecha:** stream en vivo de la cámara IP PoE (`169.254.241.135:554`)
- **Debajo:** resultado OK/NG + botón CONTINUAR CINTA

Arquitectura CCTV:
- **MediaMTX** (`localhost:8889`) recibe el stream vía RTMP y lo expone por WebRTC
- **FFmpeg** hace pull RTSP de la cámara IP y publica RTMP a MediaMTX
- El frontend se conecta directamente por WebRTC (baja latencia)

## Ejecución (inicio unificado)

### Opción 1: Script nativo recomendado (Windows)

Haz doble clic en **`start-all.bat`** (en la raíz del proyecto):

```
[1/4] Iniciando MediaMTX   -> localhost:8889 (WebRTC)
[2/4] Esperando MediaMTX   -> 3s
[3/4] Iniciando FFmpeg     -> RTSP camara IP -> RTMP MediaMTX
[4/4] Iniciando Backend    -> http://localhost:8000
```

Abre el frontend en: **http://localhost:8000**

Para detener todo: **`stop-all.bat`** o cierra las ventanas.

### Opción 2: Docker Compose (infraestructura CCTV + web)

```bash
cd C:\proyectos\TFMBigSchool
docker-compose up -d
```

Esto levanta:
- **MediaMTX** en contenedor Linux (`localhost:8889` WebRTC, `localhost:1935` RTMP)
- **Nginx** sirviendo el frontend en `http://localhost`

**IMPORTANTE — Lo que Docker NO puede hacer en Windows:**
1. ❌ **Backend FastAPI** (necesita GPU NVIDIA RTX 4070 + PyTorch CUDA + Webcam USB)
2. ❌ **FFmpeg** (el contenedor Linux no ve la red link-local `169.254.x.x` de la cámara IP)
3. ❌ **Modbus TCP al PLC** (el contenedor no ve la red link-local del PLC)

**Por tanto, si usas Docker Compose, también debes ejecutar nativamente:**

```bash
# Terminal 1: FFmpeg (puente camara IP -> MediaMTX en Docker)
cd C:\proyectos\TFMBigSchool
.\tools\ffmpeg.exe -rtsp_transport udp -i rtsp://admin:@169.254.241.135:554/live -c copy -f flv rtmp://localhost:1935/cam

# Terminal 2: Backend FastAPI (GPU + Webcam + Modbus)
cd C:\proyectos\TFMBigSchool\backend
.\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Luego abre:
- **Frontend:** `http://localhost:8080` (servido por Nginx en Docker)
- **O directamente:** `http://localhost:8000` (servido por FastAPI nativo)

> **Recomendación:** Usa `start-all.bat` (Opción 1) para evitar esta complejidad.

### Opción 3: Manual (desarrollo)

```bash
# Terminal 1: MediaMTX
.\mediamtx.exe cctv\mediamtx.yml

# Terminal 2: FFmpeg (puente camara IP)
.\tools\ffmpeg.exe -rtsp_transport udp -i rtsp://admin:@169.254.241.135:554/live -c copy -f flv rtmp://localhost:1935/cam

# Terminal 3: Backend FastAPI
cd backend
.\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## Control de versiones (Git)

Este proyecto está bajo control de versiones con Git. A continuación los comandos básicos para trabajar con el repositorio:

### Comandos esenciales

```bash
# Ver estado de los archivos
git status

# Ver historial de commits
git log --oneline

# Añadir archivos modificados al stage
git add <archivo>
# O añadir todos los cambios
git add -A

# Crear un commit con mensaje descriptivo
git commit -m "descripcion del cambio"

# Ver diferencias antes de commitear
git diff
```

### Qué se versiona y qué no

Se versiona (controlado por Git):
- Código fuente Python, Arduino y frontend.
- Configuración (`*.yml`, `*.ini`, `*.py` de config).
- Tests y scripts de utilidad.
- Documentación (`README.md`, `AGENTS.md`).

Se ignora (`.gitignore`):
- Entorno virtual (`venv/`).
- Imágenes capturadas, datasets de entrenamiento, modelos entrenados y heatmaps generados.
- Archivos binarios ejecutables (`*.exe`, `*.dll`).
- Certificados SSL auto-generados, logs y carpetas de streaming (`RTMP/`).
- Caché de Python (`__pycache__/`, `*.pyc`).

## Funcionamiento (flujo de producción)

1. **M-Duino 21+** lee la entrada `I0.0` (sensor fotoeléctrico).
   - Solo acepta nueva pieza si `sensorLibre=true` y pasaron **2 segundos** desde la última.
2. Al detectar flanco ascendente (pieza nueva):
   - **PARA la cinta inmediatamente** (`Q0.0 = HIGH`).
   - Marca `sensorLibre = false` (placa ocupando el sensor).
   - Publica **coil 0 = 1** para que el backend lo sepa.
3. **Backend** hace polling cada **50 ms** por Modbus TCP.
4. Al ver coil 0 = 1:
   - Captura imagen con la webcam.
   - Ejecuta inferencia IA (PatchCore en GPU).
5. **Si pieza es OK:**
   - Backend escribe **coil 1 = 1**.
   - M-Duino recibe el comando:
     - **Arranca cinta** (`Q0.0 = LOW`).
     - Resetea detección.
     - **Ignora** el sensor hasta que la placa salga (sensor baje a LOW).
   - Backend espera **1 segundo** (cooldown) antes de volver a `waiting`.
6. **Si pieza es NG:**
   - Backend **no escribe nada**. La cinta **sigue parada**.
   - Operador revisa la pieza y pulsa **CONTINUAR CINTA** en el frontend.
   - Backend escribe **coil 1 = 1**.
   - M-Duino arranca cinta (`Q0.0 = LOW`).
7. Cuando la placa física sale del sensor (I0.0 = LOW):
   - M-Duino marca `sensorLibre = true`.
   - Listo para la siguiente pieza (tras el cooldown de 2s).

**Importante:**
- El sensor **SIEMPRE** para la cinta al detectar una pieza.
- El PC solo decide si la cinta puede seguir (OK) o debe quedar parada (NG).
- El Arduino ignora triggers mientras la placa anterior no haya salido del sensor (evita doble detección de la misma placa).
- Cooldown de **2 segundos** entre piezas.

8. **Frontend** muestra en tiempo real:
   - Estado de la conexión con el PLC
   - Estado del sensor
   - Estado de la cámara IP PoE (WebRTC)
   - Barra de estado del ciclo (`waiting → capturing → inspecting → ok/ng`)
   - **Izquierda:** imagen actual (original durante captura/inspección, **heatmap** tras inferencia)
   - **Derecha:** cámara IP PoE en vivo (WebRTC)
   - **Debajo:** resultado OK/NG + botón **CONTINUAR CINTA**
   - Info de la predicción (score, raw score, z-score)

## Entrenamiento de anomalías (PatchCore + GPU)

El proyecto usa **PatchCore** con backbone **Wide ResNet-50 v2**, que se entrena e infiere automáticamente en la **RTX 4070** (CUDA 12.4). Esto es mucho más rápido y preciso que CPU.

- Ve a la pestaña **Entrenamiento** en el frontend.
- Captura imágenes OK y NG con la cámara en vivo.
- Pulsa **ENTRENAR MODELO (PatchCore)**.
- El entrenamiento dura ~1-2 minutos en GPU.
- La inferencia es casi instantánea (~50-100 ms por imagen).

## API REST

- `GET /` → Frontend
- `GET /api/status` → Estado del sistema (JSON)
- `GET /api/captures` → Lista de imágenes (JSON)
- `GET /api/captures/<filename>` → Descargar imagen
- `POST /api/trigger` → Captura manual

## Testing y calidad de código

El backend incluye una suite de tests automáticos con **pytest**, **pytest-cov** y **pytest-mock**.

### Ejecutar tests

```bash
cd backend
.\venv\Scripts\python.exe -m pytest tests/ -v
```

### Ver cobertura

```bash
cd backend
.\venv\Scripts\python.exe -m pytest --cov=. --cov-report=term-missing tests/
```

### Tests disponibles

- **test_config.py** – validación de constantes de red.
- **test_find_plc.py** – escaneo de red y conectividad Modbus (mocks de socket).
- **test_camera.py** – gestión de la webcam (mocks de `cv2.VideoCapture`).
- **test_modbus_client.py** – inicialización, encolado de escrituras y ciclo de vida del hilo Modbus.
- **test_trainer.py** – calibración, guardado de imágenes de entrenamiento, conteo y preparación de dataset.
- **test_main.py** – **17 tests de integración** sobre todos los endpoints FastAPI.

### Estándares aplicados

- **Type hints** en todas las firmas de funciones y clases públicas (`typing` de Python).
- **Docstrings** descriptivas en módulos, clases y funciones públicas.
- Configuración en `backend/pytest.ini` y `backend/.coveragerc`.

## Conocimientos y capacidades aplicadas

- Desarrollo de software con Python y arquitectura modular desacoplada.
- API REST con FastAPI siguiendo principios de diseño limpio.
- Comunicación entre servicios mediante Modbus TCP y gestión de hilos concurrentes.
- Integración de hardware industrial (PLC/M-Duino) con software de alto nivel.
- Visión por computador con OpenCV y captura de imágenes en tiempo real.
- Inteligencia artificial aplicada a inspección visual: modelo PatchCore (anomalías) con calibración automática de umbrales.
- Inferencia en GPU con PyTorch y CUDA 12.4, optimizando latencia y rendimiento.
- Uso de IA generativa y asistentes de código (Copilot) durante todo el ciclo de desarrollo.
- Testing automatizado con pytest, mocks, cobertura de código y análisis de métricas de calidad.
- Type hints y documentación profesional con docstrings descriptivas.
- Contenerización con Docker Compose para servicios de streaming y proxy.
- Redes locales, configuración de interfaces link-local y diagnóstico de conectividad.
- Seguridad en el desarrollo: configuración por entornos, separación de secretos y buenas prácticas de codificación segura.
- Documentación técnica dirigida a equipos de desarrollo y operaciones.

## Notas

- Si no tienes PLC conectado, el backend seguirá funcionando y podrás usar **Captura manual** desde la API.
- Si no hay webcam disponible, la captura devolverá `None`.
- En Windows puede ser necesario ajustar el índice de la webcam en `camera.py` (`cv2.VideoCapture(0)`).
- Si el PLC no responde, verifica que el cable Ethernet esté bien conectado y que ambos dispositivos estén en la misma subred.
- **Cámara IP PoE:** La cámara debe estar en `169.254.241.135` con puerto RTSP `554` abierto. Si cambia de IP, actualiza `cctv/mediamtx.yml` y el comando FFmpeg en `start-all.bat`.
- La cámara IP transmite en **H265/HEVC**. El navegador debe soportar H265 en WebRTC (Chrome/Edge en Windows con hardware compatible generalmente funciona).
