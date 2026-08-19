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
    print("✅ Test RollingBlock: Sukces!")


if __name__ == "__main__":
    test_rolling_block_creation()
