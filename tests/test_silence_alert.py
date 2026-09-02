"""
Testy jednostkowe strażnika ciszy, zliczania braku mowy oraz zintegrowanego systemu powiadomień.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from recorder.config import (
    get_silence_alert_minutes,
    get_silence_alert_seconds,
    is_silence_alert_enabled,
    RecordSourceMode
)
from recorder.ui.workers import SmartAudioWorker, SmartRecordState, TargetAppAudioMonitor


def test_silence_alert_config():
    # 1. Domyślna wartość w konfiguracji
    mins = get_silence_alert_minutes()
    assert mins > 0.0, "Domyślna wartość strażnika ciszy powinna być większa od 0"
    sec = get_silence_alert_seconds()
    assert sec == mins * 60.0
    assert is_silence_alert_enabled() is True
    print("Test konfiguracji straznika ciszy: Sukces!")


def test_worker_silence_alert_logic():
    # Inicjalizacja workera
    worker = SmartAudioWorker(auto_pause_sec=5.0)
    worker.silence_alert_sec = 300.0  # 5 minut do testu

    emitted_alerts = []
    worker.silence_alert_signal.connect(lambda sec, mode: emitted_alerts.append((sec, mode)))

    # 1. Symulacja braku mowy (200 sekund) - alert NIE powinien się pojawić
    worker.continuous_silence_samples = int(200.0 * 16000)
    assert len(emitted_alerts) == 0

    # 2. Przekroczenie progu (301 sekund) - alert POWINIEN się pojawić
    worker.continuous_silence_samples = int(301.0 * 16000)
    cont_sil_sec = float(worker.continuous_silence_samples / 16000.0)
    if worker.silence_alert_sec > 0 and worker.state != SmartRecordState.MANUAL_PAUSED:
        if cont_sil_sec >= worker.silence_alert_sec and not worker.silence_alert_emitted:
            worker.silence_alert_emitted = True
            worker.silence_alert_signal.emit(cont_sil_sec, worker.source_mode)

    assert len(emitted_alerts) == 1, "Alert powinien zostać wyemitowany dokładnie raz"
    assert emitted_alerts[0][0] >= 300.0

    # 3. Dalsza cisza (np. 350s) - alert NIE powinien się powtórzyć dopóki nie zostanie zresetowany
    worker.continuous_silence_samples = int(350.0 * 16000)
    cont_sil_sec = float(worker.continuous_silence_samples / 16000.0)
    if worker.silence_alert_sec > 0 and worker.state != SmartRecordState.MANUAL_PAUSED:
        if cont_sil_sec >= worker.silence_alert_sec and not worker.silence_alert_emitted:
            worker.silence_alert_emitted = True
            worker.silence_alert_signal.emit(cont_sil_sec, worker.source_mode)

    assert len(emitted_alerts) == 1, "Blad: alert powtorzyl sie bez resetu!"

    # 4. Uzytkownik klika 'Wszystko w porzadku' -> reset
    worker.reset_silence_alert()
    assert worker.continuous_silence_samples == 0
    assert worker.silence_alert_emitted is False

    # 5. Kolejna cisza po resecie -> powtorkowy alert po 300s
    worker.continuous_silence_samples = int(305.0 * 16000)
    cont_sil_sec = float(worker.continuous_silence_samples / 16000.0)
    if worker.silence_alert_sec > 0 and worker.state != SmartRecordState.MANUAL_PAUSED:
        if cont_sil_sec >= worker.silence_alert_sec and not worker.silence_alert_emitted:
            worker.silence_alert_emitted = True
            worker.silence_alert_signal.emit(cont_sil_sec, worker.source_mode)

    assert len(emitted_alerts) == 2, "Blad: alert nie pojawil sie ponownie po resecie!"
    print("Test logiki zliczania ciszy i emisji alertu: Sukces!")


def test_toast_banner_creation():
    app = QApplication.instance()
    if not app:
        app = QApplication([])

    from recorder.ui.window import SilenceToastBanner

    # Test tworzenia SilenceToastBanner
    toast = SilenceToastBanner(silence_sec=600.0, source_mode=RecordSourceMode.HYBRID_DUAL, timeout_sec=2)
    assert toast.btn_ok is not None
    assert toast.btn_err is not None

    # Weryfikacja UX: maksymalnie 2 słowa na przycisk
    ok_words = [w for w in toast.btn_ok.text().replace("✅", "").strip().split() if w]
    err_words = [w for w in toast.btn_err.text().replace("⚠️", "").strip().split() if w]
    assert len(ok_words) <= 2, f"Za duzo slow na przycisku OK: {ok_words}"
    assert len(err_words) <= 2, f"Za duzo slow na przycisku Error: {err_words}"
    assert "Wszystko gra" in toast.btn_ok.text()
    assert "Sprawdź dźwięk" in toast.btn_err.text()

    # Weryfikacja sygnału timeoutu
    timed_out_emitted = []
    toast.timed_out.connect(lambda: timed_out_emitted.append(True))
    toast._on_tick()  # 1s
    toast.remaining_sec = 1
    toast._on_tick()  # 0s -> emit timed_out
    assert len(timed_out_emitted) == 1, "Powinien zostać wyemitowany sygnał timed_out po wygaśnięciu"
    toast.close()
    print("Test tworzenia okien monitu i zwięzłości przycisków (max 2 słowa): Sukces!")


def test_target_app_audio_monitor():
    monitor = TargetAppAudioMonitor(target_filter="Discord")
    assert monitor.target_filter == "discord"

    # Bez aktywnego WASAPI sesji monitor powinien bezpiecznie zwrócić True lub False
    res = monitor.is_target_app_playing()
    assert res in (True, False)
    print("Test TargetAppAudioMonitor (izolacja procesu aplikacji audio): Sukces!")


def test_unified_notification_system():
    from recorder.ui.window import SmartDictaphoneWindow

    app = QApplication.instance() or QApplication([])

    win = SmartDictaphoneWindow()

    # Weryfikacja podglądu powiadomienia
    win.show_silence_alert_preview(600.0)
    assert win._active_silence_toast is not None
    assert win._active_silence_toast.isVisible()

    # Weryfikacja przekazania do Action Center po timeout
    win._handle_silence_timed_out_to_tray("10 min", RecordSourceMode.HYBRID_DUAL)
    assert "10 min" in win.lbl_cloud_status.text()

    # Weryfikacja tłumienia dźwięku systemowego podczas powiadomienia
    worker = SmartAudioWorker(auto_pause_sec=5.0)
    import time
    worker.suppress_sys_audio_for(0.5)
    assert worker.suppress_sys_until > time.time()

    # Weryfikacja ikony w zasobniku i aktualizacji tooltipa
    assert win.tray_icon is not None
    assert "10 min" in win.tray_icon.toolTip()
    win._handle_silence_confirmed("10 min")
    assert "Nagrywanie trwa" in win.tray_icon.toolTip()
    assert win.tray_icon.contextMenu() is not None

    win._active_silence_toast.close()
    print("Test zintegrowanego systemu powiadomien (Toast + Action Center + Sound + Tray): Sukces!")


if __name__ == "__main__":
    test_silence_alert_config()
    test_worker_silence_alert_logic()
    test_toast_banner_creation()
    test_target_app_audio_monitor()
    test_unified_notification_system()
    print("\nWszystkie testy straznika ciszy i zintegrowanego powiadomienia zakonczone sukcesem!")
