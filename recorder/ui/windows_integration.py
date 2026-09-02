"""
Integracja z powłoką systemu Windows:
1. Rejestracja unikalnego AppUserModelID (AUMID).
2. Obsługa ikony aplikacji (pasek zadań, okno, tray).
3. Wysyłanie natywnych powiadomień Windows Toast z nazwą i ikoną aplikacji.
"""

import os
import sys
import ctypes
import base64
import subprocess
import threading
from typing import Optional

APP_ID = "InteligentnyDyktafonAI"
APP_NAME = "Inteligentny Dyktafon AI"


def get_app_icon_path(ext: str = "ico") -> str:
    """Zwraca bezwzględną ścieżkę do ikony aplikacji (.ico lub .png)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(base_dir, "resources", f"app_icon.{ext}")
    if os.path.exists(target):
        return os.path.abspath(target)
    # Sprawdzenie w głównym katalogu
    root_dir = os.path.dirname(base_dir)
    target_root = os.path.join(root_dir, "recorder", "resources", f"app_icon.{ext}")
    if os.path.exists(target_root):
        return os.path.abspath(target_root)
    return ""


def _run_hidden_powershell(encoded_cmd: str, timeout: int = 5):
    """Uruchamia polecenie PowerShell w 100% ukrytym procesie bez migania okna konsoli."""
    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        creationflags = 0x08000000  # CREATE_NO_WINDOW

    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded_cmd],
        capture_output=True,
        startupinfo=startupinfo,
        creationflags=creationflags,
        timeout=timeout
    )


def setup_windows_app_identity():
    """
    Konfiguruje tożsamość aplikacji w Windows:
    - Ustawia SetCurrentProcessExplicitAppUserModelID, aby pasek zadań i Alt+Tab
      wyświetlały dedykowaną ikonę zamiast standardowej ikony Pythona.
    - Rejestruje AUMID w rejestrze (HKCU), aby Windows Action Center rozpoznawał
      aplikację jako 'Inteligentny Dyktafon AI' z własną ikoną.
    """
    if sys.platform != "win32":
        return

    # 1. Jawny AppUserModelID dla procesu
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception as e:
        print(f"[WindowsIntegration] Błąd SetCurrentProcessExplicitAppUserModelID: {e}")

    # 2. Rejestracja w rejestrze użytkownika (HKCU - brak wymogu uprawnień administratora)
    try:
        import winreg
        key_path = rf"Software\Classes\AppUserModelId\{APP_ID}"
        ico_path = get_app_icon_path("ico") or get_app_icon_path("png")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            if ico_path:
                winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, ico_path)
            winreg.SetValueEx(k, "IconBackgroundColor", 0, winreg.REG_SZ, "FF1E1E2F")
        # Rejestracja w ustawieniach powiadomień Windows (priorytet i brak wyciszania)
        settings_key = rf"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\{APP_ID}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, settings_key) as sk:
            winreg.SetValueEx(sk, "ShowInActionCenter", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(sk, "Enabled", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(sk, "AllowUrgentNotifications", 0, winreg.REG_DWORD, 1)
    except Exception as e:
        print(f"[WindowsIntegration] Błąd rejestracji AUMID w HKCU: {e}")

    # 3. Utworzenie skrótu w Menu Start (wymagane przez Action Center Windows 10/11)
    try:
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            programs_dir = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")
            shortcut_path = os.path.join(programs_dir, f"{APP_NAME}.lnk")
            ico_path = get_app_icon_path("ico")
            if not os.path.exists(shortcut_path) and os.path.exists(programs_dir):
                # Skrypt PowerShell do utworzenia skrótu
                ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{shortcut_path}')
$sc.TargetPath = '{sys.executable}'
$sc.Arguments = '"{os.path.abspath(sys.argv[0])}"'
$sc.Description = '{APP_NAME}'
$sc.IconLocation = '{ico_path},0'
$sc.Save()
"""
                encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
                _run_hidden_powershell(encoded, timeout=4)
    except Exception:
        pass


def send_native_windows_toast(title: str, message: str, icon_path: Optional[str] = None):
    """
    Wysyła natywne powiadomienie Toast w Windows 10/11 za pośrednictwem Windows Notification Platform.
    Dzięki scenariuszowi 'reminder' oraz 'Priority = High' powiadomienie jest klasyfikowane
    jako priorytetowy alarm i może przebijać tryb 'Nie przeszkadzać'.
    """
    if sys.platform != "win32":
        return

    def _async_send():
        try:
            png_icon = icon_path or get_app_icon_path("png") or get_app_icon_path("ico")
            # Bezpieczne ścieżki Windows dla XML
            safe_icon_uri = ""
            if png_icon and os.path.exists(png_icon):
                safe_icon_uri = "file:///" + os.path.abspath(png_icon).replace("\\", "/")

            # Przygotowanie XML szablonu ToastGeneric ze scenariuszem reminder (alarm priorytetowy)
            img_tag = f'<image placement="appLogoOverride" hint-crop="circle" src="{safe_icon_uri}"/>' if safe_icon_uri else ""
            
            # Bezpieczne encje XML
            safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            safe_msg = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

            xml_content = f"""<toast scenario="reminder"><visual><binding template="ToastGeneric">{img_tag}<text>{safe_title}</text><text>{safe_msg}</text></binding></visual></toast>"""

            ps_code = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$xml = '{xml_content}'
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
$toast.Priority = [Windows.UI.Notifications.ToastNotificationPriority]::High
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}')
$notifier.Show($toast)
"""
            encoded = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
            _run_hidden_powershell(encoded, timeout=5)
        except Exception as e:
            print(f"[WindowsIntegration] Błąd wysyłania Toast: {e}")

    thread = threading.Thread(target=_async_send, daemon=True)
    thread.start()
