#include <SPI.h>
#include <Ethernet.h>
#include <ArduinoModbus.h>

// -------------------- CONFIGURACION DE RED --------------------
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
IPAddress ip(169, 254, 241, 100);

// Servidor Modbus TCP (esclavo) en puerto 502
EthernetServer ethServer(502);
ModbusTCPServer modbusTCPServer;

// -------------------- PINOUT M-Duino 21+ --------------------
// I0_0 y Q0_0 son macros de Industrial Shields.
// Si no compilan, descomenta las lineas de abajo:
// #define I0_0 2   // Entrada digital 0
// #define Q0_0 3   // Salida digital 0 (rele de parada)

// -------------------- VARIABLES DE PROCESO --------------------
bool motorParado = false;         // true = Q0.0 HIGH = cinta PARADA
bool sensorAnterior = false;      // Estado previo del sensor para flanco
bool piezaDetectada = false;      // true = hay pieza nueva sin procesar
bool sensorLibre = true;        // true = sensor NO esta bloqueado por placa anterior
bool esperandoSalida = false;     // true = placa inspeccionada debe salir antes de nueva deteccion
unsigned long ultimoFlanco = 0;
unsigned long ignorarSensorHasta = 0; // ms hasta cuando ignorar el sensor tras arrancar cinta
const unsigned long COOLDOWN_MS = 2000;       // 2s entre piezas
const unsigned long IGNORAR_SENSOR_MS = 2000; // 2s de ventana muerta tras arrancar cinta

void setup()
{
    // --- Debug por Serial (USB) ---
    Serial.begin(115200);
    while (!Serial) { ; } // Esperar a que abran el monitor (solo en Leonardo/Micro)
    Serial.println("[PLC] M-Duino 21+ iniciando...");

    pinMode(I0_0, INPUT);
    pinMode(Q0_0, OUTPUT);
    digitalWrite(Q0_0, LOW);
    Serial.println("[PLC] Pines configurados: I0_0=INPUT, Q0_0=OUTPUT(LOW)");

    // --- Iniciar Ethernet (W5500 integrado) ---
    Ethernet.begin(mac, ip);
    ethServer.begin();
    Serial.print("[PLC] Ethernet iniciado. IP: ");
    Serial.println(ip);

    // --- Iniciar servidor Modbus TCP ---
    if (!modbusTCPServer.begin()) {
        Serial.println("[PLC] ERROR: No se pudo iniciar Modbus TCP Server");
        while (1) { delay(1000); }
    }
    Serial.println("[PLC] Modbus TCP Server iniciado en puerto 502");

    // Configurar 2 coils: 0=estado sensor, 1=comando liberar
    modbusTCPServer.configureCoils(0, 2);
    Serial.println("[PLC] Coils configurados: coil0=estado, coil1=comando");
    Serial.println("[PLC] === LISTO ===");
}

void loop()
{
    // --- Aceptar cliente Modbus TCP ---
    EthernetClient client = ethServer.available();
    if (client) {
        Serial.println("[PLC] Cliente Modbus conectado");
        modbusTCPServer.accept(client);
    }
    modbusTCPServer.poll();

    // --- Leer sensor I0.0 ---
    bool sensorActual = digitalRead(I0_0);

    // --- VENTANA MUERTA DEL SENSOR ---
    // Tras arrancar la cinta, ignoramos el sensor durante 2 segundos
    // para evitar que la placa recien inspeccionada (que aun se mueve)
    // genere falsos flancos por vibracion, bordes u orificios.
    bool sensorIgnorado = (millis() < ignorarSensorHasta);
    if (sensorIgnorado) {
        // Durante la ventana muerta solo actualizamos sensorAnterior
        // para no detectar flanco al terminar la ventana
        sensorAnterior = sensorActual;
        
        // Actualizar sensorLibre solo cuando el sensor baje a LOW
        // (la placa ya paso completamente)
        if (!sensorActual && !sensorLibre) {
            sensorLibre = true;
            Serial.println("[PLC] Sensor liberado DURANTE ventana muerta");
        }
        
        // Saltar toda la logica de deteccion durante la ventana muerta
        goto aplicar_salida;
    }

    // --- DETECCION POR FLANCO ASCENDENTE ---
    // Solo cuando:
    // - I0.0 pasa de LOW a HIGH (flanco ascendente)
    // - No hay pieza pendiente (!piezaDetectada)
    // - Sensor esta libre (placa anterior ya salio)
    // - Ha pasado el cooldown desde la ultima pieza
    if (sensorActual && !sensorAnterior && !piezaDetectada && sensorLibre)
    {
        unsigned long ahora = millis();
        if (ahora - ultimoFlanco >= COOLDOWN_MS) {
            motorParado = true;      // PARAR cinta inmediatamente
            piezaDetectada = true;   // Marcar pieza para el PC
            sensorLibre = false;     // Sensor ahora ocupado por esta placa
            esperandoSalida = true;  // Esperar a que esta placa salga
            ultimoFlanco = ahora;
            Serial.println("[PLC] FLANCO DETECTADO -> Cinta PARADA (Q0.0=HIGH)");
            Serial.println("[PLC] piezaDetectada=true, esperando decision del PC");
        } else {
            Serial.print("[PLC] Flanco ignorado (cooldown: ");
            Serial.print(ahora - ultimoFlanco);
            Serial.println("ms)");
        }
    }
    sensorAnterior = sensorActual;

    // --- DETECTAR CUANDO LA PLACA SALE DEL SENSOR ---
    // Cuando el sensor baja a LOW y estabamos esperando que saliera,
    // la placa ha salido -> sensor libre
    if (!sensorActual && esperandoSalida)
    {
        sensorLibre = true;
        esperandoSalida = false;
        Serial.println("[PLC] Sensor liberado (placa salio). Listo para siguiente pieza.");
    }

    // --- PUBLICAR ESTADO EN MODBUS ---
    modbusTCPServer.coilWrite(0, piezaDetectada ? 1 : 0);

    // --- LEER COMANDO DEL PC (coil 1) ---
    // El PC escribe coil1=1 cuando ha terminado de analizar.
    // Sea OK o NG+Continuar, siempre arrancamos la cinta.
    if (modbusTCPServer.coilRead(1) == 1)
    {
        Serial.println("[PLC] Comando recibido del PC (coil1=1)");

        if (motorParado) {
            motorParado = false;
            digitalWrite(Q0_0, LOW);
            Serial.println("[PLC] Cinta ARRANCADA (Q0.0=LOW)");
        }
        piezaDetectada = false;

        // ACTIVAR VENTANA MUERTA DEL SENSOR
        // Durante 2 segundos el sensor queda completamente ignorado.
        // Esto evita que la placa que acaba de ser inspeccionada
        // (que aun esta saliendo de la zona del sensor) genere falsos triggers.
        ignorarSensorHasta = millis() + IGNORAR_SENSOR_MS;
        Serial.print("[PLC] Ventana muerta activada: ignorar sensor hasta +");
        Serial.print(IGNORAR_SENSOR_MS);
        Serial.println("ms");

        // Resetear coil1
        modbusTCPServer.coilWrite(1, 0);
        Serial.println("[PLC] Coil1 reseteado a 0");
    }

aplicar_salida:
    // --- Aplicar salida Q0.0 ---
    digitalWrite(Q0_0, motorParado ? HIGH : LOW);
}
