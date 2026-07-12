import os
import shutil
import glob
import cv2
import numpy as np
from datetime import datetime
import math
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(__file__)
TRAIN_OK_DIR = os.path.join(BASE_DIR, "training", "ok")
TRAIN_NG_DIR = os.path.join(BASE_DIR, "training", "ng")
MODELS_DIR = os.path.join(BASE_DIR, "models")
IMAGE_DIR = os.path.join(BASE_DIR, "images")
ANOMALIB_DATA_DIR = os.path.join(BASE_DIR, "training", "anomalib_dataset")
HEATMAP_DIR = os.path.join(BASE_DIR, "heatmaps")


def ensure_dirs() -> None:
    """Crea los directorios de entrenamiento y modelos si no existen."""
    for d in [TRAIN_OK_DIR, TRAIN_NG_DIR, MODELS_DIR, HEATMAP_DIR]:
        os.makedirs(d, exist_ok=True)


ensure_dirs()

model_trained = False
anomalib_model = None

# Configuracion del modelo
MODEL_NAME = "Patchcore"
BACKBONE = "wide_resnet50_2"
LAYERS = ["layer2", "layer3"]
INPUT_SIZE = 256
CORESET_RATIO = 0.1

# Info del modelo activo (para mostrar en frontend)
MODEL_INFO: Dict[str, Any] = {
    "name": MODEL_NAME,
    "backbone": BACKBONE,
    "input_size": INPUT_SIZE,
    "checkpoint": None,
    "trained_at": None,
}

calibration: Dict[str, Optional[float]] = {
    "mean_ok": None,
    "std_ok": None,
    "max_ok": None,
    "p95_ok": None,
    "p99_ok": None,
    "mean_ng": None,
    "min_ng": None,
    "max_ng": None,
    "count_ok": 0,
    "count_ng": 0,
}

ANOMALIB_AVAILABLE = False
try:
    import torch
    import torchvision.transforms as T
    from anomalib.models import Patchcore
    from anomalib.data import Folder
    from anomalib.engine import Engine
    ANOMALIB_AVAILABLE = True
    print(f"[TRAINER] Anomalib disponible ({MODEL_NAME}/{BACKBONE})")
except Exception as e:
    print(f"[TRAINER] Anomalib NO disponible: {e}")


def _load_calibration() -> None:
    global calibration
    p = os.path.join(MODELS_DIR, "calibration.npz")
    if os.path.exists(p):
        d = np.load(p)
        calibration["mean_ok"] = float(d.get('mean_ok', 0))
        calibration["std_ok"] = float(d.get('std_ok', 1))
        calibration["max_ok"] = float(d.get('max_ok', 0))
        calibration["p95_ok"] = float(d.get('p95_ok', 0))
        calibration["p99_ok"] = float(d.get('p99_ok', 0))
        calibration["mean_ng"] = float(d.get('mean_ng', 0))
        calibration["min_ng"] = float(d.get('min_ng', 0))
        calibration["max_ng"] = float(d.get('max_ng', 0))
        calibration["count_ok"] = int(d.get('count_ok', 0))
        calibration["count_ng"] = int(d.get('count_ng', 0))
        print(f"[TRAINER] Calibracion: mean_ok={calibration['mean_ok']:.2f}, p95={calibration['p95_ok']:.2f}, p99={calibration['p99_ok']:.2f}, mean_ng={calibration['mean_ng']:.2f}")

def _save_calibration(ok_scores: List[float], ng_scores: List[float]) -> None:
    global calibration
    ok_scores_arr = np.array(ok_scores)
    calibration["mean_ok"] = float(np.mean(ok_scores_arr))
    calibration["std_ok"] = float(np.std(ok_scores_arr)) if len(ok_scores_arr) > 1 else 1.0
    calibration["max_ok"] = float(np.max(ok_scores_arr))
    calibration["p95_ok"] = float(np.percentile(ok_scores_arr, 95))
    calibration["p99_ok"] = float(np.percentile(ok_scores_arr, 99))
    calibration["count_ok"] = len(ok_scores_arr)
    
    if len(ng_scores) > 0:
        ng_scores_arr = np.array(ng_scores)
        calibration["mean_ng"] = float(np.mean(ng_scores_arr))
        calibration["min_ng"] = float(np.min(ng_scores_arr))
        calibration["max_ng"] = float(np.max(ng_scores_arr))
        calibration["count_ng"] = len(ng_scores_arr)
    else:
        calibration["mean_ng"] = calibration["max_ok"] * 1.5
        calibration["min_ng"] = calibration["max_ok"]
        calibration["max_ng"] = calibration["max_ok"] * 2.0
        calibration["count_ng"] = 0

    p = os.path.join(MODELS_DIR, "calibration.npz")
    np.savez(p,
             ok_scores=ok_scores_arr,
             ng_scores=np.array(ng_scores),
             **calibration)
    print(f"[TRAINER] Calibracion guardada: mean_ok={calibration['mean_ok']:.2f}, p95={calibration['p95_ok']:.2f}, p99={calibration['p99_ok']:.2f}, mean_ng={calibration['mean_ng']:.2f}")

def _load_model_for_inference() -> Any:
    """Carga el modelo desde checkpoint y desactiva pre/post processors para control manual.""

    Returns:
        Instancia del modelo PatchCore en modo evaluación, o ``None`` si falla.
    """
    ckpt_path = os.path.join(MODELS_DIR, "patchcore.ckpt")
    if not os.path.exists(ckpt_path):
        return None
    try:
        import torch
        # PyTorch 2.6+ requiere weights_only=False para checkpoints con clases custom
        checkpoint = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        state_dict = checkpoint.get("state_dict", checkpoint)
        
        model = Patchcore(
            backbone=BACKBONE,
            layers=LAYERS,
            coreset_sampling_ratio=CORESET_RATIO,
            pre_processor=False,
            post_processor=False,
            evaluator=False,
            visualizer=False,
        )
        model.load_state_dict(state_dict, strict=False)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        model.eval()
        model.pre_processor = None
        model.post_processor = None
        print(f"[TRAINER] Modelo movido a {device}")
        return model
    except Exception as e:
        print(f"[TRAINER] Error cargando modelo: {e}")
        import traceback
        traceback.print_exc()
        return None

def _try_load_existing_model() -> None:
    """Al arrancar, carga el último modelo entrenado si está disponible."""
    global model_trained, anomalib_model, MODEL_INFO
    if not ANOMALIB_AVAILABLE:
        return
    anomalib_model = _load_model_for_inference()
    if anomalib_model is not None:
        model_trained = True
        ckpt = os.path.join(MODELS_DIR, "patchcore.ckpt")
        if os.path.exists(ckpt):
            MODEL_INFO["checkpoint"] = "patchcore.ckpt"
            MODEL_INFO["trained_at"] = datetime.fromtimestamp(os.path.getmtime(ckpt)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[TRAINER] Modelo cargado ({MODEL_NAME}/{BACKBONE})")

def get_train_counts() -> Dict[str, int]:
    """Cuenta las imágenes de entrenamiento OK y NG.

    Returns:
        Diccionario con claves ``ok`` y ``ng``.
    """
    ok_count = len(glob.glob(os.path.join(TRAIN_OK_DIR, "*.jpg")))
    ng_count = len(glob.glob(os.path.join(TRAIN_NG_DIR, "*.jpg")))
    return {"ok": ok_count, "ng": ng_count}


def save_to_training(filename: str, category: str = "ok") -> bool:
    """Copia una captura al directorio de entrenamiento correspondiente.

    Args:
        filename: Nombre del archivo en ``IMAGE_DIR``.
        category: ``ok`` o ``ng``.

    Returns:
        ``True`` si se copió con éxito, ``False`` si no existe el origen.
    """
    src = os.path.join(IMAGE_DIR, filename)
    if not os.path.exists(src):
        return False
    dest_dir = TRAIN_OK_DIR if category == "ok" else TRAIN_NG_DIR
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = os.path.join(dest_dir, f"{timestamp}.jpg")
    shutil.copy2(src, dest)
    print(f"[TRAINER] Guardado {category}: {dest}")
    return True


def _prepare_dataset() -> Tuple[int, int]:
    if os.path.exists(ANOMALIB_DATA_DIR):
        shutil.rmtree(ANOMALIB_DATA_DIR)
    good_dir = os.path.join(ANOMALIB_DATA_DIR, "good")
    abnormal_dir = os.path.join(ANOMALIB_DATA_DIR, "abnormal")
    os.makedirs(good_dir, exist_ok=True)
    os.makedirs(abnormal_dir, exist_ok=True)
    
    ok_images = glob.glob(os.path.join(TRAIN_OK_DIR, "*.jpg"))
    for i, src in enumerate(ok_images):
        shutil.copy2(src, os.path.join(good_dir, f"ok_{i:04d}.jpg"))
    
    ng_images = glob.glob(os.path.join(TRAIN_NG_DIR, "*.jpg"))
    for i, src in enumerate(ng_images):
        shutil.copy2(src, os.path.join(abnormal_dir, f"ng_{i:04d}.jpg"))
    
    print(f"[TRAINER] Dataset: {len(ok_images)} good, {len(ng_images)} abnormal")
    return len(ok_images), len(ng_images)

def _get_raw_score_and_map(model: Any, image_path: str) -> Tuple[float, Any]:
    """Pasa una imagen por el modelo y devuelve (score raw, anomaly_map tensor).

    Args:
        model: Instancia del modelo PatchCore cargado.
        image_path: Ruta de la imagen a inspeccionar.

    Returns:
        Tupla ``(raw_score, anomaly_map_tensor)``.
    """
    from PIL import Image
    transform = T.Compose([
        T.Resize((INPUT_SIZE, INPUT_SIZE), antialias=True),
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    model.eval()
    device = next(model.parameters()).device
    with torch.no_grad():
        image = Image.open(image_path).convert("RGB")
        tensor = transform(image).unsqueeze(0).to(device)
        pred = model(tensor)
        if hasattr(pred, 'pred_score'):
            score = float(pred.pred_score.item())
            amap = pred.anomaly_map if hasattr(pred, 'anomaly_map') else None
            return score, amap
    return 0.0, None

def _save_heatmap(
    filename_base: str,
    anomaly_map_tensor: Any,
    original_path: str,
    raw_score: float = 0.0,
) -> Optional[str]:
    """Guarda overlay de anomaly_map sobre la imagen original.

    Genera una única imagen PNG con el heatmap superpuesto
    semitransparente sobre la foto original.

    Args:
        filename_base: Prefijo del nombre de salida (sin extensión).
        anomaly_map_tensor: Tensor con el mapa de anomalías.
        original_path: Ruta de la imagen original.
        raw_score: Puntuación raw para el título.

    Returns:
        Nombre del archivo PNG generado, o ``None`` si no hay tensor.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from PIL import Image
    import numpy as np
    
    if anomaly_map_tensor is None:
        return None
    amap = anomaly_map_tensor.squeeze().cpu().numpy()
    
    # Escala fija: vmax basado en calibracion para que el umbral caiga ~en la mitad
    mean_ng = calibration.get("mean_ng") or 60.0
    max_ok = calibration.get("max_ok") or 40.0
    # vmax alto para que las OK (20-40) queden en AZUL del colormap,
    # y las NG (50-75) queden en AMARILLO/ROJO
    vmax = max(mean_ng * 1.5, raw_score * 1.5, max_ok * 2.5, 80.0)
    
    img = Image.open(original_path).convert("RGB")
    img_np = np.array(img)
    
    # Redimensionar amap al tamaño de la imagen original para overlay
    from scipy.ndimage import zoom
    h_img, w_img = img_np.shape[:2]
    h_map, w_map = amap.shape
    zoom_y = h_img / h_map
    zoom_x = w_img / w_map
    amap_resized = zoom(amap, (zoom_y, zoom_x), order=1)
    
    # Figura con una sola imagen: overlay
    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    
    # Imagen original de fondo
    ax.imshow(img)
    
    # Heatmap superpuesto semitransparente
    overlay = ax.imshow(amap_resized, cmap='jet', vmin=0, vmax=vmax, alpha=0.5)
    
    # Colorbar lateral
    cbar = fig.colorbar(overlay, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Distancia de anomalia")
    
    # Titulo con el score
    ax.set_title(f"Inspeccion (score={raw_score:.1f})")
    ax.axis('off')
    
    plt.tight_layout()
    out_name = f"{filename_base}.png"
    out_path = os.path.join(HEATMAP_DIR, out_name)
    plt.savefig(out_path, bbox_inches='tight', dpi=120)
    plt.close()
    return out_name

def _compute_all_scores(model: Any) -> Tuple[List[float], List[float]]:
    """Computa scores de todas las imágenes OK y NG para calibración.

    Returns:
        Tupla ``(ok_scores, ng_scores)``.
    """
    ok_files = glob.glob(os.path.join(TRAIN_OK_DIR, "*.jpg"))
    ng_files = glob.glob(os.path.join(TRAIN_NG_DIR, "*.jpg"))
    
    ok_scores = []
    ng_scores = []
    
    print(f"[TRAINER] Computando scores de {len(ok_files)} OK y {len(ng_files)} NG...")
    
    for f in ok_files:
        s, _ = _get_raw_score_and_map(model, f)
        ok_scores.append(s)
    
    for f in ng_files:
        s, _ = _get_raw_score_and_map(model, f)
        ng_scores.append(s)
    
    if ok_scores:
        print(f"[TRAINER] OK scores: min={min(ok_scores):.2f}, max={max(ok_scores):.2f}, mean={np.mean(ok_scores):.2f}, std={np.std(ok_scores):.2f}, p95={np.percentile(ok_scores, 95):.2f}, p99={np.percentile(ok_scores, 99):.2f}")
    if ng_scores:
        print(f"[TRAINER] NG scores: min={min(ng_scores):.2f}, max={max(ng_scores):.2f}, mean={np.mean(ng_scores):.2f}, std={np.std(ng_scores):.2f}")
    
    return ok_scores, ng_scores

def train_model() -> Dict[str, Any]:
    """Entrena el modelo PatchCore con las imágenes de entrenamiento actuales.

    Returns:
        Diccionario con resultado del entrenamiento, métricas y estadísticas.
    """
    global model_trained, anomalib_model

    if not ANOMALIB_AVAILABLE:
        return {"ok": False, "error": "Anomalib no disponible"}
    
    ok_count, ng_count = _prepare_dataset()
    if ok_count < 5:
        return {"ok": False, "error": f"Minimo 5 imagenes OK. Actual: {ok_count}"}
    
    try:
        print(f"[TRAINER] === ENTRENAMIENTO ({MODEL_NAME}/{BACKBONE}, {INPUT_SIZE}x{INPUT_SIZE}) ===")
        
        from torchvision.transforms.v2 import Resize, Compose, ToTensor, Normalize
        augmentations = Compose([
            Resize((INPUT_SIZE, INPUT_SIZE), antialias=True),
            ToTensor(),
            Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        
        datamodule = Folder(
            name="placas_pcb",
            root=ANOMALIB_DATA_DIR,
            normal_dir="good",
            abnormal_dir="abnormal" if ng_count > 0 else None,
            train_batch_size=1,
            eval_batch_size=1,
            num_workers=0,
            augmentations=augmentations,
        )
        
        model = Patchcore(
            backbone=BACKBONE,
            layers=LAYERS,
            coreset_sampling_ratio=CORESET_RATIO,
            pre_processor=False,
            post_processor=False,
            evaluator=False,
            visualizer=False,
        )
        
        engine = Engine(
            max_epochs=1,
            accelerator="auto",
            devices=1,
        )
        
        print("[TRAINER] Paso 1/3: Entrenando...")
        engine.fit(model=model, datamodule=datamodule)
        
        print("[TRAINER] Paso 2/3: Validando...")
        engine.validate(model=model, datamodule=datamodule)
        
        # === GUARDAR CHECKPOINT ===
        ckpt_path = os.path.join(MODELS_DIR, "patchcore.ckpt")
        engine.trainer.save_checkpoint(ckpt_path)
        
        # === CALIBRACION con scores raw ===
        print("[TRAINER] Calibrando scores raw...")
        calib_model = _load_model_for_inference()
        if calib_model is None:
            return {"ok": False, "error": "No se pudo cargar modelo para calibracion"}
        
        ok_scores, ng_scores = _compute_all_scores(calib_model)
        _save_calibration(ok_scores, ng_scores)
        
        # Calcular AUROC manualmente con sklearn (mas fiable que el reporte de Anomalib)
        from sklearn.metrics import roc_auc_score
        if len(ng_scores) > 0 and len(ok_scores) > 0:
            y_true = [0]*len(ok_scores) + [1]*len(ng_scores)
            y_score = list(ok_scores) + list(ng_scores)
            auroc = float(roc_auc_score(y_true, y_score))
            print(f"[TRAINER] AUROC (sklearn) = {auroc:.4f} ({auroc*100:.1f}%)")
        else:
            auroc = None
        
        anomalib_model = calib_model
        model_trained = True
        MODEL_INFO["checkpoint"] = "patchcore.ckpt"
        MODEL_INFO["trained_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return {
            "ok": True,
            "images_used": ok_count,
            "ng_images": ng_count,
            "auroc": auroc,
            "ok_scores_info": {
                "count": len(ok_scores),
                "min": min(ok_scores) if ok_scores else 0,
                "max": max(ok_scores) if ok_scores else 0,
                "mean": float(np.mean(ok_scores)) if ok_scores else 0,
                "std": float(np.std(ok_scores)) if ok_scores else 0,
                "p95": float(np.percentile(ok_scores, 95)) if ok_scores else 0,
                "p99": float(np.percentile(ok_scores, 99)) if ok_scores else 0,
            },
            "ng_scores_info": {
                "count": len(ng_scores),
                "min": min(ng_scores) if ng_scores else 0,
                "max": max(ng_scores) if ng_scores else 0,
                "mean": float(np.mean(ng_scores)) if ng_scores else 0,
                "std": float(np.std(ng_scores)) if ng_scores else 0,
            },
            "method": f"anomalib-{MODEL_NAME}-{BACKBONE}-p95calibrated",
            "backbone": BACKBONE,
            "input_size": INPUT_SIZE,
        }
        
    except Exception as e:
        print(f"[TRAINER] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

def predict(image_path: str) -> Dict[str, Any]:
    """Ejecuta inferencia sobre una imagen y determina si es OK o NG.

    Args:
        image_path: Ruta completa de la imagen a inspeccionar.

    Returns:
        Diccionario con resultado, scores y nombre del heatmap generado.
    """
    global model_trained, anomalib_model, calibration

    if not ANOMALIB_AVAILABLE:
        return {"ok": False, "error": "Anomalib no disponible"}
    
    try:
        if anomalib_model is None:
            anomalib_model = _load_model_for_inference()
            if anomalib_model is None:
                return {"ok": False, "error": "Modelo no entrenado"}
            model_trained = True
            _load_calibration()
        
        raw_score, amap = _get_raw_score_and_map(anomalib_model, image_path)
        
        # Generar heatmap para debug
        heatmap_filename = None
        if amap is not None:
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            heatmap_filename = _save_heatmap(base_name, amap, image_path, raw_score=raw_score)
        
        # === UMBRAL: max_ok + margen (mas permisivo que p95) ===
        p95_ok = calibration.get("p95_ok")
        p99_ok = calibration.get("p99_ok")
        max_ok = calibration.get("max_ok")
        mean_ok = calibration.get("mean_ok")
        std_ok = calibration.get("std_ok")
        
        if p95_ok is None or p95_ok <= 0 or mean_ok is None:
            return {"ok": False, "error": "Modelo sin calibracion. Reentrena."}
        
        # Centro de la sigmoid: max_ok + 0.5*std (cubre el peor OK con margen)
        # Esto es MAS PERMISIVO que p95. Un OK outlier alto seguira siendo OK.
        center = (max_ok if max_ok else p99_ok) + (std_ok * 0.5)
        denom = (std_ok * 2.0) if std_ok > 0 else 2.0
        z = (raw_score - center) / denom
        score_norm = 1.0 / (1.0 + math.exp(-z * 2.0))
        
        threshold = 0.5
        is_anomaly = score_norm > threshold
        result = "NG" if is_anomaly else "OK"
        
        print(f"[TRAINER] raw={raw_score:.2f}, p95={p95_ok:.2f}, z={z:.2f}, norm={score_norm:.4f}, result={result}")
        
        return {
            "ok": True,
            "is_anomaly": bool(is_anomaly),
            "score": float(score_norm),
            "raw_score": float(raw_score),
            "z_score": float(z),
            "threshold": threshold,
            "p95_ok": float(p95_ok),
            "p99_ok": float(p99_ok) if p99_ok else None,
            "result": result,
            "method": f"anomalib-{MODEL_NAME}-{BACKBONE}-p95calibrated",
            "backbone": BACKBONE,
            "heatmap": heatmap_filename,
        }
        
    except Exception as e:
        print(f"[TRAINER] Error predict: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}

# Cargar al iniciar
_try_load_existing_model()
if calibration["mean_ok"] is None:
    _load_calibration()
