@echo off
rem ==============================================================================
rem Skrypt budowania aplikacji Inteligentnego Dyktafonu AI do pliku EXE
rem ==============================================================================

set "PYTHON_CMD="
if exist "env\Scripts\python.exe" (
    set "PYTHON_CMD=env\Scripts\python.exe"
) else (
    set "PYTHON_CMD=python"
)

echo [INFO] Uzywanie interpretera: %PYTHON_CMD%
echo [INFO] Rozpoczynanie kompilacji PyInstaller...

%PYTHON_CMD% scripts\build_exe.py

if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUKCES] Gotowe! Plik wykonywalny znajduje sie w folderze: dist\InteligentnyDyktafonAI\
) else (
    echo.
    echo [BLAD] Wystapil blad podczas budowania. Kod bledu: %ERRORLEVEL%
)

pause
