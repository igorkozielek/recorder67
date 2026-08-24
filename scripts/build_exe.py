"""
Skrypt budowania aplikacji Inteligentnego Dyktafonu AI do wersji .EXE (Windows).
Użycie:
    python scripts/build_exe.py
"""

import os
import sys
import subprocess
import shutil

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY_POINT = os.path.join(ROOT_DIR, "run.py")
DIST_DIR = os.path.join(ROOT_DIR, "dist")
BUILD_DIR = os.path.join(ROOT_DIR, "build")

def _is_package_installed(package_name: str) -> bool:
    try:
        import importlib.metadata
        importlib.metadata.distribution(package_name)
        return True
    except Exception:
        return False

def main():
    print("=" * 70)
    print("🚀 BUDOWANIE INTELIGENTNEGO DYKTAFONU AI DO PLIKU .EXE")
    print("=" * 70)

    # 1. Upewnij się, że pyinstaller jest zainstalowany i pliki są odblokowane
    try:
        # Odblokowanie plików binarnych przed Smart App Control
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "if (Test-Path 'env') { Get-ChildItem -Path 'env' -Recurse | Unblock-File }"],
            cwd=ROOT_DIR,
            capture_output=True
        )
    except Exception:
        pass

    try:
        import PyInstaller
        print(f"✅ Znaleziono PyInstaller w wersji: {PyInstaller.__version__}")
    except ImportError:
        print("📦 Instalowanie PyInstaller w środowisku...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Przygotuj parametry PyInstallera
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=InteligentnyDyktafonAI",
        "--onedir",                       # Folder z plikami DLL (najstabilniejszy dla modeli PyTorch/Whisper)
        "--clean",
        "--noconfirm",
        
        # Zbieranie GUI (PyQt6)
        "--collect-all=PyQt6",
        
        # Zbieranie zależności i bibliotek C++/DLL
        "--collect-all=faster_whisper",
        "--collect-all=silero_vad",
        "--collect-all=pyannote.audio",
        "--collect-all=ctranslate2",
        "--collect-all=sounddevice",
        "--collect-all=imageio_ffmpeg",
        "--collect-all=speechbrain",
        "--collect-all=lightning",
        "--collect-all=pytorch_lightning",
        
        # Metadane pakietów wymagane przez PyAnnote i HuggingFace (bezpiecznie filtrowane)
        *[
            f"--copy-metadata={pkg}"
            for pkg in [
                "faster_whisper",
                "huggingface_hub",
                "pyannote.audio",
                "pyannote.core",
                "pyannote.pipeline",
                "torch",
                "tqdm",
                "requests",
                "packaging",
                "filelock",
                "speechbrain"
            ]
            if _is_package_installed(pkg)
        ],
        
        # Dołączenie pliku .env (jeśli istnieje)
        f"--add-data={os.path.join(ROOT_DIR, '.env')};." if os.path.exists(os.path.join(ROOT_DIR, '.env')) else "",
        
        ENTRY_POINT
    ]

    # Usuń puste argumenty
    cmd = [arg for arg in cmd if arg]

    print("\n⏳ Rozpoczynanie kompilacji PyInstaller (może to zająć 2-4 minuty)...")
    result = subprocess.run(cmd, cwd=ROOT_DIR)

    if result.returncode == 0:
        output_folder = os.path.join(DIST_DIR, "InteligentnyDyktafonAI")
        exe_path = os.path.join(output_folder, "InteligentnyDyktafonAI.exe")
        
        # Skopiuj .env do folderu wyjściowego jeśli nie został automatycznie skopiowany
        env_src = os.path.join(ROOT_DIR, ".env")
        env_dst = os.path.join(output_folder, ".env")
        if os.path.exists(env_src) and not os.path.exists(env_dst):
            shutil.copy(env_src, env_dst)
            print("✅ Skopiowano plik konfiguracyjny .env do folderu aplikacji.")

        print("\n" + "=" * 70)
        print("🎉 SUKCES! Aplikacja została pomyślnie skompilowana!")
        print("=" * 70)
        print(f"📁 Folder aplikacji: {output_folder}")
        print(f"▶️ Plik startowy:    {exe_path}")
        print("\n💡 Aby przenieść aplikację na inne urządzenie:")
        print(f"   Spakuj cały folder '{os.path.basename(output_folder)}' do pliku .ZIP i wypakuj na urządzeniu docelowym.")
    else:
        print("\n❌ Błąd podczas budowania pliku .exe.")
        sys.exit(result.returncode)

if __name__ == "__main__":
    main()
