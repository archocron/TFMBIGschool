@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo   TFMBigSchool + CCTV IP PoE - Inicio Rapido
echo ============================================
echo.

REM === 1. Verificar dependencias ===
if not exist "mediamtx.exe" (
    echo [ERROR] mediamtx.exe no encontrado.
    echo   Copialo desde el proyecto cctv2 o descargalo de:
    echo   https://github.com/bluenviron/mediamtx/releases
    pause
    exit /b 1
)

if not exist "tools\ffmpeg.exe" (
    echo [ERROR] ffmpeg.exe no encontrado en tools\ffmpeg.exe
    echo   Descargalo de https://www.gyan.dev/ffmpeg/builds/
    pause
    exit /b 1
)

if not exist "backend\venv\Scripts\python.exe" (
    echo [ERROR] No se encontro backend\venv\Scripts\python.exe
    echo   Crea el entorno virtual primero:
    echo     cd backend
    echo     py -3.12 -m venv venv
    echo     .\venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM === 2. Iniciar MediaMTX (nativo) ===
echo [1/4] Iniciando MediaMTX...
taskkill /F /IM mediamtx.exe >nul 2>&1
start "MediaMTX" mediamtx.exe cctv\mediamtx.yml

REM === 3. Esperar a que MediaMTX arranque ===
echo [2/4] Esperando MediaMTX (3s)...
timeout /t 3 /nobreak >nul

REM === 4. Iniciar FFmpeg (puente camara IP -> MediaMTX) ===
echo [3/4] Iniciando FFmpeg (RTSP camara IP -> RTMP MediaMTX)...
taskkill /F /IM ffmpeg.exe >nul 2>&1
start "FFmpeg CCTV" tools\ffmpeg.exe -rtsp_transport udp -i rtsp://admin:@169.254.241.135:554/live -c copy -f flv rtmp://localhost:1935/cam

REM === 5. Iniciar backend FastAPI ===
echo [4/4] Iniciando Backend FastAPI (GPU + Webcam + Modbus)...
start "TFM Backend" /D "%~dp0backend" "venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000

echo.
echo ============================================
echo   SISTEMA INICIADO
echo ============================================
echo.
echo   Frontend:     http://localhost:8000
echo   WebRTC:       http://localhost:8889/cam
echo   MediaMTX API: http://localhost:9997/v3/paths/list
echo.
echo   Ventanas abiertas:
echo     - MediaMTX (servidor streaming)
echo     - FFmpeg CCTV (puente camara IP)
echo     - TFM Backend (FastAPI + IA)
echo.
echo   Para detener: cierra las 3 ventanas de consola.
echo.
pause
