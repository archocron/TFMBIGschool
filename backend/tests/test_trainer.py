"""Tests para trainer.py (sin dependencias de GPU/anomalib)."""

import os
import numpy as np
from unittest.mock import MagicMock, patch

import trainer as tr


def test_get_train_counts():
    """get_train_counts debe contar imágenes .jpg en los directorios de entrenamiento."""
    with patch("trainer.glob.glob") as mock_glob:
        mock_glob.side_effect = [
            ["a.jpg", "b.jpg", "c.jpg"],  # OK
            ["x.jpg", "y.jpg"],            # NG
        ]
        counts = tr.get_train_counts()
        assert counts == {"ok": 3, "ng": 2}


def test_save_to_training_missing_source():
    """save_to_training debe retornar False si la imagen origen no existe."""
    with patch("trainer.os.path.exists", return_value=False):
        result = tr.save_to_training("nonexistent.jpg", category="ok")
        assert result is False


def test_save_to_training_success():
    """save_to_training debe copiar la imagen al destino correcto."""
    with patch("trainer.os.path.exists", return_value=True):
        with patch("trainer.shutil.copy2") as mock_copy:
            result = tr.save_to_training("capture.jpg", category="ok")
            assert result is True
            mock_copy.assert_called_once()
            # Verificar que el destino contiene training/ok
            dest = mock_copy.call_args[0][1]
            assert "training" in dest and "ok" in dest


def test_save_calibration():
    """_save_calibration debe guardar estadísticas y escribir archivo npz."""
    ok_scores = [10.0, 20.0, 30.0]
    ng_scores = [50.0, 60.0]
    with patch("trainer.np.savez") as mock_savez:
        tr._save_calibration(ok_scores, ng_scores)
        mock_savez.assert_called_once()
        assert tr.calibration["mean_ok"] == 20.0
        assert tr.calibration["count_ok"] == 3
        assert tr.calibration["mean_ng"] == 55.0


def test_load_calibration_exists():
    """_load_calibration debe cargar valores desde npz si existe."""
    fake_data = {
        "mean_ok": 25.0,
        "std_ok": 5.0,
        "max_ok": 35.0,
        "p95_ok": 33.0,
        "p99_ok": 34.0,
        "mean_ng": 60.0,
        "min_ng": 50.0,
        "max_ng": 70.0,
        "count_ok": 10,
        "count_ng": 5,
    }
    mock_npz = MagicMock()
    for k, v in fake_data.items():
        mock_npz.get.return_value = v
    # Ajustar mock para que d.get(k) devuelva el valor correcto
    mock_npz.get = lambda k, default=0: fake_data.get(k, default)

    with patch("trainer.os.path.exists", return_value=True):
        with patch("trainer.np.load", return_value=mock_npz):
            tr._load_calibration()
            assert tr.calibration["mean_ok"] == 25.0
            assert tr.calibration["count_ng"] == 5


def test_predict_anomalib_not_available():
    """predict debe retornar error si anomalib no está disponible."""
    with patch.object(tr, "ANOMALIB_AVAILABLE", False):
        result = tr.predict("dummy.jpg")
        assert result["ok"] is False
        assert "Anomalib no disponible" in result["error"]


def test_predict_no_model():
    """predict debe retornar error si no hay modelo cargado."""
    with patch.object(tr, "ANOMALIB_AVAILABLE", True):
        with patch.object(tr, "anomalib_model", None):
            with patch.object(tr, "_load_model_for_inference", return_value=None):
                with patch.object(tr, "model_trained", False):
                    result = tr.predict("dummy.jpg")
                    assert result["ok"] is False
                    assert "Modelo no entrenado" in result["error"]


def test_prepare_dataset():
    """_prepare_dataset debe crear estructura de carpetas y copiar imágenes."""
    with patch("trainer.os.path.exists", return_value=False):
        with patch("trainer.shutil.rmtree") as mock_rmtree:
            with patch("trainer.os.makedirs") as mock_makedirs:
                with patch("trainer.glob.glob") as mock_glob:
                    mock_glob.side_effect = [
                        ["ok1.jpg", "ok2.jpg"],
                        ["ng1.jpg"],
                    ]
                    with patch("trainer.shutil.copy2") as mock_copy:
                        ok_count, ng_count = tr._prepare_dataset()
                        assert ok_count == 2
                        assert ng_count == 1
                        # Como os.path.exists devuelve False, rmtree no se llama
                        assert not mock_rmtree.called
                        assert mock_makedirs.call_count >= 2
                        assert mock_copy.call_count == 3
