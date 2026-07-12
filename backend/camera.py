import cv2
import os
import threading
from datetime import datetime
from typing import Optional

IMAGE_DIR = os.path.join(os.path.dirname(__file__), "images")
TRAIN_OK_DIR = os.path.join(os.path.dirname(__file__), "training", "ok")
TRAIN_NG_DIR = os.path.join(os.path.dirname(__file__), "training", "ng")


def ensure_dir() -> None:
    """Crea los directorios de imágenes si no existen."""
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(TRAIN_OK_DIR, exist_ok=True)
    os.makedirs(TRAIN_NG_DIR, exist_ok=True)


class CameraManager:
    """Gestiona la webcam con bloqueo de hilos para capturas seguras."""

    def __init__(self) -> None:
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._init_camera()

    def _init_camera(self) -> None:
        """Intenta abrir la webcam en los índices 0 y 1 con resolución 4MP."""
        for idx in [0, 1]:
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 2560)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1440)
                # Precalentar: descartar 5 frames para estabilizar
                for _ in range(5):
                    cap.read()
                self._cap = cap
                print(f"[CAMERA] Webcam inicializada en indice {idx}")
                return
        print("[CAMERA] ERROR: No se encontro webcam")

    def capture(self) -> Optional[str]:
        """Captura una imagen de alta resolución y genera thumbnail.

        Returns:
            Nombre del archivo JPEG creado, o ``None`` si falla.
        """
        ensure_dir()
        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                self._init_camera()
            if self._cap is None:
                return None

            # Refrescar 2 frames (la camara ya esta caliente)
            self._cap.read()
            self._cap.read()

            ret, frame = self._cap.read()
            if not ret:
                print("[CAMERA] ERROR: No se pudo leer frame")
                return None

        filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
        filepath = os.path.join(IMAGE_DIR, filename)

        # Guardar imagen original 4MP (calidad maxima 100 para conservar todo el detalle)
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
            if self._cap is None or not self._cap.isOpened():
                self._init_camera()
            if self._cap is None:
                return None
            ret, frame = self._cap.read()
            if not ret:
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
            if self._cap is None or not self._cap.isOpened():
                self._init_camera()
            if self._cap is None:
                return None
            ret, frame = self._cap.read()
            if not ret:
                return None

        dest_dir = TRAIN_OK_DIR if category == "ok" else TRAIN_NG_DIR
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}.jpg"
        filepath = os.path.join(dest_dir, filename)

        # Guardar original 4MP
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
