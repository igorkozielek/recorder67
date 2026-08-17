import sounddevice as sd
from typing import List, Dict, Any


def get_working_input_devices() -> List[Dict[str, Any]]:
    """
    Pobiera listę sprawnych urządzeń wejściowych, ignorując surowe sterowniki WDM-KS
    powodujące błędy PortAudio w systemie Windows.
    """
    valid_devices = []
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
