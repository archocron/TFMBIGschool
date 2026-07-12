@echo off
echo [INFO] Deteniendo procesos...
taskkill /F /IM mediamtx.exe >nul 2>&1
taskkill /F /IM ffmpeg.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM uvicorn.exe >nul 2>&1
echo [OK] Procesos detenidos.
timeout /t 2 /nobreak >nul
