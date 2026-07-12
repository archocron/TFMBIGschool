import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional


def check_port(ip: str, port: int = 502, timeout: float = 1) -> Optional[str]:
    """Intenta conectarse a ``ip:port`` vía TCP y devuelve la IP si tiene éxito.

    Args:
        ip: Dirección IP a comprobar.
        port: Puerto TCP (por defecto 502 para Modbus).
        timeout: Tiempo máximo de espera en segundos.

    Returns:
        La misma IP si la conexión fue exitosa; ``None`` en caso contrario.
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return ip
    except Exception:
        return None


def scan_network(
    base: str = "169.254.241",
    start: int = 1,
    end: int = 254,
    port: int = 502,
    max_workers: int = 50,
) -> List[str]:
    """Escanea un rango de IPs en busca de dispositivos Modbus TCP.

    Args:
        base: Prefijo de red (e.g. ``169.254.241``).
        start: Último octeto inicial.
        end: Último octeto final.
        port: Puerto a escanear.
        max_workers: Hilos concurrentes del pool.

    Returns:
        Lista de IPs que respondieron en el puerto indicado.
    """
    print(f"Escaneando {base}.{start} - {base}.{end} en puerto {port}...")
    found: List[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(check_port, f"{base}.{i}", port): i for i in range(start, end + 1)}
        for future in as_completed(futures):
            result = future.result()
            if result:
                print(f"  [ENCONTRADO] {result}:{port} responde!")
                found.append(result)
    if not found:
        print("No se encontró ningún dispositivo en ese rango.")
    else:
        print(f"Dispositivos encontrados: {found}")
    return found


def scan_full_169254(
    start_octet2: int = 0,
    end_octet2: int = 255,
    start_octet3: int = 0,
    end_octet3: int = 255,
) -> List[str]:
    """Escaneo más amplio por toda la red 169.254.x.x (más lento).

    Para evitar bloquearse eternamente, solo sondea un subconjunto
    representativo de hosts en cada subred.

    Returns:
        Lista de IPs descubiertas.
    """
    print("Escaneo amplio en 169.254.x.x (puede tardar varios minutos)...")
    found: List[str] = []
    total = (end_octet2 - start_octet2 + 1) * (end_octet3 - start_octet3 + 1) * 254
    scanned = 0
    for oct2 in range(start_octet2, end_octet2 + 1):
        for oct3 in range(start_octet3, end_octet3 + 1):
            # Estrategia rápida: escaneamos .1, .100, .143, .200
            candidates = [f"169.254.{oct2}.{x}" for x in [1, 100, 143, 200] if 1 <= x <= 254]
            for ip in candidates:
                scanned += 1
                if scanned % 100 == 0:
                    print(f"  Progreso: {scanned}/{total}...")
                res = check_port(ip, 502, timeout=0.8)
                if res:
                    print(f"  [ENCONTRADO] {res}:502 responde!")
                    found.append(res)
    return found

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Buscar PLC mduino por Modbus TCP")
    parser.add_argument("--host", default=None, help="IP específica a probar")
    parser.add_argument("--scan", action="store_true", help="Escanear red 169.254.241.x")
    parser.add_argument("--wide", action="store_true", help="Escanear toda 169.254.x.x (lento)")
    args = parser.parse_args()

    if args.host:
        print(f"Probando {args.host}:502 ...")
        res = check_port(args.host, 502, timeout=3)
        if res:
            print("Conexión OK. Probando lectura Modbus...")
            try:
                from pymodbus.client import ModbusTcpClient
                client = ModbusTcpClient(args.host, port=502, timeout=2)
                if client.connect():
                    rr = client.read_coils(0, 2)
                    print(f"  Lectura Modbus: {rr.bits if rr and not rr.isError() else 'error'}")
                    client.close()
                else:
                    print("  No se pudo conectar por Modbus (puerto abierto pero sin respuesta)")
            except Exception as e:
                print(f"  Error Modbus: {e}")
        else:
            print(f"No hay respuesta en {args.host}:502")
    elif args.wide:
        scan_full_169254()
    else:
        scan_network()
