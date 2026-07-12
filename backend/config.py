"""Configuración de red PLC ↔ PC.

Hardware: M-Duino 21+ (Industrial Shields) con W5500 integrado.
El Arduino actúa como servidor Modbus TCP (esclavo) en puerto 502.
"""

PLC_HOST: str = "169.254.241.100"
PLC_PORT: int = 502

# IMPORTANTE: Si cambias esta IP, también debes cambiarla en:
#   arduino/conveyor_modbus_tcp/conveyor_modbus_tcp.ino  -> IPAddress ip(...)
#   Y volver a subir el sketch al M-Duino 21+.
#
# La conexión es por cable Ethernet directo (adaptador USB-Ethernet del PC).
# PC: 169.254.241.143
# PLC: 169.254.241.100 (configurada aquí)
