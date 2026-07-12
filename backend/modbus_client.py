import time
import threading
from typing import Callable, List, Optional, Tuple

from pymodbus.client import ModbusTcpClient
from config import PLC_HOST, PLC_PORT


class ModbusPlcClient:
    """Cliente Modbus TCP para leer estado del sensor y escribir órdenes al PLC.

    Corre un hilo daemon que hace polling cada ~50 ms. Cuando detecta un flanco
    ascendente en la bobina 0 programa una captura con retardo para evitar
    vibración mecánica.
    """

    def __init__(
        self,
        host: str = PLC_HOST,
        port: int = PLC_PORT,
        on_trigger: Optional[Callable[[], None]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.on_trigger = on_trigger
        self.connected = False
        self.last_state = False
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_trigger_time = 0.0
        self.cooldown = 1.5
        self._pending_writes: List[Tuple[int, bool]] = []
        self._lock = threading.Lock()
        # Sistema de captura programada (no bloqueante)
        self._capture_scheduled_at = 0.0

    def start(self) -> None:
        """Arranca el hilo de polling Modbus."""
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Solicita la parada del hilo de polling."""
        self.running = False
        if self.thread:
            # No bloquear indefinidamente, el hilo es daemon
            self.thread.join(timeout=1.0)
            if self.thread.is_alive():
                print("[MODBUS] Hilo no respondio, forzando cierre...")

    def queue_write(self, address: int, value: bool) -> None:
        """Encola una escritura de bobina que se procesará en el próximo ciclo del loop."""
        with self._lock:
            self._pending_writes.append((address, value))

    def trigger_reset(self) -> None:
        """Encola la escritura de la bobina de liberación (dirección 1 = True)."""
        self.queue_write(1, True)

    def _loop(self) -> None:
        client = None
        while self.running:
            try:
                # Conectar si es necesario
                if client is None or not client.connected:
                    if client:
                        try:
                            client.close()
                        except Exception:
                            pass
                    client = ModbusTcpClient(self.host, port=self.port, timeout=1)
                    client.connect()

                self.connected = client.connected

                if client.connected:
                    # --- Leer estado del PLC ---
                    rr = client.read_coils(address=0, count=2)
                    if rr and not rr.isError():
                        state = bool(rr.bits[0])

                        if state != self.last_state:
                            print(f"[MODBUS] Bobina 0 cambio: {self.last_state} -> {state}")

                        if state and not self.last_state:
                            now = time.time()
                            if now - self.last_trigger_time >= self.cooldown:
                                print("[MODBUS] FLANCO DETECTADO -> Programando captura en 300ms")
                                self.last_trigger_time = now
                                self._capture_scheduled_at = now + 0.3
                            else:
                                print(f"[MODBUS] Flanco ignorado (cooldown: {now - self.last_trigger_time:.1f}s)")
                        self.last_state = state
                    else:
                        print(f"[MODBUS] Error leyendo bobinas: {rr}")

                    # --- Ejecutar captura programada si ya llego la hora ---
                    if self._capture_scheduled_at > 0 and time.time() >= self._capture_scheduled_at:
                        self._capture_scheduled_at = 0
                        print("[MODBUS] Ejecutando captura programada")
                        if self.on_trigger:
                            try:
                                self.on_trigger()
                            except Exception as e:
                                print(f"[MODBUS] ERROR en on_trigger: {e}")
                                import traceback
                                traceback.print_exc()

                    # --- Procesar escrituras pendientes ---
                    with self._lock:
                        writes = self._pending_writes[:]
                        self._pending_writes.clear()
                    for address, value in writes:
                        try:
                            client.write_coil(address=address, value=value)
                            print(f"[MODBUS] Escrito bobina {address}={value}")
                        except Exception as e:
                            print(f"[MODBUS] Error escribiendo bobina {address}: {e}")
                else:
                    # Esperar sin bloquear, verificando self.running
                    self._safe_sleep(1)
            except Exception as e:
                err_str = str(e)
                if "10054" in err_str or "forzado" in err_str.lower():
                    print("[MODBUS] PLC cerro conexion, reconectando...")
                else:
                    print("[MODBUS] Error:", e)
                self.connected = False
                if client:
                    try:
                        client.close()
                    except Exception:
                        pass
                    client = None
                self._safe_sleep(0.5)
            time.sleep(0.05)

    def _safe_sleep(self, seconds: float) -> None:
        """Espera en pequeños incrementos, verificando ``self.running``.

        Args:
            seconds: Tiempo total a dormir (aproximado).
        """
        elapsed = 0.0
        while self.running and elapsed < seconds:
            time.sleep(0.1)
            elapsed += 0.1
        # Intento de limpieza del cliente global si quedara abierto
        try:
            # Nota: ``client`` es una variable local de ``_loop``; en el flujo
            # actual esta referencia puede no estar disponible aquí.
            pass  # pylint: disable=unnecessary-pass
        except Exception:
            pass
