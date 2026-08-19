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

echo [INFO] Uruchamianie aplikacji...
env\Scripts\python.exe run.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [BLAD] Aplikacja zakonczyla dzialanie z bledem.
    pause
)
