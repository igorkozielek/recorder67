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

def _has_metadata(package_name: str) -> bool:
    try:
        import importlib.metadata
        importlib.metadata.distribution(package_name)
        return True
    except Exception:
        return False


def _is_module_available(module_name: str) -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec(module_name) is not None
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
        
        # PySide6 jest ładowane przez standardowe hooki PyInstaller; nie kolekcjonujemy wszystkich modułów Qt.
        # Zbieranie zależności i bibliotek C++/DLL
        *[
            f"--collect-all={pkg}"
            for pkg in [
                "faster_whisper",
                "silero_vad",
                "pyannote.audio",
                "pyannote.core",
                "pyannote.pipeline",
                "pyannote.metrics",
                "pyannote.database",
                "pytorch_metric_learning",
                "ctranslate2",
                "sounddevice",
                "imageio_ffmpeg",
                "speechbrain",
                "lightning",
                "lightning_fabric",
                "lightning_utilities",
                "pytorch_lightning",
                "torchmetrics",
                "safetensors",
                "huggingface_hub",
                "optuna"
            ]
            if _is_module_available(pkg.split('.')[0])
        ],
        
        # Metadane pakietów wymagane przez PyAnnote, Lightning i HuggingFace (tylko istniejące dystrybucje)
        *[
            f"--copy-metadata={pkg}"
            for pkg in [
                "faster_whisper",
                "huggingface_hub",
                "pyannote.audio",
                "pyannote.core",
                "pyannote.pipeline",
                "pyannote.metrics",
                "pyannote.database",
                "pytorch_metric_learning",
                "torch",
                "torchaudio",
                "tqdm",
                "requests",
                "packaging",
                "filelock",
                "speechbrain",
                "lightning",
                "pytorch_lightning",
                "torchmetrics",
                "lightning_utilities",
                "pandas",
                "scipy",
                "safetensors",
                "optuna"
            ]
            if _has_metadata(pkg)
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
