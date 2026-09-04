"""
Testy jednostkowe modułu logowania, przekierowania strumieni i bezpiecznej sanityzacji ustawień.
"""

import os
import sys
import json
import logging
import tempfile
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from recorder.config import LOGS_DIR, APP_VERSION
from recorder.core.logger import (
    setup_app_logging,
    shutdown_app_logging,
    sanitize_settings,
    sanitize_value,
    log_system_diagnostics,
    get_log_file_path,
    StdStreamLogger
)


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def test_settings_sanitization_masks_all_secrets():
    print("[TEST] Weryfikacja maskowania danych poufnych w ustawieniach...")
    raw = {
        "hf_token": "hf_mock_test_token_1234567890abcdef",
        "supabase_key": "sb_secret_mock_test_key_1234567890",
        "supabase_url": "https://example-project.supabase.co",
        "generic_webhook_url": "https://discord.com/api/webhooks/123456789/secret-webhook-token",
        "secret_password": "SuperSecretPassword123!",
        "api_key": "sk-proj-1234567890abcdef",
        "empty_token": "",
        "none_val": None,
        # Zagnieżdżona lista słowników i tokenów
        "api_endpoints": [
            {"name": "production", "token": "hf_prod1234567890abcdefghijklmn"},
            {"name": "staging", "secret_key": "my-secret-token-key-123"}
        ],
        "trusted_webhooks": [
            "https://user:mypassword@example.com/webhook",
            "https://normal.com/endpoint"
        ],
        # Pola jawne / bezpieczne:
        "whisper_beam_size": 5,
        "device_name": "Biuro-Stanowisko-1",
        "vad_speech_threshold": 0.42,
        "record_source_mode": "hybrid_dual",
        "auto_check_updates_startup": True
    }

    sanitized = sanitize_settings(raw)

    # 1. Sprawdzenie, czy żaden sekret nie wyciekł w całości
    assert "hf_mock_test_token_1234567890abcdef" not in str(sanitized)
    assert "sb_secret_mock_test_key_1234567890" not in str(sanitized)
    assert "SuperSecretPassword123!" not in str(sanitized)
    assert "sk-proj-1234567890abcdef" not in str(sanitized)
    assert "secret-webhook-token" not in str(sanitized)
    assert "hf_prod1234567890abcdefghijklmn" not in str(sanitized)
    assert "my-secret-token-key-123" not in str(sanitized)
    assert "mypassword" not in str(sanitized)

    # 2. Sprawdzenie, czy tokeny zostały bezpiecznie zamaskowane z zachowaniem prefiksu
    assert sanitized["hf_token"].startswith("hf_m")
    assert "masked" in sanitized["hf_token"]
    assert sanitized["supabase_key"].startswith("sb_s")
    assert "masked" in sanitized["supabase_key"]
    assert "***REDACTED***" in sanitized["secret_password"]
    assert "***REDACTED***" in sanitized["generic_webhook_url"]
    assert "***:***@" in sanitized["trusted_webhooks"][0]
    assert "masked" in sanitized["api_endpoints"][0]["token"]

    # 3. Sprawdzenie, czy jawne parametry pozostały nienaruszone (niezbędne do diagnostyki)
    assert sanitized["whisper_beam_size"] == 5
    assert sanitized["device_name"] == "Biuro-Stanowisko-1"
    assert sanitized["vad_speech_threshold"] == 0.42
    assert sanitized["record_source_mode"] == "hybrid_dual"
    assert sanitized["auto_check_updates_startup"] is True
    print("  -> Dane poufne są w 100% bezpiecznie maskowane!")


def test_sanitize_value_corner_cases():
    print("[TEST] Przypadki brzegowe sanitize_value...")
    assert sanitize_value("normal_field", "Zwykly tekst") == "Zwykly tekst"
    assert sanitize_value("normal_field", 12345) == 12345
    assert sanitize_value("normal_field", None) is None
    assert sanitize_value("token", "") == ""
    assert sanitize_value("auth_key", "short") == "***REDACTED***"
    assert sanitize_value("password", "Secret123456789") == "***REDACTED***"
    assert sanitize_value("token", "1234567890") == "1234***890 (masked, len 10)"
    assert "***:***@" in sanitize_value("db_url", "postgresql://admin:secretPass@localhost:5432/db")
    print("  -> Przypadki brzegowe sanitize_value zdane!")


def test_setup_app_logging_and_file_creation():
    print("[TEST] Tworzenie pliku logu i rejestracja zdarzeń...")
    tmpdir = tempfile.mkdtemp()
    try:
        test_logger = setup_app_logging(log_dir=tmpdir, log_filename="test_app.log", force=True)
        test_log_file = os.path.join(tmpdir, "test_app.log")

        assert os.path.exists(test_log_file)
        test_logger.info("Komunikat testowy INFO")
        test_logger.warning("Komunikat ostrzegawczy WARNING")

        # Wymuszenie zapisu
        for h in test_logger.handlers:
            h.flush()

        with open(test_log_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "Komunikat testowy INFO" in content
        assert "Komunikat ostrzegawczy WARNING" in content
        assert content.count("Komunikat testowy INFO") == 1, "Wpisy logu nie powinny się dublować!"
        assert content.count("Komunikat ostrzegawczy WARNING") == 1, "Wpisy logu nie powinny się dublować!"
        print("  -> Zapis do pliku logu działa prawidłowo (brak duplikatów)!")
    finally:
        shutdown_app_logging()
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def test_stdout_redirection_to_log():
    print("[TEST] Przekierowanie sys.stdout/stderr do loggera (brak okna konsoli)...")
    tmpdir = tempfile.mkdtemp()
    try:
        test_logger = setup_app_logging(log_dir=tmpdir, log_filename="test_stream.log", force=True)
        test_log_file = os.path.join(tmpdir, "test_stream.log")

        unique_marker = "TEST_UNIKALNY_ZNACZNIK_PRINT_12345"
        print(unique_marker)
        sys.stdout.flush()

        for h in test_logger.handlers:
            h.flush()

        with open(test_log_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert unique_marker in content
        assert content.count(unique_marker) == 1, "Przechwycony print nie powinien się dublować!"
        print("  -> Przekierowanie print() do pliku logu działa prawidłowo (dokładnie 1 wpis)!")
    finally:
        shutdown_app_logging()
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def test_system_diagnostics_logging():
    print("[TEST] Zrzut raportu diagnostycznego do logu...")
    tmpdir = tempfile.mkdtemp()
    try:
        test_logger = setup_app_logging(log_dir=tmpdir, log_filename="test_diag.log", force=True)
        test_log_file = os.path.join(tmpdir, "test_diag.log")

        log_system_diagnostics(test_logger)

        for h in test_logger.handlers:
            h.flush()

        with open(test_log_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "START APLIKACJI" in content
        assert APP_VERSION in content
        assert "System:" in content
        assert "Python:" in content
        assert "Aktywna konfiguracja użytkownika" in content
        # Upewniamy się, że żaden klucz prywatny nie wyciekł do logu
        assert "sb_secret_" not in content
        print("  -> Raport diagnostyczny został pomyślnie i bezpiecznie wygenerowany!")
    finally:
        shutdown_app_logging()
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def test_build_spec_and_script_configured_for_noconsole():
    print("[TEST] Weryfikacja wyłączenia okna konsoli w plikach budowania EXE...")
    spec_path = os.path.join(ROOT_DIR, "InteligentnyDyktafonAI.spec")
    build_script_path = os.path.join(ROOT_DIR, "scripts", "build_exe.py")

    assert os.path.exists(spec_path), "Brak pliku spec!"
    assert os.path.exists(build_script_path), "Brak skryptu build_exe.py!"

    with open(spec_path, "r", encoding="utf-8") as f:
        spec_content = f.read()
    assert "console=False" in spec_content, "Plik .spec powinien mieć ustawione console=False!"

    with open(build_script_path, "r", encoding="utf-8") as f:
        build_content = f.read()
    assert "--noconsole" in build_content, "Skrypt build_exe.py powinien zawierać flagę --noconsole!"
    print("  -> Konfiguracja PyInstallera wyłącza konsolę (tryb GUI noconsole)!")


def test_std_stream_logger_features_and_restoration():
    print("[TEST] Weryfikacja właściwości StdStreamLogger i czystego resetowania strumieni...")
    import io
    dummy_logger = logging.getLogger("test.dummy")
    stream = StdStreamLogger(dummy_logger, logging.INFO, original_stream=None)
    
    # 1. Właściwość encoding
    assert stream.encoding == "utf-8"
    assert stream.isatty() is False

    # 2. fileno rzuca UnsupportedOperation dla wirtualnego strumienia
    try:
        stream.fileno()
        assert False, "fileno() powinno rzucić UnsupportedOperation!"
    except io.UnsupportedOperation:
        pass

    # 3. Czyszczenie bufora przy flush ze spacjami
    stream.write("    ")
    stream.flush()
    assert stream._buffer == ""

    # 4. Weryfikacja przywracania sys.stdout/stderr w shutdown_app_logging
    orig_out = sys.stdout
    orig_err = sys.stderr
    tmpdir = tempfile.mkdtemp()
    try:
        setup_app_logging(log_dir=tmpdir, force=True)
        assert isinstance(sys.stdout, StdStreamLogger)
        shutdown_app_logging()
        assert not isinstance(sys.stdout, StdStreamLogger)
    finally:
        shutdown_app_logging()
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    print("  -> Właściwości strumieni i bezpieczne przywracanie działają prawidłowo!")


def test_no_duplicate_log_entries_across_child_loggers():
    print("[TEST] Weryfikacja braku duplikacji wpisów z pod-loggerów (recorder.*)...")
    tmpdir = tempfile.mkdtemp()
    try:
        setup_app_logging(log_dir=tmpdir, log_filename="test_dedup.log", force=True)
        log_file = os.path.join(tmpdir, "test_dedup.log")

        # 1. Główny logger "recorder"
        rec_logger = logging.getLogger("recorder")
        rec_logger.info("Unikalny_komunikat_glowny_123")

        # 2. Pod-logger potomny "recorder.core.cloud_sync"
        child_logger = logging.getLogger("recorder.core.cloud_sync")
        child_logger.info("Unikalny_komunikat_potomny_456")

        # 3. Zewnętrzny logger biblioteczny (propaguje do root)
        ext_logger = logging.getLogger("urllib3.connectionpool")
        ext_logger.warning("Unikalny_komunikat_zewnetrzny_789")

        for h in list(rec_logger.handlers) + list(logging.getLogger().handlers):
            try:
                h.flush()
            except Exception:
                pass

        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert content.count("Unikalny_komunikat_glowny_123") == 1, "Główny logger zduplikował wpis!"
        assert content.count("Unikalny_komunikat_potomny_456") == 1, "Pod-logger zduplikował wpis!"
        assert content.count("Unikalny_komunikat_zewnetrzny_789") == 1, "Zewnętrzny logger zduplikował wpis!"
        print("  -> Brak jakichkolwiek duplikatów dla loggerów głównych, potomnych i zewnętrznych!")
    finally:
        shutdown_app_logging()
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    test_settings_sanitization_masks_all_secrets()
    test_sanitize_value_corner_cases()
    test_setup_app_logging_and_file_creation()
    test_stdout_redirection_to_log()
    test_system_diagnostics_logging()
    test_build_spec_and_script_configured_for_noconsole()
    test_std_stream_logger_features_and_restoration()
    test_no_duplicate_log_entries_across_child_loggers()
    print("\n[OK] Wszystkie testy modulu logowania i diagnostyki zakonczone sukcesem!")
