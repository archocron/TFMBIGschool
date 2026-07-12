# Agent Context - TFMBigSchool

## Hardware Configuration

### PLC / Microcontroller
- **Device:** M-Duino 21+ (Industrial Shields)
- **Base board:** Arduino Mega 2560 compatible
- **Ethernet:** Built-in W5500 (Modbus TCP server, port 502)
- **IP:** `169.254.241.100` (link-local, conectado por USB-Ethernet al PC)
- **PC IP en esa interfaz:** `169.254.241.143`

### Pinout M-Duino 21+
| Señal | Pin M-Duino | Tipo | Descripción |
|-------|-------------|------|-------------|
| I0.0  | I0_0 (input digital) | ENTRADA | Sensor fotoeléctrico de la cinta |
| Q0.0  | Q0_0 (output digital) | SALIDA | Relé de parada de la cinta (HIGH = PARADA) |

**Nota:** En Industrial Shields, `I0_0` y `Q0_0` son macros que mapean a los pines correctos del Arduino Mega subyacente.

### Registro Modbus TCP (coils)
| Coil | Dirección | Dirección M-Duino | Función |
|------|-----------|-------------------|---------|
| 0    | 0         | -                 | Estado del sensor (I0.0) - Lectura |
| 1    | 1         | -                 | Comando liberar cinta - Escritura |

## Flujo de Producción

1. **Arduino** detecta flanco ascendente en I0.0 (solo si sensor está libre y pasó cooldown)
2. **Arduino** PARA la cinta inmediatamente (`Q0.0 = HIGH`)
3. **Arduino** pone `piezaDetectada = true`, marca `sensorLibre = false` y publica **coil 0 = 1**
4. **Backend** detecta coil 0 = 1 → captura imagen → inferencia IA (cinta ya está parada)
5. Si **OK**: backend escribe **coil 1 = 1**
   - Arduino lee coil 1 = 1 → **ARRANCA** cinta (`Q0.0 = LOW`) + resetea detección
   - Arduino **ignora** el sensor hasta que baje a LOW (la placa sale)
   - Backend entra en cooldown 1s
6. Si **NG**: backend **no escribe nada**. La cinta sigue **PARADA**.
7. Cuando operador pulsa "Continuar": backend escribe **coil 1 = 1**
   - Arduino lee coil 1 = 1 → **ARRANCA** cinta (`Q0.0 = LOW`) + resetea detección
   - Arduino ignora el sensor hasta que la placa salga (baje a LOW)
8. Cuando la placa sale del sensor (I0.0 = LOW) → Arduino marca `sensorLibre = true`
9. **Cooldown de 2s** desde la última detección antes de aceptar la siguiente pieza

**Importante:**
- El sensor SIEMPRE para la cinta al detectar una pieza.
- El PC solo decide si la cinta puede seguir (OK) o debe quedar parada (NG).
- El Arduino ignota triggers mientras la placa anterior no haya salido del sensor (evita doble detección de la misma placa).
- Cooldown de 2s entre piezas.

## Modelo IA
- **Modelo:** PatchCore
- **Backbone:** wide_resnet50_2
- **Input size:** 256×256
- **GPU:** RTX 4070, CUDA 12.4
- **Scores calibrados:**
  - OK: mean=28.1, std=2.1, max=39.8, p95=32.4
  - NG: mean=60.7, min=44.7, max=74.6
- **Threshold:** sigmoid centrado en `max_ok + 0.5*std = 40.92`

## Estado actual del sistema
- Backend: FastAPI + Uvicorn en puerto 8000
- Polling Modbus: cada 50ms
- Cooldown sensor: 1.5 segundos entre triggers
- Cooldown OK: 1 segundo después de OK antes de aceptar nueva pieza
- Estado producción: `waiting → capturing → inspecting → ok/cooldown → waiting` o `ng → waiting`

## Archivos clave
- `backend/main.py` - API + estado de producción
- `backend/modbus_client.py` - Cliente Modbus TCP
- `backend/trainer.py` - Modelo PatchCore + calibración
- `backend/config.py` - IP del PLC
- `arduino/conveyor_modbus_tcp/conveyor_modbus_tcp.ino` - Código Arduino
- `frontend/index.html` - UI monolítica

## Comandos útiles
```bash
# Descubrir PLC
.\venv\Scripts\python.exe find_plc.py --scan

# Verificar GPU
.\venv\Scripts\python.exe -c "import torch; print(torch.cuda.get_device_name(0))"

# Iniciar backend
cd backend
.\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## Control de versiones
- Repositorio Git inicializado en la raíz del proyecto (`C:\proyectos\TFMBigSchool`).
- Archivos ignorados: `venv/`, imágenes y modelos generados, binarios, certificados y caché Python (ver `.gitignore`).
- Commits descriptivos obligatorios. Antes de commitear revisar `git status` y `git diff`.

## Calidad de código y testing (nuevo)

### Tests
- Framework: **pytest** + **pytest-cov** + **pytest-mock**.
- Ubicación: `backend/tests/`.
- Configuración: `backend/pytest.ini` y `backend/.coveragerc`.
- Cobertura: se excluye `venv/`, `tests/` y `__pycache__/`.
- Ejecutar tests:
  ```bash
  cd backend
  .\venv\Scripts\python.exe -m pytest --cov=. --cov-report=term-missing tests/
  ```

### Type hints y docstrings
- Todo el backend tiene **type hints** en las firmas de funciones/clases.
- Todos los módulos tienen **docstrings** descriptivas (módulo, clase, función pública).
- Se usa `typing` (`Dict`, `List`, `Optional`, `Tuple`, `Any`, `Callable`).

### Endpoints testeados (test_main.py)
- `/api/status`
- `/api/trigger`, `/api/ok`, `/api/ng`, `/api/release`
- `/api/auto-predict/toggle`
- `/api/train/status`, `/api/train/save-ok`, `/api/train/save-ng`, `/api/train/start`
- `/api/predict-live`
- `/api/stream/preview`, `/api/stream/capture-ok`, `/api/stream/capture-ng`
- `/api/captures/{filename}`, `/api/heatmaps/{filename}`

### Notas de implementación
- Los pre/post-procesadores de Anomalib están desactivados para obtener scores raw reales.
- El cálculo de AUROC se hace manual con sklearn porque el evaluador de Anomalib está deshabilitado.
- Los heatmaps usan escala fija (`vmax` ~80-92) para que las piezas OK aparezcan en azul.
- El frontend muestra UNA sola imagen: original durante captura/inspección, heatmap tras inferencia.
