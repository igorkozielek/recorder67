"""
Moduł automatycznych aktualizacji (Auto-Updater) z GitHub Releases dla recorder67.
Obsługuje sprawdzanie wydań stabilnych i pre-release (alpha/beta), asynchroniczne pobieranie
oraz automatyczną podmianę plików aplikacji (in-place update) na Windowsie.
"""

import os
import sys
import re
import json
import shutil
import tempfile
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, Tuple
from PySide6.QtCore import QThread, Signal as pyqtSignal

from recorder.config import APP_VERSION, GITHUB_REPO


def parse_version(v_str: str) -> Tuple[int, int, int, int, str]:
    """
    Parsuje wersję w formacie semver (np. 'v0.3.0-alpha', '0.4.0', 'v0.2.1.2')
    do krotki umożliwiającej rzetelne porównywanie wersji.
    
    Zwraca (major, minor, patch, prerelease_rank, prerelease_suffix).
    """
    if not v_str:
        return (0, 0, 0, 0, "")
        
    clean_v = v_str.strip().lstrip("vV")
    
    # Rozdzielenie części głównej od przyrostka pre-release
    prerelease_suffix = ""
    prerelease_rank = 100  # Wersja stabilna (brak przyrostka) ma najwyższy priorytet
    
    if "-" in clean_v:
        main_part, prerelease_suffix = clean_v.split("-", 1)
        suffix_lower = prerelease_suffix.lower()
        if "alpha" in suffix_lower:
            prerelease_rank = 10
        elif "beta" in suffix_lower:
            prerelease_rank = 20
        elif "rc" in suffix_lower:
            prerelease_rank = 30
        else:
            prerelease_rank = 15
    else:
        main_part = clean_v
        
    digits = []
    for part in re.findall(r'\d+', main_part):
        try:
            digits.append(int(part))
        except ValueError:
            pass
            
    while len(digits) < 3:
        digits.append(0)
        
    return (digits[0], digits[1], digits[2], prerelease_rank, prerelease_suffix)


def is_newer_version(remote_tag: str, local_version: str = APP_VERSION) -> bool:
    """Zwraca True, jeśli remote_tag reprezentuje nowszą wersję niż local_version."""
    remote_parsed = parse_version(remote_tag)
    local_parsed = parse_version(local_version)
    
    # 1. Porównanie numerów wersji major.minor.patch
    if remote_parsed[:3] > local_parsed[:3]:
        return True
    elif remote_parsed[:3] < local_parsed[:3]:
        return False
        
    # 2. Przy równych numerach głównych (np. 0.3.0 vs 0.3.0-alpha), wersja stabilna jest nowsza od alpha
    return remote_parsed[3] > local_parsed[3]


def check_github_updates(
    repo: str = GITHUB_REPO,
    current_version: str = APP_VERSION,
    include_prereleases: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Odpytuje API GitHuba o najnowsze wydania repozytorium.
    Zwraca słownik z informacjami o aktualizacji lub None jeśli brak nowszej wersji.
    """
    url = f"https://api.github.com/repos/{repo}/releases"
    headers = {
        "User-Agent": f"Recorder67-App/{current_version}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, list) or not data:
                return None
                
            for release in data:
                is_draft = release.get("draft", False)
                is_prerelease = release.get("prerelease", False)
                
                if is_draft:
                    continue
                if is_prerelease and not include_prereleases:
                    continue
                    
                tag_name = release.get("tag_name", "")
                if not tag_name:
                    continue
                    
                if is_newer_version(tag_name, current_version):
                    # Szukanie assetu ZIP z aplikacją
                    assets = release.get("assets", [])
                    zip_asset = None
                    for a in assets:
                        a_name = a.get("name", "").lower()
                        if a_name.endswith(".zip"):
                            zip_asset = a
                            break
                            
                    return {
                        "has_update": True,
                        "current_version": current_version,
                        "latest_version": tag_name,
                        "release_title": release.get("name") or tag_name,
                        "release_notes": release.get("body", "Brak opisu zmian."),
                        "published_at": release.get("published_at", ""),
                        "is_prerelease": is_prerelease,
                        "html_url": release.get("html_url", ""),
                        "download_url": zip_asset.get("browser_download_url") if zip_asset else None,
                        "asset_name": zip_asset.get("name") if zip_asset else None,
                        "asset_size": zip_asset.get("size") if zip_asset else 0,
                    }
                    
            return None
    except Exception as err:
        print(f"[UPDATER] Błąd sprawdzania aktualizacji: {err}")
        return None


class CheckUpdateWorker(QThread):
    """Asynchroniczny wątek sprawdzający dostępność aktualizacji na GitHubie."""
    update_checked_signal = pyqtSignal(object)  # (dict_or_None)
    error_signal = pyqtSignal(str)

    def __init__(self, include_prereleases: bool = True):
        super().__init__()
        self.include_prereleases = include_prereleases

    def run(self):
        try:
            res = check_github_updates(include_prereleases=self.include_prereleases)
            self.update_checked_signal.emit(res)
        except Exception as e:
            self.error_signal.emit(str(e))


class DownloadUpdateWorker(QThread):
    """Asynchroniczny wątek pobierający paczkę ZIP z aktualizacją z GitHuba."""
    progress_signal = pyqtSignal(int, str)  # (procent, status_text)
    download_finished_signal = pyqtSignal(bool, str, str)  # (sukces, zip_path_lub_error, wersja)

    def __init__(self, download_url: str, target_version: str):
        super().__init__()
        self.download_url = download_url
        self.target_version = target_version
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if not self.download_url:
            self.download_finished_signal.emit(False, "Brak bezpośredniego adresu URL do pliku ZIP w wydaniu.", self.target_version)
            return

        temp_dir = tempfile.gettempdir()
        zip_path = os.path.join(temp_dir, f"InteligentnyDyktafonAI_{self.target_version}.zip")
        
        try:
            self.progress_signal.emit(5, "Nawiązywanie połączenia z serwerem wydań GitHub...")
            headers = {"User-Agent": f"Recorder67-App/{APP_VERSION}"}
            req = urllib.request.Request(self.download_url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                block_size = 1024 * 64  # 64 KB bufor
                
                with open(zip_path, "wb") as out_file:
                    while True:
                        if self._is_cancelled:
                            out_file.close()
                            if os.path.exists(zip_path):
                                os.remove(zip_path)
                            self.download_finished_signal.emit(False, "Pobieranie anulowane przez użytkownika.", self.target_version)
                            return
                            
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                            
                        out_file.write(buffer)
                        downloaded += len(buffer)
                        
                        if total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            d_mb = downloaded / (1024 * 1024)
                            t_mb = total_size / (1024 * 1024)
                            self.progress_signal.emit(min(98, max(5, pct)), f"Pobieranie aktualizacji: {d_mb:.1f} MB / {t_mb:.1f} MB ({pct}%)...")
                        else:
                            d_mb = downloaded / (1024 * 1024)
                            self.progress_signal.emit(50, f"Pobrano {d_mb:.1f} MB...")

            self.progress_signal.emit(100, "Pobieranie zakończone pomyślnie!")
            self.download_finished_signal.emit(True, zip_path, self.target_version)
        except Exception as e:
            self.download_finished_signal.emit(False, f"Błąd pobierania pliku: {e}", self.target_version)


def apply_in_place_update(zip_path: str, restart_after: bool = True) -> bool:
    """
    Przygotowuje i uruchamia skrypt podmiany plików w tle, po czym zamyka bieżącą aplikację.
    Działa zarówno dla wersji skompilowanej PyInstaller (.exe), jak i zgłasza informację w trybie dev.
    Parametr restart_after określa, czy po podmianie plików aplikacja ma się samoczynnie zrestartować.
    """
    if not os.path.exists(zip_path):
        return False
        
    is_frozen = getattr(sys, "frozen", False)
    if not is_frozen:
        # Tryb deweloperski (uruchomiony ze skryptu .py)
        # Nie nadpisujemy środowiska deweloperskiego plikami skompilowanymi .exe
        return False

    app_dir = os.path.dirname(os.path.abspath(sys.executable))
    exe_path = sys.executable
    current_pid = os.getpid()
    temp_extract = os.path.join(tempfile.gettempdir(), "InteligentnyDyktafonAI_Update")
    updater_bat = os.path.join(tempfile.gettempdir(), "run_app_update.bat")
    
    restart_cmd = f'start "" "{exe_path}"' if restart_after else 'rem Brak restartu (aktualizacja przy wyjsciu)'

    bat_content = f"""@echo off
rem Skrypt automatycznej podmiany plikow aktualizacji Recorder67
echo [UPDATER] Oczekiwanie na zakonczenie glownego procesu (PID: {current_pid})...
:wait_process
ping 127.0.0.1 -n 2 > nul
tasklist /fi "pid eq {current_pid}" 2>nul | find "{current_pid}" >nul
if not errorlevel 1 goto wait_process

echo [UPDATER] Proces aplikacji zamkniety. Rozpakowywanie nowej wersji...
if exist "{temp_extract}" rmdir /s /q "{temp_extract}" 2>nul
mkdir "{temp_extract}"

tar -xf "{zip_path}" -C "{temp_extract}" 2>nul
if not exist "{temp_extract}\\*" (
    powershell -NoProfile -Command "Expand-Archive -Path '{zip_path}' -DestinationPath '{temp_extract}' -Force"
)

echo [UPDATER] Kopiowanie plikow do: {app_dir}
if exist "{temp_extract}\\InteligentnyDyktafonAI" (
    robocopy "{temp_extract}\\InteligentnyDyktafonAI" "{app_dir}" /e /np /r:5 /w:1 > nul
) else (
    robocopy "{temp_extract}" "{app_dir}" /e /np /r:5 /w:1 > nul
)

echo [UPDATER] Czyszczenie plikow tymczasowych...
if exist "{zip_path}" del /f /q "{zip_path}" 2>nul
if exist "{temp_extract}" rmdir /s /q "{temp_extract}" 2>nul

echo [UPDATER] Finalizacja aktualizacji...
{restart_cmd}
exit /b 0
"""

    try:
        with open(updater_bat, "w", encoding="cp852", errors="replace") as f:
            f.write(bat_content)
            
        # Uruchom skrypt .bat jako niezależny proces w tle (detached process)
        subprocess.Popen(
            ["cmd.exe", "/c", updater_bat],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008),
            close_fds=True
        )
        return True
    except Exception as e:
        print(f"[UPDATER] Błąd uruchomienia skryptu aktualizatora: {e}")
        return False
