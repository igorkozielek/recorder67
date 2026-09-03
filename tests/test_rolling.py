import os
import sys
import numpy as np

# Ustawienie ścieżki do projektu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from recorder.core.rolling_transcriber import RollingBlock, RollingTranscriptionWorker


def test_rolling_block_creation():
    audio_sample = np.zeros(16000 * 2, dtype=np.float32)
    block = RollingBlock(block_index=1, start_sec=0.0, end_sec=2.0, audio_float=audio_sample)
    assert block.block_index == 1
    assert block.start_sec == 0.0
    assert block.end_sec == 2.0
    assert len(block.audio_float) == 32000
    print("[OK] Test RollingBlock: Sukces!")


def test_rolling_worker_long_session_scalability():
    """Test weryfikujący brak spadku wydajności (O(N^2)) przy 1500 blokach (sesja 4h+)."""
    import time
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication([])

    worker = RollingTranscriptionWorker()
    
    t0 = time.time()
    # Symulacja 1500 bloków mowy
    for i in range(1500):
        block = RollingBlock(
            block_index=i,
            start_sec=float(i * 10),
            end_sec=float((i + 1) * 10),
            audio_float=None,
            channel_source="mic" if i % 2 == 0 else "system"
        )
        block.turns = [{
            "speaker": "Mikrofon",
            "start": float(i * 10),
            "end": float((i + 1) * 10),
            "text": f"Testowa wypowiedź bloku numer {i}",
            "channel": block.channel_source
        }]
        transcript_words = [
            {"word": "Testowa", "start": float(i * 10), "end": float(i * 10 + 1)},
            {"word": "wypowiedź", "start": float(i * 10 + 1), "end": float(i * 10 + 2)}
        ]
        
        # Test wewnętrznej agregacji
        worker.processed_blocks.append(block)
        worker._all_words.extend(transcript_words)
        worker.all_turns.extend(block.turns)
        worker.total_processed_seconds = block.end_sec

    # Kompilacja całościowa dla 1500 bloków
    html, plain, turns = worker._compile_full_transcript()
    t_elapsed = time.time() - t0
    
    assert len(turns) == 1500
    assert len(worker.get_all_words()) == 3000
    assert len(plain) > 10000
    assert len(html) > 10000
    assert t_elapsed < 2.0, f"Kompilacja 1500 bloków trwała zbyt długo: {t_elapsed:.2f}s"
    print(f"[OK] Test skalowalnosci 1500 blokow: wykonano w {t_elapsed:.3f}s (brak O(N^2)!)")


if __name__ == "__main__":
    test_rolling_block_creation()
    test_rolling_worker_long_session_scalability()
