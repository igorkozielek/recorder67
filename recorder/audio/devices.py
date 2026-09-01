import sounddevice as sd
from typing import List, Dict, Any, Optional

try:
    import pyaudiowpatch as pyaudio
    HAS_PYAUDIOWPATCH = True
except ImportError:
    pyaudio = None
    HAS_PYAUDIOWPATCH = False

try:
    from pycaw.pycaw import AudioUtilities
    HAS_PYCAW = True
except ImportError:
    HAS_PYCAW = False


def get_working_input_devices(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Pobiera listę sprawnych urządzeń wejściowych (mikrofonów), ignorując surowe sterowniki WDM-KS.
    """
    valid_devices = []
    if HAS_PYAUDIOWPATCH:
        p = None
        try:
            p = pyaudio.PyAudio()
            hostapis = {}
            for i in range(p.get_host_api_count()):
                info = p.get_host_api_info_by_index(i)
                hostapis[i] = info.get('name', '')

            for idx in range(p.get_device_count()):
                dev = p.get_device_info_by_index(idx)
                if dev.get('maxInputChannels', 0) > 0 and not dev.get('isLoopbackDevice', False) and '[Loopback]' not in dev.get('name', ''):
                    hostapi_name = hostapis.get(dev.get('hostApi', 0), '')
                    if "WDM-KS" in hostapi_name:
                        continue
                    valid_devices.append({
                        'index': idx,
                        'name': dev['name'],
                        'hostapi': hostapi_name,
                        'channels': int(dev['maxInputChannels']),
                        'samplerate': int(dev.get('defaultSampleRate', 16000))
                    })
        except Exception as e:
            print(f"Błąd wykrywania mikrofonów PyAudio: {e}")
        finally:
            if p:
                try:
                    p.terminate()
                except Exception:
                    pass

        if valid_devices:
            return valid_devices

    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()

        for idx, dev in enumerate(devices):
            if dev.get('max_input_channels', 0) > 0:
                hostapi_idx = dev.get('hostapi', 0)
                hostapi_name = hostapis[hostapi_idx]['name'] if hostapi_idx < len(hostapis) else ""
                
                # WDM-KS na Windows powoduje błąd "Blocking API not supported" w PortAudio
                if "WDM-KS" in hostapi_name:
                    continue

                valid_devices.append({
                    'index': idx,
                    'name': dev['name'],
                    'hostapi': hostapi_name,
                    'channels': dev['max_input_channels'],
                    'samplerate': int(dev.get('default_samplerate', 16000))
                })
    except Exception as e:
        print(f"Błąd wykrywania urządzeń audio: {e}")

    return valid_devices


def get_working_loopback_devices() -> List[Dict[str, Any]]:
    """
    Pobiera listę dostępnych urządzeń WASAPI Loopback (Głośniki / Słuchawki / Dźwięk Systemu).
    Pozwala na bezpośrednie rejestrowanie dźwięku z Discorda, Teamsa, YouTube, itp.
    """
    loopback_devices = []
    if not HAS_PYAUDIOWPATCH:
        return loopback_devices

    p = None
    try:
        p = pyaudio.PyAudio()
        default_loopback_idx = None
        try:
            def_loop = p.get_default_wasapi_loopback()
            if def_loop:
                default_loopback_idx = def_loop.get('index')
        except Exception:
            pass

        for loopback in p.get_loopback_device_info_generator():
            idx = loopback.get('index')
            name = loopback.get('name', 'Nieznane urządzenie loopback')
            is_default = (idx == default_loopback_idx)
            
            clean_name = name.replace(" [Loopback]", "").strip()
            label = f"🎧 {clean_name}"
            if is_default:
                label += " (Domyślne)"

            loopback_devices.append({
                'index': idx,
                'name': name,
                'label': label,
                'channels': int(loopback.get('maxInputChannels', 2)),
                'samplerate': int(loopback.get('defaultSampleRate', 48000)),
                'is_loopback': True,
                'is_default': is_default,
                'raw_info': loopback
            })
    except Exception as e:
        print(f"Błąd pobierania urządzeń WASAPI Loopback: {e}")
    finally:
        if p:
            try:
                p.terminate()
            except Exception:
                pass

    return loopback_devices


def get_active_audio_apps() -> List[Dict[str, Any]]:
    """
    Pobiera listę uruchomionych aplikacji, które aktualnie posiadają aktywną sesję audio w systemie Windows
    (np. Discord.exe, ms-teams.exe, firefox.exe, chrome.exe).
    """
    apps = []
    if not HAS_PYCAW:
        return apps

    try:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass

        sessions = AudioUtilities.GetAllSessions()
        seen_names = set()
        for session in sessions:
            if session.Process and session.Process.name():
                exe_name = session.Process.name()
                pid = session.Process.pid
                if exe_name.lower() in seen_names or exe_name.lower() in ("system sounds", "svchost.exe"):
                    continue
                seen_names.add(exe_name.lower())
                
                # Czysta, uniwersalna nazwa programu na podstawie pliku wykonywalnego
                clean_name = exe_name[:-4] if exe_name.lower().endswith(".exe") else exe_name
                display_name = clean_name.capitalize() if clean_name.islower() else clean_name

                apps.append({
                    'name': display_name,
                    'exe': exe_name,
                    'pid': pid
                })
    except Exception as e:
        print(f"Błąd pobierania sesji audio aplikacji: {e}")

    return apps
