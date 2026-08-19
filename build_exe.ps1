# Skrypt PowerShell do budowania wersji EXE
$pythonExe = if (Test-Path "env\Scripts\python.exe") { "env\Scripts\python.exe" } else { "python" }
Write-Host "[INFO] Używanie interpretera: $pythonExe" -ForegroundColor Cyan
Write-Host "[INFO] Rozpoczynanie kompilacji PyInstaller..." -ForegroundColor Cyan

& $pythonExe scripts\build_exe.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[SUKCES] Gotowe! Aplikacja znajduje się w folderze: dist\InteligentnyDyktafonAI\" -ForegroundColor Green
} else {
    Write-Host "`n[BŁĄD] Wystąpił błąd podczas budowania." -ForegroundColor Red
}
Read-Host -Prompt "Naciśnij Enter, aby zakończyć"
