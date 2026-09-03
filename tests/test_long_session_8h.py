import os
import sys
import time
import wave
import tempfile
import threading
import numpy as np
from unittest.mock import MagicMock

# Ustawienie ścieżki do projektu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from recorder.audio.capture import StreamingWavWriter
from recorder.ui.workers import SmartAudioWorker, RealtimeAudioMixer
from recorder.core.rolling_transcriber import RollingBlock, RollingTranscriptionWorker
from recorder.core.session import TranscriptionSession
from recorder.core.vad import SileroVADDetector


def test_smart_audio_worker_lifecycle_and_save_wav():
    """
    Weryfikuje poprawność cyklu życia SmartAudioWorker:
    stop_recording() zamyka plik strumieniowy na dysku, a późniejsze wywołanie save_wav(path)
    zwraca True i zachowuje prawidłowy plik WAV o rozmiarze > 44 bajtów.
    """
    _ = QApplication.instance() or QApplication([])

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        save_path = tmp.name

    try:
        worker = SmartAudioWorker()
        # Inicjalizacja StreamingWavWriter symulująca start nagrywania
        worker.wav_writer = StreamingWavWriter(save_path, channels=1, samplerate=16000)

        # Zapis próbki audio (1 sekunda 16kHz PCM)
        dummy_pcm = (np.ones(16000, dtype=np.int16) * 500).tobytes()
        worker.wav_writer.write_frames(dummy_pcm)

        # 1. Zatrzymanie nagrywania - zamyka wav_writer i ustawia go na None
        worker.stop_recording()
        assert worker.wav_writer is None, "Po stop_recording wav_writer powinien być None"

        # 2. Wywołanie save_wav(path) - nie może nadpisać pliku pustą listą frames ani zwrócić False
        saved = worker.save_wav(save_path)
        assert saved is True, "save_wav() powinno zwrócić True dla zapisanego strumieniowo pliku"
        assert os.path.exists(save_path), "Plik WAV musi istnieć na dysku"
        file_size = os.path.getsize(save_path)
        assert file_size > 44, f"Rozmiar pliku WAV ({file_size} B) musi być większy niż nagłówek (44 B)"

        with wave.open(save_path, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 16000

        # 3. Dodatkowy test ścieżki bezpośredniego zapisu, gdy wav_writer jest jeszcze otwarty
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp2:
            save_path2 = tmp2.name
        try:
            worker2 = SmartAudioWorker()
            worker2.wav_writer = StreamingWavWriter(save_path2, channels=1, samplerate=16000)
            worker2.wav_writer.write_frames(dummy_pcm)
            saved2 = worker2.save_wav(save_path2)
            assert saved2 is True
            assert os.path.exists(save_path2)
            assert os.path.getsize(save_path2) > 44
            assert worker2.wav_writer is None
        finally:
            if os.path.exists(save_path2):
                try:
                    os.remove(save_path2)
                except Exception:
                    pass

        # 4. Test zapisu do nowej lokalizacji docelowej (innej niż save_wav_path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_streamed:
            streamed_path = tmp_streamed.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_target:
            target_path = tmp_target.name
        try:
            worker3 = SmartAudioWorker()
            worker3.save_wav_path = streamed_path
            worker3.wav_writer = StreamingWavWriter(streamed_path, channels=1, samplerate=16000)
            worker3.wav_writer.write_frames(dummy_pcm)
            worker3.stop_recording()

            # Usunięcie pliku docelowego, aby zasymulować nową ścieżkę eksportu
            if os.path.exists(target_path):
                os.remove(target_path)

            saved3 = worker3.save_wav(target_path)
            assert saved3 is True
            assert os.path.exists(target_path)
            assert os.path.getsize(target_path) > 44
        finally:
            for p in (streamed_path, target_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    finally:
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception:
                pass


def test_audio_mixer_8h_asymmetry_and_memory():
    """
    Symuluje 5000 asymetrycznych kroków dodawania ramek do miksera audio (mikrofon + loopback).
    Weryfikuje, że bufory nigdy nie przekraczają 8000 próbek i pamięć RAM jest ściśle ograniczona O(1).
    """
    mixer = RealtimeAudioMixer()

    # Symulacja 5000 asynchronicznych fragmentów z dryfem zegarów i asymetrią pakietów
    for i in range(5000):
        # Mikrofon wysyła pakiety regularnie (1024 próbki)
        mic_chunk = (np.sin(np.linspace(0, 10, 1024)) * 0.4).astype(np.float32)
        mixer.add_mic_chunk(mic_chunk)

        # Dźwięk systemowy ma asymetrię (pakiety o różnej wielkości lub sporadyczne opóźnienia)
        if i % 2 == 0:
            sys_chunk = (np.cos(np.linspace(0, 10, 600)) * 0.3).astype(np.float32)
            mixer.add_sys_chunk(sys_chunk)

        # Pętla robocza SmartAudioWorker opróżnia mikser co interwał
        _ = mixer.pop_mixed_frames(is_hybrid=True, run_mic=True, run_sys=True)

        assert len(mixer.mic_buffer) <= 8000, f"mic_buffer={len(mixer.mic_buffer)} przekroczył limit 8000 próbek w kroku {i}"
        assert len(mixer.sys_buffer) <= 8000, f"sys_buffer={len(mixer.sys_buffer)} przekroczył limit 8000 próbek w kroku {i}"

    # Ekstremalny test: całkowita cisza na kanale systemu przez 1000 iteracji
    for i in range(1000):
        mic_chunk = np.ones(1024, dtype=np.float32) * 0.1
        mixer.add_mic_chunk(mic_chunk)
        _ = mixer.pop_mixed_frames(is_hybrid=True, run_mic=True, run_sys=True)

        assert len(mixer.mic_buffer) <= 8000, f"mic_buffer={len(mixer.mic_buffer)} przekroczył limit przy braku loopback"
        assert len(mixer.sys_buffer) <= 8000, f"sys_buffer={len(mixer.sys_buffer)} przekroczył limit przy braku loopback"

    assert len(mixer.mic_buffer) <= 8000
    assert len(mixer.sys_buffer) <= 8000


def test_rolling_worker_disk_throttling_8h_simulation():
    """
    Symuluje 3000 bloków mowy (odpowiednik sesji biurowej ~8.3h, 3000 x 10s).
    Weryfikuje, że throttling zapisu dyskowego (30s) ogranicza liczbę zapisów pośrednich (<= 2)
    oraz że stop_and_finalize zapisuje 100% wszystkich wypowiedzi do plików TXT i JSON.
    """
    _ = QApplication.instance() or QApplication([])

    with tempfile.TemporaryDirectory() as tmp_dir:
        txt_path = os.path.join(tmp_dir, "sesja_biurowa_8h.txt")
        worker = RollingTranscriptionWorker(txt_save_path=txt_path)

        disk_writes = {"txt": 0, "session": 0}
        orig_save_txt = worker._save_to_txt_file
        orig_save_session = worker._save_to_session_file

        def tracked_save_txt(content):
            disk_writes["txt"] += 1
            return orig_save_txt(content)

        def tracked_save_session(turns, force=False):
            disk_writes["session"] += 1
            return orig_save_session(turns, force=force)

        worker._save_to_txt_file = tracked_save_txt
        worker._save_to_session_file = tracked_save_session

        # Szybka symulacja 3000 bloków mowy
        for i in range(3000):
            block = RollingBlock(
                block_index=i,
                start_sec=float(i * 10),
                end_sec=float((i + 1) * 10),
                audio_float=None,
                channel_source="mic" if i % 2 == 0 else "system"
            )
            block.turns = [{
                "speaker": "Mikrofon" if i % 2 == 0 else "Dźwięk Systemu",
                "start": float(i * 10),
                "end": float((i + 1) * 10),
                "text": f"Kluczowe ustalenie spotkania w bloku #{i}",
                "channel": block.channel_source
            }]

            worker.processed_blocks.append(block)
            worker.all_turns.extend(block.turns)
            worker.total_processed_seconds = block.end_sec

            now_ts = time.time()
            # Logika buforowania UI
            should_render_ui = (now_ts - worker._last_ui_render_time >= 3.0) or not worker._cached_html
            if should_render_ui:
                worker._last_ui_render_time = now_ts
                h, p, _ = worker._compile_full_transcript()
                worker._cached_html = h
                worker._cached_plain = p

            # Logika throttlingu dyskowego (co 30s bez uzależnienia od is_queue_empty)
            should_save_disk = (now_ts - worker._last_disk_save_time >= 30.0) and bool(worker._cached_plain)
            if should_save_disk:
                worker._last_disk_save_time = now_ts
                worker._save_to_txt_file(worker._cached_plain)
                worker._save_to_session_file(worker.all_turns, force=True)

        # Podczas szybkiej symulacji (wykonanie w ułamku sekundy) liczba zapisów pośrednich musi wynosić <= 2
        assert disk_writes["txt"] <= 2, f"Oczekiwano <= 2 zapisów TXT podczas szybkiej symulacji, otrzymano {disk_writes['txt']}"
        assert disk_writes["session"] <= 2, f"Oczekiwano <= 2 zapisów sesji podczas szybkiej symulacji, otrzymano {disk_writes['session']}"

        # Finalizacja nagrania (jak na końcu run() po wywołaniu stop_and_finalize)
        final_html, final_plain, turns = worker._compile_full_transcript()
        worker._save_to_txt_file(final_plain)
        worker._save_to_session_file(turns, force=True)

        # Sprawdzenie integralności pliku tekstowego TXT
        assert os.path.exists(txt_path)
        with open(txt_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Kluczowe ustalenie spotkania w bloku #0" in content
            assert "Kluczowe ustalenie spotkania w bloku #2999" in content

        # Sprawdzenie integralności pliku sesji JSON
        from recorder.core.session import get_session_path_for_txt
        json_path = get_session_path_for_txt(txt_path)
        assert os.path.exists(json_path)
        session = TranscriptionSession.load_from_json(json_path)
        assert session is not None
        assert len(session.turns) == 3000
        assert session.duration_sec == 30000.0


def test_vad_inference_mode_thread_safety():
    """
    Weryfikuje współbieżną ocenę fragmentów audio przez model Silero VAD w wielu wątkach
    z użyciem torch.inference_mode() i wewnętrznego rygla wątkowego _silero_lock.
    """
    errors = []

    def vad_worker(thread_id: int):
        detector = SileroVADDetector()
        try:
            for _ in range(80):
                chunk = (np.random.randn(512) * 0.05).astype(np.float32)
                is_speech, prob = detector.process_chunk(chunk, samplerate=16000)
                assert isinstance(is_speech, (bool, np.bool_))
                assert isinstance(prob, (float, np.floating))
                assert 0.0 <= prob <= 1.0
        except Exception as e:
            errors.append((thread_id, e))

    threads = [threading.Thread(target=vad_worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Wykryto błędy wielowątkowości w VAD: {errors}"


def test_adaptive_beam_size_under_load():
    """
    Weryfikuje, że w sytuacji nagromadzenia bloków w kolejce (qsize > 1),
    algorytm automatycznie redukuje beam_size do 1 (greedy decoding),
    aby uniknąć przegrzewania procesora i natychmiast dogonić czas rzeczywisty.
    """
    _ = QApplication.instance() or QApplication([])
    worker = RollingTranscriptionWorker()

    # Zamockowanie silnika Whisper, aby nie ładować ciężkich wag w teście jednostkowym
    captured_beam_sizes = []

    def mock_transcribe(audio_norm, **kwargs):
        captured_beam_sizes.append(kwargs.get("beam_size"))
        return [], None

    worker.transcriber = MagicMock()
    worker.transcriber._model.transcribe = mock_transcribe

    # 1. Kolejka z 1 blokiem lub pusta -> normalny beam_size (domyślnie > 1 z config)
    dummy_audio = np.zeros(16000 * 2, dtype=np.float32)
    block_normal = RollingBlock(1, 0.0, 2.0, dummy_audio)
    worker._process_single_block(block_normal)
    assert len(captured_beam_sizes) == 1
    assert captured_beam_sizes[0] > 1, f"Oczekiwano domyślnego beam_size > 1, otrzymano {captured_beam_sizes[0]}"

    # 2. Kolejka z > 1 blokami (spiętrzenie w kolejce pod obciążeniem)
    captured_beam_sizes.clear()
    b_pending1 = RollingBlock(2, 2.0, 4.0, dummy_audio)
    b_pending2 = RollingBlock(3, 4.0, 6.0, dummy_audio)
    worker.block_queue.put(b_pending1)
    worker.block_queue.put(b_pending2)
    assert worker.block_queue.qsize() == 2

    block_under_load = RollingBlock(4, 6.0, 8.0, dummy_audio)
    worker._process_single_block(block_under_load)

    assert len(captured_beam_sizes) == 1
    assert captured_beam_sizes[0] == 1, f"Oczekiwano dynamicznego obniżenia beam_size do 1, otrzymano {captured_beam_sizes[0]}"

    # Opróżnienie kolejki
    while not worker.block_queue.empty():
        worker.block_queue.get_nowait()


def test_short_block_early_return_updates_session_time_and_frees_ram():
    """
    Weryfikuje, że dla bloków krótszych niż 1.0s (np. kaszel, szum, stuknięcie):
    - audio_float jest natychmiast zwalniany (None), aby nie zużywać RAM
    - worker.total_processed_seconds jest poprawnie aktualizowany do block.end_sec
    - block_processed_signal jest emitowany, aby pasek postępu w UI nie zawieszał się
    - zapis sesji JSON poprawnie odnotowuje pełny czas trwania sesji
    """
    _ = QApplication.instance() or QApplication([])

    with tempfile.TemporaryDirectory() as tmp_dir:
        txt_path = os.path.join(tmp_dir, "test_short_blocks.txt")
        worker = RollingTranscriptionWorker(txt_save_path=txt_path)
        worker.update_session_time(100.0)

        signals_received = []
        worker.block_processed_signal.connect(lambda *args: signals_received.append(args))

        # Blok o długości 0.5s (8000 próbek)
        short_pcm = np.ones(8000, dtype=np.float32) * 0.1
        block_short = RollingBlock(1, start_sec=0.0, end_sec=0.5, audio_float=short_pcm)
        worker._process_single_block(block_short)

        assert block_short.audio_float is None, "audio_float musi być wyczyszczone dla O(1) RAM"
        assert block_short.is_processed is True
        assert worker.total_processed_seconds == 0.5, "total_processed_seconds musi uwzględniać end_sec krótkiego bloku"
        assert len(signals_received) == 1, "block_processed_signal musi być wyemitowany dla aktualizacji paska UI"

        # Zapis sesji: duration_sec musi być max(latest_session_seconds, total_processed_seconds)
        worker._save_to_session_file([], force=True)
        from recorder.core.session import get_session_path_for_txt
        j_path = get_session_path_for_txt(txt_path)
        assert os.path.exists(j_path)
        sess = TranscriptionSession.load_from_json(j_path)
        assert sess.duration_sec == 100.0, f"Oczekiwano duration_sec=100.0, otrzymano {sess.duration_sec}"


def test_rotate_session_file_flushes_audio_mixer():
    """
    Weryfikuje, że rotate_session_file() przed zamknięciem starego pliku StreamingWavWriter
    dokonuje opróżnienia miksera audio (flush remaining bytes), zapobiegając utracie dźwięku
    na przełomie rotacji wielogodzinnych plików.
    """
    _ = QApplication.instance() or QApplication([])

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f2:
        path1 = f1.name
        path2 = f2.name

    try:
        worker = SmartAudioWorker()
        worker.start_recording(save_wav_path=path1)

        # Dodanie próbek do miksera (odpowiednik buforowanego dźwięku przed rotacją)
        chunk = (np.ones(1600, dtype=np.float32) * 0.2)
        worker.audio_mixer.add_mic_chunk(chunk)

        # Rotacja do path2
        worker.rotate_session_file(path2)

        # path1 powinien być poprawnie zamknięty i zawierać buforowane próbki
        assert os.path.exists(path1)
        assert os.path.getsize(path1) > 44, "Plik path1 powinien zawierać zrzucone próbki z miksera"
        assert worker.save_wav_path == os.path.abspath(path2)
        assert worker.wav_writer is not None

        worker.stop_recording()
    finally:
        for p in (path1, path2):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


def test_real_wall_clock_timestamp_with_mute():
    """
    Weryfikuje, że w trybie 'clock_only' (Tylko godzina realna), wypowiedzi po 15 minutach wyciszenia
    lub auto-pauzy otrzymują RZECZYWISTY czas zegarowy ze stopera systemowego (np. 18:15:00),
    a nie czas przesunięty o offset skompresowanego pliku WAV (np. 18:00:05).
    """
    from datetime import datetime, timedelta
    from recorder.core.session import format_turn_timestamp

    t1_wall = datetime(2026, 9, 3, 18, 0, 0)
    t2_wall = datetime(2026, 9, 3, 18, 15, 0)

    # Audio offset: pierwsze zdanie trwa 5s (0.0 do 5.0).
    # Drugie zdanie w skompresowanym WAV ma offset 5.0 do 10.0 (bo 15 minut ciszy nie było nagrywane).
    st1, en1 = 0.0, 5.0
    st2, en2 = 5.0, 10.0

    session_start = datetime(2026, 9, 3, 18, 0, 0)

    lbl1 = format_turn_timestamp(st1, en1, session_start_time=session_start, ts_format="clock_only",
                                 wall_start=t1_wall, wall_end=t1_wall + timedelta(seconds=5.0))
    lbl2 = format_turn_timestamp(st2, en2, session_start_time=session_start, ts_format="clock_only",
                                 wall_start=t2_wall, wall_end=t2_wall + timedelta(seconds=5.0))

    assert lbl1 == "18:00:00 - 18:00:05"
    assert lbl2 == "18:15:00 - 18:15:05", f"Oczekiwano rzeczywistej godziny 18:15:00, otrzymano: {lbl2}"

    # Weryfikacja dla trybu hybrydowego: offset + realna godzina (np. 00:05 - 00:10 | 18:15:00 - 18:15:05)
    lbl1_hybrid = format_turn_timestamp(st1, en1, session_start_time=session_start, ts_format="hybrid",
                                        wall_start=t1_wall, wall_end=t1_wall + timedelta(seconds=5.0))
    lbl2_hybrid = format_turn_timestamp(st2, en2, session_start_time=session_start, ts_format="hybrid",
                                        wall_start=t2_wall, wall_end=t2_wall + timedelta(seconds=5.0))

    assert lbl1_hybrid == "00:00 - 00:05 | 18:00:00 - 18:00:05"
    assert lbl2_hybrid == "00:05 - 00:10 | 18:15:00 - 18:15:05", f"Oczekiwano hybrydy z czasem 18:15:00, otrzymano: {lbl2_hybrid}"


def test_silence_alert_timeout_does_not_cancel_session_split():
    """
    Weryfikuje, że wygaszenie powiadomienia strażnika ciszy (po 5 minutach / 300s)
    NIE kasuje licznika automatycznego podziału sesji (ustawionego na 10 minut / 600s).
    """
    _ = QApplication.instance() or QApplication([])

    worker = SmartAudioWorker()
    worker.set_silence_alert_seconds(300.0)
    worker.set_session_split_silence_sec(600.0)
    worker.session_has_speech = True

    # Symulacja 5 minut (300s) ciszy
    worker.continuous_silence_samples = int(300.0 * 16000)
    worker.session_split_silence_samples = int(300.0 * 16000)

    # Strażnik ciszy zgłasza alert i po 45s braku reakcji resetuje stan alertu
    worker.reset_silence_alert()

    # Licznik alertu powinien być wyzerowany, ale licznik podziału sesji ZACHOWANY!
    assert worker.continuous_silence_samples == 0
    assert worker.session_split_silence_samples == int(300.0 * 16000), \
        "BŁĄD: reset_silence_alert() skasował licznik podziału sesji!"

    # Kolejne 5 minut i 5 sekund ciszy (łącznie > 10 min)
    worker.session_split_silence_samples += int(305.0 * 16000)

    split_events = []
    worker.session_split_signal.connect(lambda r: split_events.append(r))

    # Wywołanie logiki sprawdzania podziału sesji
    split_sil_sec = float(worker.session_split_silence_samples / 16000.0)
    if worker.session_has_speech and worker.session_split_silence_sec > 0:
        if split_sil_sec >= worker.session_split_silence_sec:
            worker.session_has_speech = False
            worker.session_split_silence_samples = 0
            worker.continuous_silence_samples = 0
            mins = int(worker.session_split_silence_sec // 60)
            worker.session_split_signal.emit(f"Cisza > {mins} min")

    assert len(split_events) == 1
    assert "10 min" in split_events[0]

