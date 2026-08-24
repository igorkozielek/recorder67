@echo off
chcp 65001 > nul
echo ==============================================================================
echo 🎙️ URUCHAMIANIE INTELIGENTNEGO DYKTAFONU AI
echo ==============================================================================

if not exist env (
    echo [INFO] Pierwsze uruchomienie: tworzenie srodowiska wirtualnego env...
    python -m venv env
    echo [INFO] Instalowanie wymaganych bibliotek...
    env\Scripts\pip.exe install -r requirements.txt
)

REM Automatyczne odblokowanie bibliotek C/DLL (.pyd) zablokowanych przez Windows Smart App Control
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path 'env') { Get-ChildItem -Path 'env' -Recurse | Unblock-File }" >nul 2>&1

echo [INFO] Uruchamianie aplikacji...
env\Scripts\python.exe run.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [BLAD] Aplikacja zakonczyla dzialanie z bledem.
    pause
)
