import cv2
import os
import threading
from datetime import datetime
from typing import Optional, List

import config

IMAGE_DIR = os.path.join(os.path.dirname(__file__), "images")
TRAIN_OK_DIR = os.path.join(os.path.dirname(__file__), "training", "ok")
TRAIN_NG_DIR = os.path.join(os.path.dirname(__file__), "training", "ng")


def ensure_dir() -> None:
    """Crea los directorios de imágenes si no existen."""
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(TRAIN_OK_DIR, exist_ok=True)
    os.makedirs(TRAIN_NG_DIR, exist_ok=True)


def _is_black_frame(frame) -> bool:
    """Devuelve True si el frame está vacío o es mayormente negro.

    Un frame se considera inválido si:
    - Es None o está vacío.
    - El brillo medio es menor a 5 (escala 0-255).
    """
    if frame is None or frame.size == 0:
        return True
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_brightness = gray.mean()
    return mean_brightness < 5.0


class CameraManager:
    """Gestiona la webcam con bloqueo de hilos para capturas seguras."""

    def __init__(self) -> None:
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        # Inicializacion perezosa: no abrimos la camara aqui para evitar
        # bloquear el arranque del backend si MSMF se cuelga.


    def _try_index(self, idx: int) -> Optional[cv2.VideoCapture]:
        """Prueba un índice de cámara concreto y valida que devuelva frames reales.

        Returns:
            VideoCapture abierto y validado, o None si falla.
        """
        print(f"[CAMERA] Probando indice {idx}...")
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            print(f"[CAMERA]   Indice {idx}: no se pudo abrir")
            return None

        # Descartar 5 frames iniciales para estabilizar
        for _ in range(5):
            cap.read()

        ret, frame = cap.read()
        if not ret:
            print(f"[CAMERA]   Indice {idx}: abierto pero sin frames")
            cap.release()
            return None

        if _is_black_frame(frame):
            print(f"[CAMERA]   Indice {idx}: frame mayormente NEGRO (dispositivo fantasma?)")
            cap.release()
            return None

        print(f"[CAMERA]   Indice {idx}: OK - frame valido (brillo={frame.mean():.1f})")
        return cap

    def _init_camera(self) -> None:
        """Detecta la webcam automáticamente o usa índice forzado desde config.

        Prueba índices 0..5. Si ``config.CAMERA_INDEX`` es un entero, fuerza
        ese índice directamente.
        """
        # Si hay indice forzado, probar solo ese
        forced: Optional[int] = getattr(config, "CAMERA_INDEX", None)
        if forced is not None:
            print(f"[CAMERA] Indice forzado por config: {forced}")
            cap = self._try_index(forced)
            if cap:
                self._cap = cap
                print(f"[CAMERA] Webcam forzada en indice {forced}")
                return
            print(f"[CAMERA] ERROR: Indice forzado {forced} no funciona")
            return

        # Autodeteccion: probar 0..5
        candidates: List[int] = list(range(6))
        for idx in candidates:
            cap = self._try_index(idx)
            if cap:
                self._cap = cap
                print(f"[CAMERA] Webcam autodetectada en indice {idx}")
                return

        print("[CAMERA] ERROR: No se encontro webcam valida en indices 0..5")

    def _safe_read(self) -> tuple:
        """Lee un frame de la camara con proteccion contra crashes de OpenCV.

        Si ``cap.read()`` lanza ``cv2.error`` (p.ej. MSMF corrupto), libera
        la camara, reinicializa y reintenta una vez.

        Returns:
            (ret, frame) igual que ``cap.read()``.
        """
        try:
            if self._cap is None or not self._cap.isOpened():
                self._init_camera()
            if self._cap is None:
                return (False, None)
            return self._cap.read()
        except cv2.error as e:
            print(f"[CAMERA] cv2.error en read(): {e}")
            if self._cap:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
            self._init_camera()
            if self._cap is None:
                return (False, None)
            try:
                return self._cap.read()
            except cv2.error:
                return (False, None)

    def capture(self) -> Optional[str]:
        """Captura una imagen de alta resolución y genera thumbnail.

        Returns:
            Nombre del archivo JPEG creado, o ``None`` si falla.
        """
        ensure_dir()
        with self._lock:
            # Refrescar 2 frames (la camara ya esta caliente)
            self._safe_read()
            self._safe_read()

            ret, frame = self._safe_read()
            if not ret or frame is None:
                print("[CAMERA] ERROR: No se pudo leer frame")
                return None

        filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
        filepath = os.path.join(IMAGE_DIR, filename)

        # Guardar imagen original con calidad maxima 100
        cv2.imwrite(filepath, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
        file_size = os.path.getsize(filepath)
        print(f"[CAMERA] Original guardada: {filename} ({file_size // 1024} KB)")

        # Crear thumbnail para frontend (rapido pero con buena calidad)
        thumb = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
        thumb_name = filename.replace(".jpg", "_thumb.jpg")
        thumb_path = os.path.join(IMAGE_DIR, thumb_name)
        cv2.imwrite(thumb_path, thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        thumb_size = os.path.getsize(thumb_path)
        print(f"[CAMERA] Thumbnail guardado: {thumb_name} ({thumb_size // 1024} KB)")

        return filename

    def get_preview(self) -> Optional[bytes]:
        """Captura un frame para preview en tiempo real. Devuelve bytes JPEG."""
        with self._lock:
            ret, frame = self._safe_read()
            if not ret or frame is None:
                return None
        # Redimensionar a 640x360 para preview rapido por red
        preview = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            return encoded.tobytes()
        return None

    def capture_training(self, category: str = "ok") -> Optional[str]:
        """Captura desde la camara y guarda directamente en training/ok/ o training/ng/.

        Args:
            category: ``ok`` o ``ng``.

        Returns:
            Nombre del archivo guardado, o ``None`` si falla.
        """
        ensure_dir()
        with self._lock:
            ret, frame = self._safe_read()
            if not ret or frame is None:
                return None

        dest_dir = TRAIN_OK_DIR if category == "ok" else TRAIN_NG_DIR
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}.jpg"
        filepath = os.path.join(dest_dir, filename)

        cv2.imwrite(filepath, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
        print(f"[CAMERA] Training {category}: {filename}")
        return filename

    def release(self) -> None:
        """Libera el recurso de la webcam."""
        if self._cap:
            self._cap.release()
            self._cap = None


# Instancia global
camera = CameraManager()


def capture_image() -> Optional[str]:
    """Wrapper global para capturar imagen."""
    return camera.capture()


def get_camera_preview() -> Optional[bytes]:
    """Wrapper global para obtener preview."""
    return camera.get_preview()


def capture_training_image(category: str = "ok") -> Optional[str]:
    """Wrapper global para capturar imagen de entrenamiento."""
    return camera.capture_training(category)
