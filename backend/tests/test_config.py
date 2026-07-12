"""Tests para el módulo de configuración."""

import config


def test_config_values():
    """Verifica que las constantes de configuración están definidas y son del tipo esperado."""
    assert isinstance(config.PLC_HOST, str)
    assert isinstance(config.PLC_PORT, int)
    assert config.PLC_PORT == 502
    assert len(config.PLC_HOST.split(".")) == 4
