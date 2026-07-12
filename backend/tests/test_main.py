"""Tests para main.py usando TestClient con dependencias mockeadas."""

import os
import sys
import tempfile
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """Crea un TestClient de FastAPI con todas las dependencias hardware mockeadas."""
    # Asegurar que los módulos se recargan con los mocks
    for mod in ["main", "modbus_client", "camera", "trainer", "config"]:
        if mod in sys.modules:
            del sys.modules[mod]

    # Crear directorios temporales reales para que StaticFiles no falle
    tmp_images = tempfile.mkdtemp(prefix="test_images_")
    tmp_heatmaps = tempfile.mkdtemp(prefix="test_heatmaps_")

    # Mock modbus_client
    mock_plc_instance = MagicMock()
    mock_plc_instance.connected = True
    mock_plc_instance.last_state = False
    mock_modbus = MagicMock()
    mock_modbus.ModbusPlcClient.return_value = mock_plc_instance
    monkeypatch.setitem(sys.modules, "modbus_client", mock_modbus)

    # Mock camera
    mock_camera = MagicMock()
    mock_camera.capture_image.return_value = "20230101_120000_000000.jpg"
    mock_camera.get_camera_preview.return_value = b"preview_bytes"
    mock_camera.capture_training_image.return_value = "train_20230101.jpg"
    mock_camera.IMAGE_DIR = tmp_images
    monkeypatch.setitem(sys.modules, "camera", mock_camera)

    # Mock trainer
    mock_trainer = MagicMock()
    mock_trainer.ANOMALIB_AVAILABLE = True
    mock_trainer.MODEL_INFO = {"name": "Patchcore", "backbone": "wide_resnet50_2"}
    mock_trainer.HEATMAP_DIR = tmp_heatmaps
    mock_trainer.predict.return_value = {
        "ok": True,
        "result": "OK",
        "score": 0.1,
        "raw_score": 25.0,
        "z_score": -1.0,
        "heatmap": "heatmap_20230101.png",
    }
    mock_trainer.save_to_training.return_value = True
    mock_trainer.get_train_counts.return_value = {"ok": 5, "ng": 2}
    mock_trainer.train_model.return_value = {"ok": True, "auroc": 0.99}
    monkeypatch.setitem(sys.modules, "trainer", mock_trainer)

    # Mock config
    mock_config = MagicMock()
    mock_config.PLC_HOST = "169.254.241.100"
    mock_config.PLC_PORT = 502
    monkeypatch.setitem(sys.modules, "config", mock_config)

    import importlib
    import main
    importlib.reload(main)
    # Inyectar el mock de PLC en el módulo main para que los endpoints lo usen
    main.plc = mock_plc_instance
    return TestClient(main.app), mock_plc_instance, mock_camera, mock_trainer


def test_get_status(client):
    """GET /api/status debe retornar el estado global."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["plc_connected"] is True
    assert data["capture_count"] >= 0
    assert data["anomalib_available"] is True
    assert data["production_state"] == "waiting"


def test_manual_trigger(client):
    """POST /api/trigger debe capturar imagen manualmente."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.post("/api/trigger")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["filename"] is not None
    cam_mock.capture_image.assert_called_once()


def test_ok_decision(client):
    """POST /api/ok debe marcar decisión OK y liberar cinta."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.post("/api/ok")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["decision"] == "OK"
    plc_mock.queue_write.assert_called()


def test_ng_decision(client):
    """POST /api/ng debe marcar decisión NG."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.post("/api/ng")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["decision"] == "NG"


def test_release_conveyor(client):
    """POST /api/release debe reanudar la cinta desde NG."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    # Forzar estado NG
    import main
    main.production_state = "ng"
    response = test_client.post("/api/release")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["action"] == "release"
    assert main.production_state in ("cooldown", "waiting")


def test_auto_predict_toggle(client):
    """POST /api/auto-predict/toggle debe alternar el flag."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    import main
    initial = main.auto_predict
    response = test_client.post("/api/auto-predict/toggle")
    assert response.status_code == 200
    data = response.json()
    assert data["auto_predict"] is not initial


def test_train_status(client):
    """GET /api/train/status debe retornar conteos."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.get("/api/train/status")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["counts"]["ok"] == 5
    assert data["counts"]["ng"] == 2


def test_save_training_ok(client):
    """POST /api/train/save-ok debe guardar captura actual como OK."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    import main
    main.latest_capture = "20230101_120000_000000.jpg"
    response = test_client.post("/api/train/save-ok")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    trainer_mock.save_to_training.assert_called_with("20230101_120000_000000.jpg", "ok")


def test_save_training_ng(client):
    """POST /api/train/save-ng debe guardar captura actual como NG."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    import main
    main.latest_capture = "20230101_120000_000000.jpg"
    response = test_client.post("/api/train/save-ng")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    trainer_mock.save_to_training.assert_called_with("20230101_120000_000000.jpg", "ng")


def test_start_training(client):
    """POST /api/train/start debe delegar en trainer.train_model."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.post("/api/train/start")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["auroc"] == 0.99


def test_predict_live(client):
    """POST /api/predict-live debe capturar y predecir."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.post("/api/predict-live")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["result"] == "OK"
    assert "filename" in data
    cam_mock.capture_image.assert_called()
    trainer_mock.predict.assert_called()


def test_stream_preview(client):
    """GET /api/stream/preview debe devolver imagen JPEG o error controlado."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.get("/api/stream/preview")
    # Como el mock devuelve bytes, debería ser 200
    if response.status_code == 200:
        assert response.headers["content-type"] == "image/jpeg"
    else:
        assert response.status_code == 503


def test_stream_capture_ok(client):
    """POST /api/stream/capture-ok debe capturar imagen de entrenamiento OK."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.post("/api/stream/capture-ok")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    cam_mock.capture_training_image.assert_called_with("ok")


def test_stream_capture_ng(client):
    """POST /api/stream/capture-ng debe capturar imagen de entrenamiento NG."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.post("/api/stream/capture-ng")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    cam_mock.capture_training_image.assert_called_with("ng")


def test_get_capture_404(client):
    """GET /api/captures/{filename} debe retornar 404 si no existe."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.get("/api/captures/nonexistent.jpg")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not found"


def test_get_heatmap_404(client):
    """GET /api/heatmaps/{filename} debe retornar 404 si no existe."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    response = test_client.get("/api/heatmaps/nonexistent.png")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not found"


def test_root_serves_frontend(client):
    """GET / debe intentar servir index.html del frontend."""
    test_client, plc_mock, cam_mock, trainer_mock = client
    # Como el frontend no existe en el entorno de test, esperamos 404
    response = test_client.get("/")
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert "text/html" in response.headers.get("content-type", "")
