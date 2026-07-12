import os
import threading
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from modbus_client import ModbusPlcClient
from camera import capture_image, IMAGE_DIR, get_camera_preview, capture_training_image
from trainer import save_to_training, get_train_counts, train_model, predict, ANOMALIB_AVAILABLE, HEATMAP_DIR, MODEL_INFO

app = FastAPI(title="Conveyor Camera Monitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== ESTADO GLOBAL =====
latest_capture = None
capture_count = 0
last_decision = None
auto_predict = False  # Modo prediccion automatica (manual)

# Estado de produccion automatica
production_state = "waiting"   # waiting, capturing, inspecting, ok, ng, cooldown
last_inspection_result = None  # OK / NG / ERROR
last_heatmap_file = None
last_predict_result = None

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

# ===== LOGICA DE PRODUCCION =====

def on_trigger() -> None:
    """Callback ejecutado por el cliente Modbus cuando detecta flanco ascendente.

    Gestiona el ciclo completo: captura de imagen, inferencia automática y
    decisión de arrancar o mantener parada la cinta.
    """
    global latest_capture, capture_count, last_decision
    global production_state, last_inspection_result, last_heatmap_file, last_predict_result

    print(f"[MAIN] on_trigger iniciado (estado={production_state})")

    # Si estamos en cooldown, NG, o acabamos de dar OK, ignorar triggers del PLC
    if production_state in ("cooldown", "ng", "capturing", "inspecting", "ok"):
        print(f"[MAIN] Trigger ignorado, estado actual={production_state}")
        return

    try:
        # Estado: capturando
        production_state = "capturing"
        filename = capture_image()
        if filename:
            latest_capture = filename
            capture_count += 1
            last_decision = None
            last_inspection_result = None
            last_heatmap_file = None
            last_predict_result = None
            print(f"[MAIN] Captura #{capture_count} completada: {filename}")
            
            # Inferencia automatica
            production_state = "inspecting"
            img_path = os.path.join(IMAGE_DIR, filename)
            result = predict(img_path)
            
            if result.get("ok"):
                last_predict_result = result
                last_heatmap_file = result.get("heatmap")
                decision = result.get("result", "UNKNOWN")
                last_inspection_result = decision
                last_decision = decision
                print(f"[MAIN] Inferencia: {decision} score={result.get('score',0):.3f} raw={result.get('raw_score',0):.1f}")
                
                if decision == "OK":
                    production_state = "ok"
                    # OK: arrancar cinta (Arduino la habia parado al detectar la pieza)
                    plc.queue_write(1, True)
                    print("[MAIN] OK -> Enviando comando para ARRANCAR cinta")
                    
                    # Cooldown 1s: la placa inspeccionada se aleja antes de aceptar siguiente
                    def _cooldown_ok():
                        global production_state
                        time.sleep(1.0)
                        if production_state == "ok":
                            production_state = "waiting"
                            print("[MAIN] Cooldown OK terminado, esperando siguiente placa")
                    threading.Thread(target=_cooldown_ok, daemon=True).start()
                else:
                    # NG: la cinta ya esta parada por el Arduino, queda parada
                    production_state = "ng"
                    print("[MAIN] NG detectado -> Cinta queda PARADA. Esperando operador (Continuar).")
            else:
                # Error en inferencia -> tratar como NG por seguridad
                production_state = "ng"
                last_inspection_result = "ERROR"
                last_decision = "NG"
                print(f"[MAIN] ERROR inferencia: {result.get('error')} -> Cinta DETENIDA")
        else:
            print("[MAIN] on_trigger: capture_image devolvio None")
            production_state = "waiting"
    except Exception as e:
        print(f"[MAIN] ERROR en on_trigger: {e}")
        import traceback
        traceback.print_exc()
        production_state = "waiting"

from config import PLC_HOST, PLC_PORT

plc = ModbusPlcClient(host=PLC_HOST, port=PLC_PORT, on_trigger=on_trigger)

@app.on_event("startup")
async def startup_event():
    plc.start()
    print("Backend iniciado. Polling Modbus TCP activo.")

@app.on_event("shutdown")
async def shutdown_event():
    plc.stop()

@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    """Devuelve el estado global del backend: PLC, producción, última captura y modelo."""
    return {
        "plc_connected": plc.connected,
        "sensor_active": plc.last_state,
        "latest_capture": latest_capture,
        "capture_count": capture_count,
        "last_decision": last_decision,
        "auto_predict": auto_predict,
        "anomalib_available": ANOMALIB_AVAILABLE,
        # Estado de produccion
        "production_state": production_state,
        "last_inspection_result": last_inspection_result,
        "last_heatmap": last_heatmap_file,
        "last_predict_score": last_predict_result.get("score") if last_predict_result else None,
        "last_predict_raw": last_predict_result.get("raw_score") if last_predict_result else None,
        "last_predict_z": last_predict_result.get("z_score") if last_predict_result else None,
        "model_info": MODEL_INFO,
    }

@app.get("/api/captures/{filename}")
def get_capture(filename: str) -> Any:
    """Sirve una imagen capturada por nombre."""
    path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/captures/thumb/{filename}")
def get_capture_thumb(filename: str) -> Any:
    """Sirve el thumbnail de una captura; si no existe devuelve la original."""
    thumb_name = filename.replace(".jpg", "_thumb.jpg")
    path = os.path.join(IMAGE_DIR, thumb_name)
    if os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    orig_path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(orig_path):
        return FileResponse(orig_path, media_type="image/jpeg")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.post("/api/trigger")
def manual_trigger() -> Dict[str, Any]:
    """Dispara una captura manual desde la cámara."""
    global latest_capture, capture_count
    filename = capture_image()
    if filename:
        latest_capture = filename
        capture_count += 1
    return {"filename": filename, "ok": filename is not None}


@app.post("/api/ok")
def ok_decision() -> Dict[str, Any]:
    """Marca la última pieza como OK y ordena arrancar la cinta."""
    global last_decision, production_state
    last_decision = "OK"
    # Si estabamos en NG, pasar a cooldown y luego waiting
    if production_state == "ng":
        production_state = "cooldown"
        plc.queue_write(1, True)
        def _reset():
            global production_state
            time.sleep(1.0)
            if production_state == "cooldown":
                production_state = "waiting"
                print("[MAIN] Continuar tras NG -> esperando siguiente placa")
        threading.Thread(target=_reset, daemon=True).start()
    else:
        plc.queue_write(1, True)
    return {"ok": True, "decision": "OK"}


@app.post("/api/ng")
def ng_decision() -> Dict[str, Any]:
    """Marca la última pieza como NG (la cinta sigue parada)."""
    global last_decision
    last_decision = "NG"
    return {"ok": True, "decision": "NG"}


@app.post("/api/release")
def release_conveyor() -> Dict[str, Any]:
    """Reanuda la cinta manualmente desde estado NG."""
    global production_state
    # Reanudar cinta desde estado NG
    if production_state == "ng":
        production_state = "cooldown"
        plc.queue_write(1, True)
        def _reset():
            global production_state
            time.sleep(1.0)
            if production_state == "cooldown":
                production_state = "waiting"
                print("[MAIN] Cinta reanudada tras NG, esperando siguiente placa")
        threading.Thread(target=_reset, daemon=True).start()
    else:
        plc.queue_write(1, True)
    return {"ok": True, "action": "release"}

# ========== ENDPOINTS DE ENTRENAMIENTO ==========

@app.get("/api/train/status")
def train_status() -> Dict[str, Any]:
    """Devuelve el número de imágenes de entrenamiento disponibles."""
    counts = get_train_counts()
    return {
        "ok": True,
        "counts": counts,
        "anomalib_available": ANOMALIB_AVAILABLE,
    }


@app.post("/api/train/save-ok")
def save_training_ok() -> Dict[str, Any]:
    """Guarda la última captura como imagen OK de entrenamiento."""
    if latest_capture is None:
        return {"ok": False, "error": "No hay captura actual para guardar"}
    success = save_to_training(latest_capture, "ok")
    counts = get_train_counts()
    return {"ok": success, "counts": counts}


@app.post("/api/train/save-ng")
def save_training_ng() -> Dict[str, Any]:
    """Guarda la última captura como imagen NG de entrenamiento."""
    if latest_capture is None:
        return {"ok": False, "error": "No hay captura actual para guardar"}
    success = save_to_training(latest_capture, "ng")
    counts = get_train_counts()
    return {"ok": success, "counts": counts}


@app.post("/api/train/start")
def start_training() -> Dict[str, Any]:
    """Lanza el entrenamiento del modelo PatchCore con las imágenes actuales."""
    result = train_model()
    return result


@app.post("/api/predict-live")
def do_predict_live() -> Dict[str, Any]:
    """Captura imagen fresca desde la cámara y la predice inmediatamente."""
    global latest_capture, capture_count, last_decision

    print("[MAIN] Predict-live: capturando imagen fresca...")
    filename = capture_image()
    if not filename:
        return {"ok": False, "error": "No se pudo capturar imagen de la camara"}

    latest_capture = filename
    capture_count += 1
    last_decision = None
    print(f"[MAIN] Predict-live: imagen capturada {filename}")

    img_path = os.path.join(IMAGE_DIR, filename)
    result = predict(img_path)

    if result.get("ok"):
        last_decision = result.get("result", "UNKNOWN")
        print(f"[MAIN] Predict-live: resultado = {last_decision}")

    result["filename"] = filename
    return result


@app.post("/api/auto-predict/toggle")
def toggle_auto_predict() -> Dict[str, Any]:
    """Activa o desactiva el modo de predicción automática manual."""
    global auto_predict
    auto_predict = not auto_predict
    return {"ok": True, "auto_predict": auto_predict}

# ========== ENDPOINTS DE STREAMING / PREVIEW ==========

from fastapi.responses import StreamingResponse
from io import BytesIO

@app.get("/api/stream/preview")
def stream_preview() -> Any:
    """Devuelve un frame JPEG en tiempo real para preview de la cámara."""
    frame_bytes = get_camera_preview()
    if frame_bytes is None:
        return JSONResponse({"error": "No se pudo capturar preview"}, status_code=503)
    return StreamingResponse(BytesIO(frame_bytes), media_type="image/jpeg")


@app.post("/api/stream/capture-ok")
def stream_capture_ok() -> Dict[str, Any]:
    """Captura desde la cámara y guarda directamente en el dataset OK."""
    filename = capture_training_image("ok")
    if filename:
        counts = get_train_counts()
        return {"ok": True, "filename": filename, "counts": counts}
    return {"ok": False, "error": "No se pudo capturar"}


@app.post("/api/stream/capture-ng")
def stream_capture_ng() -> Dict[str, Any]:
    """Captura desde la cámara y guarda directamente en el dataset NG."""
    filename = capture_training_image("ng")
    if filename:
        counts = get_train_counts()
        return {"ok": True, "filename": filename, "counts": counts}
    return {"ok": False, "error": "No se pudo capturar"}


@app.get("/")
def root() -> Any:
    """Sirve el frontend monolítico (index.html) sin caché."""
    response = FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# Endpoint para heatmaps
@app.get("/api/heatmaps/{filename}")
def get_heatmap(filename: str) -> Any:
    """Sirve una imagen de heatmap generada tras la inferencia."""
    path = os.path.join(HEATMAP_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    return JSONResponse({"error": "not found"}, status_code=404)

# Servir imagenes estaticas
app.mount("/images", StaticFiles(directory=IMAGE_DIR), name="images")
app.mount("/heatmaps", StaticFiles(directory=HEATMAP_DIR), name="heatmaps")
