"""Tests para find_plc.py."""

from unittest.mock import patch, MagicMock
import find_plc


def test_check_port_success():
    """Cuando el socket se conecta, check_port devuelve la IP."""
    with patch("find_plc.socket.create_connection") as mock_conn:
        result = find_plc.check_port("192.168.1.100", port=502, timeout=1)
        mock_conn.assert_called_once_with(("192.168.1.100", 502), timeout=1)
        assert result == "192.168.1.100"


def test_check_port_failure():
    """Cuando el socket falla, check_port devuelve None."""
    with patch("find_plc.socket.create_connection", side_effect=OSError("timeout")):
        result = find_plc.check_port("192.168.1.100", port=502, timeout=1)
        assert result is None


def test_scan_network_finds_hosts():
    """scan_network debe retornar las IPs que responden."""
    with patch("find_plc.check_port") as mock_check:
        mock_check.side_effect = lambda ip, port, timeout=None: ip if ip.endswith(".50") else None
        found = find_plc.scan_network(base="192.168.1", start=1, end=100, port=502, max_workers=10)
        assert "192.168.1.50" in found


def test_scan_full_169254():
    """scan_full_169254 debe retornar resultados sin bloquearse."""
    with patch("find_plc.check_port") as mock_check:
        mock_check.return_value = None
        found = find_plc.scan_full_169254(start_octet2=0, end_octet2=0, start_octet3=0, end_octet3=0)
        assert isinstance(found, list)
