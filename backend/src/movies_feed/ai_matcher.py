import json
import logging
import os
import time
from datetime import datetime
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


class GeminiModelCapabilityError(ValueError):
    """Raised when the configured Gemini model cannot run generateContent."""


class AiMatcher:
    """
    AI-powered batch parsing and validation helper for media scanner.
    Uses Gemini REST API with structured outputs to parse complex torrent titles
    and validate candidate OMDb matches in batches.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        inter_request_delay: Optional[float] = None,
        forbidden_cooldown_seconds: float = 300.0,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        chosen_model = model or os.environ.get("GEMINI_MODEL", GEMINI_MODEL)
        self.model = chosen_model

        # Determine inter-request delay to comply with model RPM limits
        if inter_request_delay is not None:
            self.inter_request_delay = inter_request_delay
        elif os.environ.get("GEMINI_INTER_REQUEST_DELAY"):
            self.inter_request_delay = float(os.environ["GEMINI_INTER_REQUEST_DELAY"])
        else:
            # Default delays based on model RPM limits:
            # Flash Lite (15 RPM limit) -> ~4.0s delay (60/15 = 4s)
            # Standard Flash / Pro (5 RPM limit) -> ~12.0s delay (60/5 = 12s)
            is_lite = "lite" in self.model.lower()
            self.inter_request_delay = 4.0 if is_lite else 12.0

        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        self.forbidden_cooldown_seconds = forbidden_cooldown_seconds
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.failed_calls: int = 0
        self.total_items_processed: int = 0
        self._disabled: bool = False
        self._capability_validated: bool = False

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5) and not self._disabled

    def get_stats(self) -> Dict[str, int]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "total_items_processed": self.total_items_processed,
        }

    @staticmethod
    def _supports_generate_content(model_payload: Dict[str, Any], configured_model: str) -> bool:
        model_name = model_payload.get("name")
        if not isinstance(model_name, str):
            return False
        normalized_name = model_name.rsplit("/", 1)[-1]
        normalized_model = configured_model.rsplit("/", 1)[-1]
        methods = model_payload.get("supportedGenerationMethods")
        return normalized_name == normalized_model and isinstance(methods, list) and "generateContent" in methods

    @classmethod
    def validate_model_capability_payload(
        cls,
        payload: Any,
        configured_model: str,
    ) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise GeminiModelCapabilityError("Gemini models.list returned an invalid response")
        if not any(
            isinstance(model, dict) and cls._supports_generate_content(model, configured_model)
            for model in payload["models"]
        ):
            raise GeminiModelCapabilityError(
                f"Configured Gemini model '{configured_model}' does not support generateContent"
            )

    def validate_model_capability(self, timeout: float = 10.0) -> None:
        """Verify the configured model exists and supports the matcher operation."""
        if not self.api_key or not self.api_key.strip():
            raise GeminiModelCapabilityError("Gemini API key is required for model capability validation")
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={
                "Accept": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise GeminiModelCapabilityError(
                f"Gemini models.list capability check failed with HTTP {exc.code}"
            ) from exc
        except Exception as exc:
            raise GeminiModelCapabilityError(
                f"Gemini models.list capability check failed ({type(exc).__name__})"
            ) from exc
        self.validate_model_capability_payload(payload, self.model)
        self._capability_validated = True

    def _call_gemini(
        self,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None,
        action_name: str = "generateContent",
        item_count: int = 1,
    ) -> Optional[Dict[str, Any]]:
        if not self.is_available:
            return None

        self.total_calls += 1
        call_id = self.total_calls
        t0 = time.perf_counter()
        sent_time_str = datetime.now().strftime("%H:%M:%S")

        logger.info(
            f"[Gemini API #{call_id}] [Sent @ {sent_time_str}] Starting '{action_name}' request "
            f"(model: {self.model}, items: {item_count}, prompt_len: {len(prompt)} chars)..."
        )

        url = self.endpoint
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "thinkingConfig": {
                    "thinkingBudget": 0
                },
            }
        }
        if schema:
            payload["generationConfig"]["responseSchema"] = schema

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST"
        )

        max_retries = 3
        for attempt in range(max_retries):
            attempt_start_time_str = datetime.now().strftime("%H:%M:%S")
            try:
                attempt_t0 = time.perf_counter()
                with urllib.request.urlopen(req, timeout=120) as resp:
                    resp_bytes = resp.read()
                    resp_json = json.loads(resp_bytes.decode("utf-8"))
                    candidates = resp_json.get("candidates", [])
                    finished_time_str = datetime.now().strftime("%H:%M:%S")
                    if candidates:
                        first_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                        parsed_res = json.loads(first_part)
                        elapsed = time.perf_counter() - attempt_t0
                        self.successful_calls += 1
                        self.total_items_processed += item_count
                        logger.info(
                            f"[Gemini API #{call_id}] [Received @ {finished_time_str}] Request '{action_name}' SUCCEEDED in {elapsed:.2f}s "
                            f"(processed {item_count} items)."
                        )
                        return parsed_res
                    logger.warning(
                        f"[Gemini API #{call_id}] [Received @ {finished_time_str}] No candidates returned in response."
                    )
                    self.failed_calls += 1
                    return None
            except urllib.error.HTTPError as e:
                err_time_str = datetime.now().strftime("%H:%M:%S")
                # Retry on rate limits or transient server errors
                if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    retry_delay = 2.0 * (attempt + 1)
                    logger.warning(
                        f"[Gemini API #{call_id}] [Error @ {err_time_str}] HTTP error {e.code} ({e.reason}) on attempt {attempt + 1}/{max_retries}. "
                        f"Retrying in {retry_delay:.1f}s..."
                    )
                    time.sleep(retry_delay)
                    continue
                logger.error(
                    f"[Gemini API #{call_id}] [Error @ {err_time_str}] HTTP error {e.code} ({e.reason}) for model '{self.model}'. "
                    f"Disabling further AI calls for this run."
                )
                self.failed_calls += 1
                self._disabled = True
                break
            except urllib.error.URLError as e:
                err_time_str = datetime.now().strftime("%H:%M:%S")
                is_timeout = "timed out" in str(e.reason).lower() or isinstance(getattr(e, "reason", None), TimeoutError)
                if is_timeout and attempt < max_retries - 1:
                    retry_delay = 2.0 * (attempt + 1)
                    logger.warning(
                        f"[Gemini API #{call_id}] [Error @ {err_time_str}] Connection/read timeout on attempt {attempt + 1}/{max_retries}: {e.reason}. "
                        f"Retrying in {retry_delay:.1f}s..."
                    )
                    time.sleep(retry_delay)
                    continue
                logger.error(
                    f"[Gemini API #{call_id}] [Error @ {err_time_str}] URL error: {e.reason}. "
                    f"Disabling further AI calls for this run."
                )
                self.failed_calls += 1
                self._disabled = True
                break
            except Exception as e:
                err_time_str = datetime.now().strftime("%H:%M:%S")
                is_timeout = "timed out" in str(e).lower() or isinstance(e, TimeoutError)
                if is_timeout and attempt < max_retries - 1:
                    retry_delay = 2.0 * (attempt + 1)
                    logger.warning(
                        f"[Gemini API #{call_id}] [Error @ {err_time_str}] Timeout on attempt {attempt + 1}/{max_retries}: {e}. "
                        f"Retrying in {retry_delay:.1f}s..."
                    )
                    time.sleep(retry_delay)
                    continue
                logger.error(
                    f"[Gemini API #{call_id}] [Error @ {err_time_str}] Call failed: {e}. "
                    f"Disabling further AI calls for this run."
                )
                self.failed_calls += 1
                self._disabled = True
                break

        return None

    def batch_extract_titles(self, items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        """
        Batch extracts clean title, year, and media type from noisy torrent raw titles.
        items: [{"id": 0, "raw_title": "...", "feed_type": "movie"|"series"}]
        Returns dict keyed by item id:
        {
           0: {"title": "Dune: Part Two", "year": 2024, "media_type": "movie", "confidence": "high"}
        }
        """
        if not self.is_available or not items:
            return {}

        prompt = (
            "You are an expert movie and TV series metadata parser. "
            "Given a JSON array of torrent titles from RuTracker/trackers and their expected feed type, "
            "extract the clean original international English/Latin title (or native transliterated title), "
            "release year (integer), and media type ('movie' or 'series').\n\n"
            "Rules:\n"
            "1. Remove Russian translated titles before the slash ('/'). Use the original/international title.\n"
            "2. Remove author names, directors in brackets like '(реж. Denis Villeneuve)', and codec tags.\n"
            "3. If seasons/episodes are present (e.g. 'Сезон 1', '[01-08 из 08]', 'S01'), treat that as a series marker.\n"
            "4. When feed_type is 'movie' or 'series', it is authoritative for source type; do not silently change it because of a marker.\n"
            "5. When feed_type is 'unknown', infer the source type from the title and its markers.\n\n"
            f"Input items:\n{json.dumps(items, ensure_ascii=False)}"
        )

        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "title": {"type": "STRING"},
                    "year": {"type": "INTEGER", "nullable": True},
                    "media_type": {"type": "STRING", "enum": ["movie", "series"]},
                    "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]}
                },
                "required": ["id", "title", "media_type"]
            }
        }

        result = self._call_gemini(
            prompt,
            schema,
            action_name="batch_extract_titles",
            item_count=len(items),
        )
        if not result or not isinstance(result, list):
            return {}

        out = {}
        for entry in result:
            if isinstance(entry, dict) and "id" in entry:
                out[entry["id"]] = entry
        logger.info(f"[AiMatcher] Extracted title metadata for {len(out)}/{len(items)} items.")
        return out

    def batch_validate_omdb_matches(self, candidates: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        """
        Validates whether OMDb results match the original torrent titles to eliminate false positives.
        candidates: [{"id": 0, "raw_title": "...", "feed_type": "...", "omdb_title": "...", "omdb_year": 2024, "omdb_type": "movie"}]
        Returns dict keyed by candidate id:
        {
           0: {"is_match": True, "confidence": 0.95, "reason": "Exact match"}
        }
        """
        if not self.is_available or not candidates:
            return {}

        prompt = (
            "You are a strict film and TV series verification agent. "
            "Given a list of torrent titles and candidate OMDb matches, decide if each OMDb match is genuinely "
            "the movie/series described in the torrent title. "
            "PRINCIPLE: It is much better to mark an item as NOT a match (is_match=false) than to accept a wrong title.\n\n"
            "Rules:\n"
            "1. If torrent is a TV series and OMDb result is a movie (or vice versa), is_match MUST be false.\n"
            "2. Apply the one-year release-year tolerance only to movies. A series torrent year can be a later season/release year, while OMDb Year commonly contains the show's first broadcast year; that difference alone is NOT a mismatch.\n"
            "3. If titles are completely unrelated (e.g. searching 'Fallout' matched a 1995 documentary 'Fallout'), is_match MUST be false.\n\n"
            f"Candidate pairs:\n{json.dumps(candidates, ensure_ascii=False)}"
        )

        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "is_match": {"type": "BOOLEAN"},
                    "confidence": {"type": "NUMBER"},
                    "reason": {"type": "STRING"}
                },
                "required": ["id", "is_match", "confidence"]
            }
        }

        result = self._call_gemini(
            prompt,
            schema,
            action_name="batch_validate_omdb_matches",
            item_count=len(candidates),
        )
        if not result or not isinstance(result, list):
            return {}

        out = {}
        for entry in result:
            if isinstance(entry, dict) and "id" in entry:
                out[entry["id"]] = entry
        logger.info(f"[AiMatcher] Validated OMDb matches for {len(out)}/{len(candidates)} candidates.")
        return out

    def batch_recheck_matches(self, items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        """
        Audits existing database titles and their torrent raw titles.
        Determines whether the currently assigned OMDb metadata is correct.
        If incorrect, extracts clean corrected title, year, and media type to allow a new OMDb query.

        items: [{
            "id": 0,
            "raw_title": "...",
            "current_omdb_title": "...",
            "current_omdb_year": 2024,
            "current_omdb_type": "movie",
            "current_imdb_id": "tt1234567"
        }]

        Returns:
        {
            0: {
                "is_valid_match": False,
                "corrected_title": "Alien: Romulus",
                "corrected_year": 2024,
                "corrected_media_type": "movie",
                "reason": "Previous match was 1979 Alien instead of 2024 Alien Romulus"
            }
        }
        """
        if not self.is_available or not items:
            return {}

        prompt = (
            "You are an expert movie and TV series metadata auditor and correction agent.\n"
            "You are given pairs of raw torrent titles (from RuTracker / media trackers) and the currently assigned OMDb metadata stored in the database.\n"
            "Evaluate whether each stored OMDb metadata entry is a TRUE, ACCURATE match for the torrent release.\n\n"
            "Verification criteria:\n"
            "1. If the torrent is for a TV series (has season/episode info, e.g. S01, Сезон 1) but the current OMDb item is a movie, it is INVALID (is_valid_match=false).\n"
            "2. If the torrent is for a movie but the current OMDb item is a TV series, it is INVALID.\n"
            "3. Apply the one-year release-year tolerance only to movies. A raw series year can identify a later season/release, while OMDb Year commonly identifies the series' first broadcast year; do NOT mark a series invalid solely for that difference.\n"
            "4. If the title is an unrelated movie (e.g. remake vs original, wrong film with similar word, documentary matched as feature film), it is INVALID.\n"
            "5. If INVALID, extract the exact original clean English/Latin title, release year, and media type ('movie' or 'series') from the raw torrent title so a new OMDb lookup can be performed.\n"
            "6. If VALID (the torrent is indeed for the specified movie/series), set is_valid_match=true.\n\n"
            f"Items to audit:\n{json.dumps(items, ensure_ascii=False)}"
        )

        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "is_valid_match": {"type": "BOOLEAN"},
                    "corrected_title": {"type": "STRING", "nullable": True},
                    "corrected_year": {"type": "INTEGER", "nullable": True},
                    "corrected_media_type": {"type": "STRING", "enum": ["movie", "series"], "nullable": True},
                    "reason": {"type": "STRING"}
                },
                "required": ["id", "is_valid_match"]
            }
        }

        result = self._call_gemini(
            prompt,
            schema,
            action_name="batch_recheck_matches",
            item_count=len(items),
        )
        if not result or not isinstance(result, list):
            return {}

        requested_ids = [item.get("id") for item in items]
        if (
            any(type(item_id) is not int for item_id in requested_ids)
            or len(set(requested_ids)) != len(requested_ids)
            or len(result) != len(requested_ids)
        ):
            return {}

        out = {}
        for entry in result:
            if (
                not isinstance(entry, dict)
                or type(entry.get("id")) is not int
                or entry["id"] not in requested_ids
                or entry["id"] in out
                or type(entry.get("is_valid_match")) is not bool
            ):
                return {}
            out[entry["id"]] = entry
        if set(out) != set(requested_ids):
            return {}
        logger.info(f"[AiMatcher] Audited {len(out)}/{len(items)} database titles.")
        return out
