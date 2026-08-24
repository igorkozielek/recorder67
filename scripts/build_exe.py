"""
Skrypt budowania aplikacji Inteligentnego Dyktafonu AI do wersji .EXE (Windows).
Użycie:
    python scripts/build_exe.py
"""

import os
import sys
import subprocess
import shutil
import importlib.metadata
import importlib.util

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY_POINT = os.path.join(ROOT_DIR, "run.py")
DIST_DIR = os.path.join(ROOT_DIR, "dist")
BUILD_DIR = os.path.join(ROOT_DIR, "build")


def _is_module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def main():
    print("=" * 70)
    print("🚀 BUDOWANIE INTELIGENTNEGO DYKTAFONU AI DO PLIKU .EXE")
    print("=" * 70)

    # 1. Odblokowanie plików binarnych przed blokadą Windows Smart App Control
    try:
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

    # 2. Automatyczne wykrycie WSZYSTKICH pakietów zainstalowanych w środowisku env
    all_dists = []
    try:
        all_dists = sorted(list(set([
            dist.metadata['Name']
            for dist in importlib.metadata.distributions()
            if dist.metadata and 'Name' in dist.metadata
        ])))
        print(f"📦 Automatycznie wykryto {len(all_dists)} pakietów w środowisku Python.")
    except Exception as e:
        print(f"⚠️ Ostrzeżenie przy skanowaniu pakietów: {e}")

    # 3. Przygotuj parametry PyInstallera
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=InteligentnyDyktafonAI",
        "--onedir",                       # Folder z plikami DLL (najstabilniejszy dla modeli PyTorch/Whisper)
        "--clean",
        "--noconfirm",
        
        # Wykluczamy PyQt6, ponieważ aplikacja używa PySide6 (zapobiega konfliktom dwóch bibliotek Qt)
        "--exclude-module=PyQt6",
        "--exclude-module=PyQt6.QtCore",
        "--exclude-module=PyQt6.QtWidgets",
        "--exclude-module=PyQt6.QtGui",
        "--exclude-module=PyQt6_sip",

        # Zbieranie zależności i bibliotek C++/DLL dla wszystkich modułów AI
        *[
            f"--collect-all={pkg}"
            for pkg in [
                "faster_whisper",
                "silero_vad",
                "pyannote",
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
                "optuna",
                "torch",
                "torchaudio",
                "onnxruntime",
                "scipy"
            ]
            if _is_module_available(pkg.split('.')[0])
        ],
        
        # Automatyczne dołączenie metadanych dla 100% wykrytych pakietów w środowisku!
        *[
            f"--copy-metadata={dist_name}"
            for dist_name in all_dists
            if not dist_name.lower().startswith("pyqt6")
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
