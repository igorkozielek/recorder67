@echo off
chcp 65001 > nul
echo ==============================================================================
echo 🚀 Rozpoczynanie budowania Inteligentnego Dyktafonu AI do pliku .EXE
echo ==============================================================================

if exist env\Scripts\python.exe (
    set PYTHON_EXE=env\Scripts\python.exe
) else (
    set PYTHON_EXE=python
)

%PYTHON_EXE% scripts\build_exe.py

if %ERRORLEVEL% equ 0 (
    echo.
    echo ✅ Gotowe! Plik wykonywalny znajduje sie w folderze: dist\InteligentnyDyktafonAI\
    pause
) else (
    echo.
    echo ❌ Wystapil blad podczas budowania.
    pause
)
