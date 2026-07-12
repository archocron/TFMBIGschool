"""Tests para camera.py."""

import os
from unittest.mock import MagicMock, patch

import camera as cam


def test_ensure_dir_creates_paths():
    """ensure_dir debe crear los directorios necesarios."""
    with patch("camera.os.makedirs") as mock_makedirs:
        cam.ensure_dir()
        assert mock_makedirs.call_count >= 3


def test_capture_image_success():
    """capture_image debe retornar un nombre de archivo cuando la cámara funciona."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    # Simular que read() devuelve frame válido
    fake_frame = MagicMock()
    mock_cap.read.side_effect = [
        (True, fake_frame),  # refrescar 1
        (True, fake_frame),  # refrescar 2
        (True, fake_frame),  # captura real
    ]

    with patch("camera.cv2.VideoCapture", return_value=mock_cap):
        with patch("camera.os.path.getsize", return_value=1024):
            with patch("camera.cv2.imwrite", return_value=True):
                with patch("camera.cv2.resize", return_value=fake_frame):
                    filename = cam.camera.capture()
                    assert filename is not None
                    assert filename.endswith(".jpg")


def test_get_preview_success():
    """get_preview debe devolver bytes JPEG cuando la cámara funciona."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    fake_frame = MagicMock()
    mock_cap.read.return_value = (True, fake_frame)

    with patch("camera.cv2.VideoCapture", return_value=mock_cap):
        with patch("camera.cv2.resize", return_value=fake_frame):
            with patch("camera.cv2.imencode") as mock_imencode:
                mock_imencode.return_value = (True, MagicMock(tobytes=lambda: b"fake_jpeg"))
                result = cam.camera.get_preview()
                assert result == b"fake_jpeg"


def test_capture_training_success():
    """capture_training debe guardar en el directorio correcto."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    fake_frame = MagicMock()
    mock_cap.read.return_value = (True, fake_frame)

    with patch("camera.cv2.VideoCapture", return_value=mock_cap):
        with patch("camera.cv2.imwrite", return_value=True):
            with patch("camera.os.path.getsize", return_value=2048):
                filename = cam.camera.capture_training(category="ok")
                assert filename is not None
                assert filename.endswith(".jpg")


def test_camera_manager_release():
    """release debe liberar la captura."""
    mock_cap = MagicMock()
    manager = cam.CameraManager()
    manager._cap = mock_cap
    manager.release()
    mock_cap.release.assert_called_once()
    assert manager._cap is None
