"""
Moduł synchronizacji chmurowej dla recorder67 (Agnostic Cloud Sync).
Odpowiada za asynchroniczne wysyłanie transkrypcji i metadanych spotkań
do bazy Supabase (REST API) lub zewnętrznego Webhooka (klienci B2B / n8n / CRM).
Obsługuje automatyczną kolejkę offline (odporność na brak internetu).
"""


import os
import json
import time
import uuid
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
import urllib.request
import urllib.parse
import urllib.error

from PyQt6.QtCore import QObject, pyqtSignal

from recorder.config import get_cloud_sync_config, SYNC_QUEUE_DIR

logger = logging.getLogger(__name__)


class CloudSyncSignals(QObject):
    sync_started = pyqtSignal(str)              # meeting_id
    sync_finished = pyqtSignal(str, bool, str)  # meeting_id, success, message
    offline_queued = pyqtSignal(str, str)       # meeting_id, reason


class CloudSyncManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CloudSyncManager, cls).__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        self.signals = CloudSyncSignals()
        self.config = get_cloud_sync_config()
        self._is_processing_queue = False
        os.makedirs(SYNC_QUEUE_DIR, exist_ok=True)

    def reload_config(self):
        """Przeładowuje konfigurację z pliku .env/środowiska."""
        self.config = get_cloud_sync_config()

    def sync_meeting_async(
        self,
        title: str,
        transcript_text: str,
        segments: List[Dict[str, Any]],
        duration_seconds: float = 0.0,
        audio_path: Optional[str] = None,
        context_type: str = "general",
        context_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
    ) -> str:
        """
        Asynchronicznie wysyła spotkanie do chmury (nie blokuje wątku UI).
        Zwraca wygenerowany meeting_id.
        """
        self.reload_config()
        if not meeting_id:
            meeting_id = str(uuid.uuid4())

        payload = self._build_payload(
            meeting_id=meeting_id,
            title=title,
            transcript_text=transcript_text,
            segments=segments,
            duration_seconds=duration_seconds,
            audio_path=audio_path,
            context_type=context_type,
            context_id=context_id,
        )

        threading.Thread(
            target=self._sync_worker,
            args=(payload,),
            daemon=True
        ).start()

        return meeting_id

    def _build_payload(
        self,
        meeting_id: str,
        title: str,
        transcript_text: str,
        segments: List[Dict[str, Any]],
        duration_seconds: float,
        audio_path: Optional[str],
        context_type: str,
        context_id: Optional[str],
    ) -> Dict[str, Any]:
        """Tworzy znormalizowany, agnostyczny obiekt spotkania."""
        now_iso = datetime.utcnow().isoformat() + "Z"
        
        # Zlicz unikalnych mówców
        unique_speakers = set()
        cleaned_segments = []
        for s in segments:
            spk = s.get("speaker", "Mówca")
            unique_speakers.add(spk)
            cleaned_segments.append({
                "speaker": spk,
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": str(s.get("text", "")).strip()
            })

        return {
            "id": meeting_id,
            "title": title or f"Spotkanie {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "organization_id": self.config.get("organization_id", "default_org"),
            "device_name": self.config.get("device_name", "Biuro-Stanowisko"),
            "created_at": now_iso,
            "duration_seconds": round(duration_seconds, 2),
            "speaker_count": len(unique_speakers),
            "transcript_text": transcript_text.strip(),
            "segments": cleaned_segments,
            "context_type": context_type,
            "context_id": context_id,
            "audio_path": audio_path if audio_path and os.path.exists(audio_path) else None,
            "source": "recorder67_ambient",
        }

    def _sync_worker(self, payload: Dict[str, Any]):
        meeting_id = payload["id"]
        sync_target = self.config.get("sync_target", "emanager").lower()

        if sync_target == "none":
            logger.info("Synchronizacja chmurowa wyłączona (SYNC_TARGET=none).")
            self.signals.sync_finished.emit(meeting_id, True, "Synchronizacja chmurowa wyłączona.")
            return

        self.signals.sync_started.emit(meeting_id)

        try:
            if sync_target == "emanager":
                success, msg = self._send_to_supabase_emanager(payload)
            elif sync_target == "generic_webhook":
                success, msg = self._send_to_generic_webhook(payload)
            else:
                success, msg = False, f"Nieznany cel synchronizacji: {sync_target}"

            if success:
                logger.info(f"Pomyślnie zsynchronizowano spotkanie {meeting_id}: {msg}")
                self.signals.sync_finished.emit(meeting_id, True, msg)
            else:
                logger.warning(f"Błąd synchronizacji {meeting_id}: {msg}. Zapisywanie do kolejki offline.")
                self._save_to_offline_queue(payload, msg)

        except Exception as e:
            err_msg = f"Nieoczekiwany błąd podczas wysyłki: {e}"
            logger.error(err_msg, exc_info=True)
            self._save_to_offline_queue(payload, err_msg)

    def _send_to_supabase_emanager(self, payload: Dict[str, Any]) -> tuple[bool, str]:
        """Wysyła spotkanie bezpośrednio do bazy Supabase w EMANAGER.PRO."""
        url = self.config.get("supabase_url", "").rstrip("/")
        key = self.config.get("supabase_key", "")

        if not url or not key:
            return False, "Brak skonfigurowanego SUPABASE_URL lub SUPABASE_KEY w .env"

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }

        # 1. Opcjonalny upload pliku audio do Storage (bucket: voice-notes)
        audio_url = None
        audio_path = payload.get("audio_path")
        if self.config.get("upload_audio") and audio_path and os.path.exists(audio_path):
            audio_url = self._upload_audio_to_supabase(url, key, payload["id"], audio_path)

        # 2. Rekord spotkania
        meeting_record = {
            "id": payload["id"],
            "title": payload["title"],
            "duration_seconds": int(payload["duration_seconds"]),
            "audio_url": audio_url,
            "created_at": payload["created_at"],
            "status": "completed",
            "context_type": payload.get("context_type", "general"),
            "context_id": payload.get("context_id"),
            "device_name": payload.get("device_name"),
            "speaker_count": payload.get("speaker_count", 1),
            "transcript": payload.get("transcript_text", ""),
        }

        # Próba zapisu do dedykowanej tabeli 'meetings'
        meetings_endpoint = f"{url}/rest/v1/meetings"
        req = urllib.request.Request(
            meetings_endpoint,
            data=json.dumps(meeting_record).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201, 204):
                    self._save_segments_to_supabase(url, headers, payload["id"], payload.get("segments", []))
                    return True, "Zapisano w tabeli spotkań (meetings)"
        except urllib.error.HTTPError as http_err:
            if http_err.code == 409:
                # Rekord o tym ID już istnieje w bazie -> wykonujemy aktualizację (PATCH)
                logger.info(f"Spotkanie {payload['id']} już istnieje w bazie (409 Conflict), aktualizuję rekord metodą PATCH...")
                patch_req = urllib.request.Request(
                    f"{meetings_endpoint}?id=eq.{payload['id']}",
                    data=json.dumps({
                        "title": payload["title"],
                        "duration_seconds": int(payload["duration_seconds"]),
                        "transcript": payload.get("transcript_text", ""),
                        "speaker_count": payload.get("speaker_count", 1),
                        "status": "completed",
                        "audio_url": audio_url or meeting_record.get("audio_url")
                    }).encode("utf-8"),
                    headers=headers,
                    method="PATCH"
                )
                try:
                    with urllib.request.urlopen(patch_req, timeout=15) as patch_resp:
                        if patch_resp.status in (200, 204):
                            self._save_segments_to_supabase(url, headers, payload["id"], payload.get("segments", []))
                            return True, "Zaktualizowano spotkanie w tabeli meetings"
                except Exception as patch_err:
                    return False, f"Błąd aktualizacji PATCH spotkania: {patch_err}"

            # Jeśli tabela 'meetings' nie istnieje, wykonujemy fallback do 'voice_notes'
            logger.info(f"Tabela 'meetings' zwróciła {http_err.code}, próba zapisu do tabeli 'voice_notes'...")
            fallback_success, fallback_msg = self._fallback_save_to_voice_notes(url, headers, payload, audio_url)
            if fallback_success:
                return True, fallback_msg
            return False, f"Błąd HTTP {http_err.code}: {http_err.reason}"
        except urllib.error.URLError as url_err:
            return False, f"Błąd połączenia sieciowego: {url_err.reason}"

        return True, "Zsynchronizowano pomyślnie."

    def _save_segments_to_supabase(self, base_url: str, headers: dict, meeting_id: str, segments: List[dict]):
        """Zapisuje listę segmentów wypowiedzi do meeting_segments (najpierw czyści stare, by uniknąć duplikatów)."""
        if not segments:
            return

        # 1. Usuń stare segmenty dla tego meeting_id (jeśli to re-sync po edycji mówców)
        del_req = urllib.request.Request(
            f"{base_url}/rest/v1/meeting_segments?meeting_id=eq.{meeting_id}",
            headers=headers,
            method="DELETE"
        )
        try:
            with urllib.request.urlopen(del_req, timeout=10):
                pass
        except Exception as e:
            logger.debug(f"DELETE meeting_segments: {e}")

        # 2. Wstaw nowe segmenty
        rows = []
        for s in segments:
            rows.append({
                "meeting_id": meeting_id,
                "speaker_name": s["speaker"],
                "start_time": s["start"],
                "end_time": s["end"],
                "text": s["text"]
            })

        req = urllib.request.Request(
            f"{base_url}/rest/v1/meeting_segments",
            data=json.dumps(rows).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as e:
            logger.warning(f"Nie udało się zapisać segmentów do meeting_segments: {e}")


    def _fallback_save_to_voice_notes(self, base_url: str, headers: dict, payload: dict, audio_url: Optional[str]) -> tuple[bool, str]:
        """Zapisuje rekord do istniejącej tabeli 'voice_notes' jako kompatybilny fallback."""
        record = {
            "id": payload["id"],
            "duration_seconds": int(payload["duration_seconds"]),
            "audio_url": audio_url,
            "created_at": payload["created_at"],
            "context_type": payload.get("context_type", "general"),
            "context_label": payload["title"],
            "transcript": payload["transcript_text"],
            "source": "ambient_recorder",
            "tags": ["ambient_meeting", f"speakers_{payload.get('speaker_count', 1)}"]
        }

        req = urllib.request.Request(
            f"{base_url}/rest/v1/voice_notes",
            data=json.dumps(record).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201, 204):
                    return True, "Zapisano w module Notatek Głosowych (voice_notes)"
                return False, f"Status: {resp.status}"
        except Exception as e:
            return False, f"Błąd zapisu do voice_notes: {e}"

    def _upload_audio_to_supabase(self, base_url: str, key: str, meeting_id: str, audio_path: str) -> Optional[str]:
        """Wgrywa plik audio do bucketu Storage 'voice-notes'."""
        try:
            ext = os.path.splitext(audio_path)[1].lstrip(".").lower() or "wav"
            storage_path = f"meetings/{meeting_id}.{ext}"
            upload_url = f"{base_url}/storage/v1/object/voice-notes/{storage_path}"

            with open(audio_path, "rb") as f:
                data = f.read()

            headers = {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "audio/wav" if ext == "wav" else "audio/mpeg",
                "x-upsert": "true"
            }

            req = urllib.request.Request(upload_url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in (200, 201):
                    return storage_path
        except Exception as e:
            logger.warning(f"Nie udało się wgrać pliku audio do Storage: {e}")
        return None

    def _send_to_generic_webhook(self, payload: Dict[str, Any]) -> tuple[bool, str]:
        """Wysyła znormalizowany JSON do webhooka (n8n / custom CRM)."""
        webhook_url = self.config.get("generic_webhook_url")
        if not webhook_url:
            return False, "Brak GENERIC_WEBHOOK_URL w konfiguracji."

        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201, 202, 204):
                return True, f"Wysłano do webhooka (Status {resp.status})"
            return False, f"Webhook zwrócił status {resp.status}"

    def _save_to_offline_queue(self, payload: Dict[str, Any], reason: str):
        """Zapisuje spotkanie do pliku JSON w kolejce offline."""
        meeting_id = payload["id"]
        queue_file = os.path.join(SYNC_QUEUE_DIR, f"{meeting_id}.json")
        try:
            with open(queue_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(f"Zapisano spotkanie w kolejce offline: {queue_file}")
            self.signals.offline_queued.emit(meeting_id, f"Zapisano lokalnie w kolejce offline ({reason})")
        except Exception as e:
            logger.error(f"Nie udało się zapisać do kolejki offline: {e}")

    def process_offline_queue_async(self):
        """Przetwarza oczekujące pliki w kolejce offline w osobnym wątku."""
        if self._is_processing_queue:
            return
        threading.Thread(target=self._process_offline_queue_worker, daemon=True).start()

    def _process_offline_queue_worker(self):
        self._is_processing_queue = True
        try:
            files = [f for f in os.listdir(SYNC_QUEUE_DIR) if f.endswith(".json")]
            if not files:
                return

            logger.info(f"Przetwarzanie kolejki offline: {len(files)} plików.")
            for filename in files:
                file_path = os.path.join(SYNC_QUEUE_DIR, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)

                    sync_target = self.config.get("sync_target", "emanager").lower()
                    if sync_target == "emanager":
                        success, _ = self._send_to_supabase_emanager(payload)
                    elif sync_target == "generic_webhook":
                        success, _ = self._send_to_generic_webhook(payload)
                    else:
                        success = False

                    if success:
                        os.remove(file_path)
                        logger.info(f"Usunięto przetworzone spotkanie z kolejki offline: {filename}")
                except Exception as e:
                    logger.warning(f"Błąd podczas ponownej próby wysyłki {filename}: {e}")
        finally:
            self._is_processing_queue = False
