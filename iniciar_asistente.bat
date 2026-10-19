@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo No se encontró .venv\Scripts\python.exe. Crea el entorno virtual primero.
  pause
  exit /b 1
)

:menu
cls
echo ================================================
echo       ASISTENTE VIRTUAL PROFUNDO - WINDOWS
echo ================================================
echo 1. Iniciar asistente completo
echo 2. Iniciar solo servidor Telegram
echo 3. Diagnostico GPU y Ollama
echo 4. Salir
choice /c 1234 /n /m "Selecciona una opcion: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto diagnostic
if errorlevel 2 goto telegram
if errorlevel 1 goto full

:full
REM Si Ollama esta instalado pero su puerto no responde, iniciarlo en segundo plano.
powershell.exe -NoProfile -Command "$c=Get-Command ollama -ErrorAction SilentlyContinue; if ($c) { $t=Test-NetConnection 127.0.0.1 -Port 11434 -InformationLevel Quiet -WarningAction SilentlyContinue; if (-not $t) { Start-Process -FilePath $c.Source -ArgumentList 'serve' -WindowStyle Hidden } }"
".venv\Scripts\python.exe" main.py
REM Codigo 3 = /reiniciar: vuelve a abrir el asistente con los cambios aplicados.
if %errorlevel%==3 goto full
goto end

:telegram
echo Iniciando el mismo main.py; el bot se activa si esta configurado en .env.
:telegram_loop
".venv\Scripts\python.exe" main.py
if %errorlevel%==3 goto telegram_loop
goto end

:diagnostic
powershell.exe -NoProfile -Command "$g=Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue; if ($g) { & $g.Source --query-gpu=name,memory.used,memory.total,temperature.gpu --format=csv,noheader } else { 'nvidia-smi no disponible' }; $t=Test-NetConnection 127.0.0.1 -Port 11434 -InformationLevel Quiet -WarningAction SilentlyContinue; 'Ollama 11434: ' + $t"
pause
goto menu

:end
pause
