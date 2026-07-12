"""Tests para modbus_client.py."""

import sys
import time
from unittest.mock import MagicMock, patch

import pytest

import modbus_client as mc


@pytest.fixture(autouse=True)
def _ensure_real_modbus_module(monkeypatch):
    """Asegura que sys.modules contenga el módulo real antes de cada test."""
    if "modbus_client" in sys.modules:
        del sys.modules["modbus_client"]
    import modbus_client
    monkeypatch.setitem(sys.modules, "modbus_client", modbus_client)


def test_modbus_plc_client_init():
    """Verifica que el cliente se inicializa con los parámetros esperados."""
    callback = MagicMock()
    client = mc.ModbusPlcClient(host="169.254.241.100", port=502, on_trigger=callback)
    assert client.host == "169.254.241.100"
    assert client.port == 502
    assert client.on_trigger is callback
    assert client.connected is False
    assert client.running is False


def test_queue_write():
    """queue_write debe añadir escrituras a la lista interna."""
    client = mc.ModbusPlcClient()
    client.queue_write(1, True)
    client.queue_write(2, False)
    assert client._pending_writes == [(1, True), (2, False)]


def test_start_stop():
    """start arranca el hilo; stop lo detiene sin bloquear indefinidamente."""
    client = mc.ModbusPlcClient()
    client.start()
    assert client.running is True
    assert client.thread is not None
    client.stop()
    assert client.running is False


# Nota: los tests del loop interno (_loop) se omiten porque implican un hilo
# daemon con bucle infinito que es difícil de mockear sin alterar la lógica.
# La cobertura funcional se valida con test_start_stop y tests de integración.
