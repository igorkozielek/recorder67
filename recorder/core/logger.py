"""
Moduł centralnego logowania i diagnostyki dla Inteligentnego Dyktafonu AI.
Zapewnia:
- Zapis logów do rotującego pliku (RotatingFileHandler) w katalogu logs/
- Bezpieczne przekierowanie sys.stdout i sys.stderr do pliku logu (kluczowe dla exe z --noconsole)
- Przechwytywanie nieobsłużonych wyjątków (sys.excepthook)
- Bezpieczny zrzut parametrów konfiguracyjnych i diagnostyki sprzętowej
  z automatyczną maskowaniem i cenzurą danych wrażliwych (klucze API, tokeny, sekrety).
"""

import os
import io
import sys
import json
import logging
import platform
import traceback
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any

from recorder.config import LOGS_DIR, APP_VERSION, GITHUB_REPO, load_user_settings

# Flagi stanu
_LOGGING_INITIALIZED = False
_ACTIVE_LOG_FILE: Optional[str] = None
_DIAGNOSTICS_LOGGED = False
_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr
_ORIGINAL_EXCEPTHOOK = sys.excepthook
_FILE_HANDLERS = []


class StdStreamLogger:
    """
    Plikopodobny wrapper strumienia (sys.stdout / sys.stderr) przekierowujący
    wyjście do loggera Pythona oraz zachowujący wyjście na oryginalnej konsoli (jeśli istnieje).
    Dzięki temu w wersji .exe z flagą --noconsole (gdzie sys.stdout to None) aplikacja nie rzuca
    AttributeError: 'NoneType' object has no attribute 'write'.
    """
    def __init__(self, logger: logging.Logger, log_level: int, original_stream=None):
        self.logger = logger
        self.log_level = log_level
        self.original_stream = original_stream
        self._buffer = ""

    def write(self, text: str):
        if not text:
            return

        # Przekaż do oryginalnego strumienia, jeśli jest dostępny (np. w trybie deweloperskim)
        if self.original_stream is not None:
            try:
                self.original_stream.write(text)
                self.original_stream.flush()
            except Exception:
                pass

        # Buforowanie linii do zapisu w loggerze
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line.strip():
                self.logger.log(self.log_level, line)

    def flush(self):
        if self.original_stream is not None:
            try:
                self.original_stream.flush()
            except Exception:
                pass
        buf = self._buffer.strip()
        self._buffer = ""
        if buf:
            self.logger.log(self.log_level, buf)

    def isatty(self) -> bool:
        if self.original_stream is not None and hasattr(self.original_stream, "isatty"):
            try:
                return self.original_stream.isatty()
            except Exception:
                pass
        return False

    @property
    def encoding(self) -> str:
        if self.original_stream is not None and hasattr(self.original_stream, "encoding"):
            return getattr(self.original_stream, "encoding", "utf-8") or "utf-8"
        return "utf-8"

    def fileno(self) -> int:
        if self.original_stream is not None and hasattr(self.original_stream, "fileno"):
            try:
                return self.original_stream.fileno()
            except Exception:
                pass
        raise io.UnsupportedOperation("fileno")


def sanitize_value(key: str, val: Any) -> Any:
    """
    Maskuje wrażliwe dane (klucze API, tokeny, hasła) w ustawieniach.
    Zachowuje bezpieczne prefiksy/sufiksy dla ułatwienia weryfikacji przez użytkownika.
    """
    if val is None or not isinstance(val, str):
        return val

    key_lower = key.lower()
    val_str = str(val).strip()
    if not val_str:
        return ""

    # Słowa kluczowe wskazujące na pole poufne
    sensitive_keywords = (
        "token", "key", "secret", "password", "passwd", "pwd",
        "auth", "credential", "private", "webhook"
    )

    is_sensitive = any(kw in key_lower for kw in sensitive_keywords)

    # Sprawdzenie również formatu samego stringa (np. hf_..., sb_secret_..., Bearer ..., eyJ..., URL z @)
    if not is_sensitive:
        val_lower = val_str.lower()
        if (
            val_lower.startswith("hf_")
            or val_lower.startswith("sb_secret_")
            or val_lower.startswith("bearer ")
            or val_lower.startswith("eyj")
            or ("@" in val_str and "://" in val_str)
        ):
            is_sensitive = True

    # Hasła i sekrety ściśle poufne - zawsze maskuj w 100% bez ujawniania liter
    strict_redact = ("password", "passwd", "pwd", "secret")
    if any(kw in key_lower for kw in strict_redact):
        return "***REDACTED***"

    if is_sensitive:
        # Jeśli to adres URL lub connection string (np. generic_webhook_url, db url)
        if "://" in val_str:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(val_str)
                netloc = parsed.netloc
                if "@" in netloc:
                    netloc = "***:***@" + netloc.split("@", 1)[1]
                parts = [p for p in parsed.path.split("/") if p]
                base_p = "/" + parts[0] if parts else ""
                return f"{parsed.scheme}://{netloc}{base_p}/***REDACTED***"
            except Exception:
                pass

        # Standardowe maskowanie tokena / klucza API
        if len(val_str) <= 8:
            return "***REDACTED***"
        else:
            return f"{val_str[:4]}***{val_str[-3:]} (masked, len {len(val_str)})"

    return val


def sanitize_settings(settings: Any) -> Any:
    """
    Tworzy bezpieczną kopię słownika ustawień z zamaskowanymi tokenami i kluczami API.
    Bezpiecznie obsługuje zagnieżdżone słowniki i listy.
    """
    if not isinstance(settings, dict):
        return settings

    sanitized = {}
    for k, v in settings.items():
        if isinstance(v, dict):
            sanitized[k] = sanitize_settings(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_settings(item) if isinstance(item, dict)
                else sanitize_value(k, item)
                for item in v
            ]
        else:
            sanitized[k] = sanitize_value(k, v)
    return sanitized


def get_log_file_path() -> str:
    """Zwraca bezwzględną ścieżkę do aktywnego pliku dziennika zdarzeń."""
    global _ACTIVE_LOG_FILE
    if _ACTIVE_LOG_FILE:
        return _ACTIVE_LOG_FILE
    return os.path.join(LOGS_DIR, "app.log")


def shutdown_app_logging():
    """Zamyka pliki logów i odłącza handlery (umożliwia czyste usunięcie katalogów na Windowsie)."""
    global _LOGGING_INITIALIZED, _ACTIVE_LOG_FILE, _FILE_HANDLERS, _DIAGNOSTICS_LOGGED

    for h in list(_FILE_HANDLERS):
        try:
            h.flush()
            h.close()
        except Exception:
            pass

    logger = logging.getLogger("recorder")
    logger.propagate = True
    for h in list(logger.handlers):
        if isinstance(h, RotatingFileHandler):
            logger.removeHandler(h)

    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, RotatingFileHandler):
            root.removeHandler(h)

    if _ORIGINAL_STDOUT is not None:
        sys.stdout = _ORIGINAL_STDOUT
    if _ORIGINAL_STDERR is not None:
        sys.stderr = _ORIGINAL_STDERR
    if _ORIGINAL_EXCEPTHOOK is not None:
        sys.excepthook = _ORIGINAL_EXCEPTHOOK

    _FILE_HANDLERS.clear()
    _LOGGING_INITIALIZED = False
    _ACTIVE_LOG_FILE = None
    _DIAGNOSTICS_LOGGED = False


def setup_app_logging(
    log_dir: Optional[str] = None,
    log_filename: str = "app.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    level: int = logging.INFO,
    force: bool = False
) -> logging.Logger:
    """
    Inicjalizuje globalny system logowania aplikacji.
    - Tworzy rotujący plik dziennika logs/app.log
    - Bezpiecznie przekierowuje sys.stdout i sys.stderr
    - Instaluje globalny przechwytywacz błędów sys.excepthook
    """
    global _LOGGING_INITIALIZED, _ACTIVE_LOG_FILE, _FILE_HANDLERS

    if force:
        shutdown_app_logging()

    target_dir = log_dir or LOGS_DIR
    os.makedirs(target_dir, exist_ok=True)
    log_path = os.path.join(target_dir, log_filename)
    _ACTIVE_LOG_FILE = log_path

    logger = logging.getLogger("recorder")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not _LOGGING_INITIALIZED or force:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s:%(threadName)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # 1. Rotujący plik logu z kodowaniem UTF-8
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            errors="replace"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
            logger.addHandler(file_handler)
        _FILE_HANDLERS.append(file_handler)

        # Skonfiguruj także logger główny (root), by zbierać logi z zewnętrznych bibliotek
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)
        if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
            root_logger.addHandler(file_handler)

        # 2. Przekierowanie sys.stdout i sys.stderr do pliku dziennika
        if not isinstance(sys.stdout, StdStreamLogger):
            orig_stdout = sys.stdout
            orig_stderr = sys.stderr

            stdout_logger = logging.getLogger("recorder.stdout")
            stderr_logger = logging.getLogger("recorder.stderr")

            sys.stdout = StdStreamLogger(stdout_logger, logging.INFO, orig_stdout)
            sys.stderr = StdStreamLogger(stderr_logger, logging.ERROR, orig_stderr)

        # 3. Globalny przechwytywacz nieobsłużonych wyjątków
        def global_excepthook(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                if sys.__excepthook__:
                    sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            logger.critical(
                "Nieobsłużony krytyczny wyjątek w aplikacji:\n" +
                "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            )

        sys.excepthook = global_excepthook
        _LOGGING_INITIALIZED = True

    return logger


def log_system_diagnostics(logger: Optional[logging.Logger] = None, force: bool = False):
    """
    Zapisuje do pliku dziennika pełny raport diagnostyczny środowiska i bezpieczny zrzut ustawień.
    Domyślnie zapisuje się tylko raz w trakcie trwania procesu (zapobiega duplikatom przy wielokrotnym wywołaniu).
    """
    global _DIAGNOSTICS_LOGGED
    if _DIAGNOSTICS_LOGGED and not force:
        return

    log = logger or logging.getLogger("recorder")

    is_frozen = getattr(sys, "frozen", False)
    mode_desc = "Skompilowane EXE (PyInstaller)" if is_frozen else "Tryb deweloperski (Python)"

    log.info("=" * 70)
    log.info(f"START APLIKACJI: Inteligentny Dyktafon AI v{APP_VERSION} ({mode_desc})")
    log.info(f"Repozytorium:   {GITHUB_REPO}")
    log.info(f"System:         {platform.system()} {platform.release()} ({platform.version()})")
    log.info(f"Architektura:   {platform.machine()} / {platform.architecture()[0]}")
    log.info(f"Python:         {platform.python_version()} ({sys.executable})")
    log.info(f"Katalog pracy:  {os.getcwd()}")
    log.info(f"Plik logu:      {get_log_file_path()}")

    try:
        raw_settings = load_user_settings()
        sanitized = sanitize_settings(raw_settings)
        formatted_json = json.dumps(sanitized, indent=2, ensure_ascii=False)
        log.info("Aktywna konfiguracja użytkownika (dane wrażliwe zamaskowane):\n" + formatted_json)
    except Exception as e:
        log.warning(f"Nie udało się wczytać ustawień do diagnostyki: {e}")

    log.info("=" * 70)
    _DIAGNOSTICS_LOGGED = True


def open_logs_folder() -> bool:
    """
    Otwiera katalog z plikami dziennika w Eksploratorze Windows.
    """
    try:
        folder = LOGS_DIR
        os.makedirs(folder, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
            return True
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder])
            return True
    except Exception as e:
        print(f"[LOGGER] Błąd otwierania folderu logów: {e}")
        return False
