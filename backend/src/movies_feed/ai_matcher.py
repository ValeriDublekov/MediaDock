import json
import logging
import os
import time
from pathlib import Path
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, List, Optional, Set

from .ai_validator import (
    DEFAULT_MIN_AUDIT_CONFIDENCE,
    DEFAULT_MIN_CANDIDATE_VALIDATION_CONFIDENCE,
    DEFAULT_MIN_EXTRACTION_CONFIDENCE,
    MAX_RESPONSE_BYTES,
    validate_batch_extract_results,
    validate_batch_recheck_results,
    validate_batch_validate_omdb_results,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def _load_prompt_template(filename: str) -> str:
    prompt_file = PROMPTS_DIR / filename
    if prompt_file.is_file():
        return prompt_file.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt template file not found: {prompt_file}")


def _bound_text(text: Any, max_length: int = 500) -> str:
    if not isinstance(text, str):
        return ""
    return text[:max_length]


class GeminiModelCapabilityError(ValueError):
    """Raised when the configured Gemini model cannot run generateContent."""


class AiMatcher:
    """
    AI-powered batch parsing and validation helper for media scanner.
    Uses Gemini REST API with structured outputs to parse complex torrent titles
    and validate candidate OMDb matches in batches.

    Error classification policy:
    - Retryable errors: HTTP 429 (rate limit), HTTP 500/502/503/504 (server error),
      and connection/read timeouts (URLError/TimeoutError). Retried up to 3 total
      attempts (1 initial + 2 retries) with linear backoff (2s * attempt).
    - Terminal errors:
      - HTTP 401: Authentication failure (invalid API key) -> disables matcher for run.
      - HTTP 403: Forbidden (quota/project permission) -> sets forbidden cooldown.
      - HTTP 400/404: Bad request or invalid model -> disables matcher for run.
      - Other 4xx / unexpected non-retryable errors -> disables matcher for run.
      - Response body size exceeding MAX_RESPONSE_BYTES -> rejected and counted as failure.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        inter_request_delay: Optional[float] = None,
        forbidden_cooldown_seconds: float = 300.0,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        chosen_model = model or os.environ.get("GEMINI_MODEL", GEMINI_MODEL)
        self.model = chosen_model

        self.clock: Callable[[], float] = clock or time.monotonic
        self.sleep: Callable[[float], None] = sleep or time.sleep

        # Determine inter-request delay to comply with model RPM limits
        if inter_request_delay is not None:
            self.inter_request_delay = float(inter_request_delay)
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
        self._forbidden_until: Optional[float] = None
        self._last_request_time: Optional[float] = None
        self._capability_validated: bool = False

    @property
    def is_available(self) -> bool:
        if not bool(self.api_key and len(self.api_key.strip()) > 5):
            return False
        if self._disabled:
            return False
        if self._forbidden_until is not None:
            if self.clock() < self._forbidden_until:
                return False
            self._forbidden_until = None
        return True

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
                resp_bytes = response.read(MAX_RESPONSE_BYTES + 1)
                if len(resp_bytes) > MAX_RESPONSE_BYTES:
                    raise GeminiModelCapabilityError(
                        f"Gemini models.list response exceeded maximum allowed size {MAX_RESPONSE_BYTES} bytes"
                    )
                payload = json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise GeminiModelCapabilityError(
                f"Gemini models.list capability check failed with HTTP {exc.code}"
            ) from exc
        except GeminiModelCapabilityError:
            raise
        except Exception as exc:
            raise GeminiModelCapabilityError(
                f"Gemini models.list capability check failed ({type(exc).__name__})"
            ) from exc
        self.validate_model_capability_payload(payload, self.model)
        self._capability_validated = True

    def _enforce_inter_request_delay(self) -> None:
        if self.inter_request_delay > 0 and self._last_request_time is not None:
            elapsed = self.clock() - self._last_request_time
            if elapsed < self.inter_request_delay:
                delay_needed = self.inter_request_delay - elapsed
                self.sleep(delay_needed)
        self._last_request_time = self.clock()

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

        logger.info(
            f"[Gemini API #{call_id}] Starting '{action_name}' request "
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
            self._enforce_inter_request_delay()
            try:
                attempt_t0 = self.clock()
                with urllib.request.urlopen(req, timeout=120) as resp:
                    resp_bytes = resp.read(MAX_RESPONSE_BYTES + 1)
                    if len(resp_bytes) > MAX_RESPONSE_BYTES:
                        logger.error(
                            f"[Gemini API #{call_id}] Response body exceeded maximum allowed size {MAX_RESPONSE_BYTES} bytes."
                        )
                        self.failed_calls += 1
                        return None
                    resp_json = json.loads(resp_bytes.decode("utf-8"))
                    candidates = resp_json.get("candidates", [])
                    if candidates:
                        first_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                        parsed_res = json.loads(first_part)
                        elapsed = self.clock() - attempt_t0
                        self.successful_calls += 1
                        self.total_items_processed += item_count
                        logger.info(
                            f"[Gemini API #{call_id}] Request '{action_name}' SUCCEEDED in {elapsed:.2f}s "
                            f"(processed {item_count} items)."
                        )
                        return parsed_res
                    logger.warning(
                        f"[Gemini API #{call_id}] No candidates returned in response."
                    )
                    self.failed_calls += 1
                    return None
            except urllib.error.HTTPError as e:
                # Retry on rate limits or transient server errors
                if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    retry_delay = 2.0 * (attempt + 1)
                    logger.warning(
                        f"[Gemini API #{call_id}] HTTP error {e.code} ({e.reason}) on attempt {attempt + 1}/{max_retries}. "
                        f"Retrying in {retry_delay:.1f}s..."
                    )
                    self.sleep(retry_delay)
                    continue
                if e.code == 403:
                    logger.error(
                        f"[Gemini API #{call_id}] HTTP error 403 (Forbidden) for model '{self.model}'. "
                        f"Setting cooldown for {self.forbidden_cooldown_seconds:.1f}s."
                    )
                    self._forbidden_until = self.clock() + self.forbidden_cooldown_seconds
                    self.failed_calls += 1
                    break
                logger.error(
                    f"[Gemini API #{call_id}] HTTP error {e.code} ({e.reason}) for model '{self.model}'. "
                    f"Disabling further AI calls for this run."
                )
                self.failed_calls += 1
                self._disabled = True
                break
            except urllib.error.URLError as e:
                is_timeout = "timed out" in str(e.reason).lower() or isinstance(getattr(e, "reason", None), TimeoutError)
                if is_timeout and attempt < max_retries - 1:
                    retry_delay = 2.0 * (attempt + 1)
                    logger.warning(
                        f"[Gemini API #{call_id}] Connection/read timeout on attempt {attempt + 1}/{max_retries}: {e.reason}. "
                        f"Retrying in {retry_delay:.1f}s..."
                    )
                    self.sleep(retry_delay)
                    continue
                logger.error(
                    f"[Gemini API #{call_id}] URL error: {e.reason}. "
                    f"Disabling further AI calls for this run."
                )
                self.failed_calls += 1
                self._disabled = True
                break
            except Exception as e:
                is_timeout = "timed out" in str(e).lower() or isinstance(e, TimeoutError)
                if is_timeout and attempt < max_retries - 1:
                    retry_delay = 2.0 * (attempt + 1)
                    logger.warning(
                        f"[Gemini API #{call_id}] Timeout on attempt {attempt + 1}/{max_retries}: {type(e).__name__}. "
                        f"Retrying in {retry_delay:.1f}s..."
                    )
                    self.sleep(retry_delay)
                    continue
                logger.error(
                    f"[Gemini API #{call_id}] Call failed: {type(e).__name__}. "
                    f"Disabling further AI calls for this run."
                )
                self.failed_calls += 1
                self._disabled = True
                break

        return None

    def batch_extract_titles(
        self,
        items: List[Dict[str, Any]],
        min_confidence: float = DEFAULT_MIN_EXTRACTION_CONFIDENCE,
    ) -> Dict[int, Dict[str, Any]]:
        """
        Batch extracts clean title, year, and media type from noisy torrent raw titles.
        items: [{"id": 0, "raw_title": "...", "feed_type": "movie"|"series"}]
        Returns dict keyed by item id:
        {
           0: {"id": 0, "title": "Dune: Part Two", "year": 2024, "media_type": "movie", "confidence": 0.95}
        }
        """
        if not self.is_available or not items:
            return {}

        expected_ids: Set[int] = set()
        bounded_items: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict) or type(it.get("id")) is not int:
                return {}
            expected_ids.add(it["id"])
            bounded_items.append({
                "id": it["id"],
                "raw_title": _bound_text(it.get("raw_title", "")),
                "feed_type": str(it.get("feed_type") or "unknown")[:50],
            })

        if len(expected_ids) != len(items):
            return {}

        template = _load_prompt_template("extract_titles.txt")
        prompt = template.format(items_json=json.dumps(bounded_items, ensure_ascii=False))

        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "title": {"type": "STRING"},
                    "year": {"type": "INTEGER", "nullable": True},
                    "media_type": {"type": "STRING", "enum": ["movie", "series"]},
                    "confidence": {"type": "NUMBER"}
                },
                "required": ["id", "title", "media_type", "confidence"]
            }
        }

        result = self._call_gemini(
            prompt,
            schema,
            action_name="batch_extract_titles",
            item_count=len(bounded_items),
        )
        if result is None:
            return {}

        validated = validate_batch_extract_results(result, expected_ids, min_confidence=min_confidence)
        if validated:
            logger.info(f"[AiMatcher] Extracted title metadata for {len(validated)}/{len(items)} items.")
        else:
            logger.warning(f"[AiMatcher] batch_extract_titles validation failed or returned low confidence.")
        return validated

    def batch_validate_omdb_matches(
        self,
        candidates: List[Dict[str, Any]],
        min_confidence: float = DEFAULT_MIN_CANDIDATE_VALIDATION_CONFIDENCE,
    ) -> Dict[int, Dict[str, Any]]:
        """
        Validates whether OMDb results match the original torrent titles to eliminate false positives.
        candidates: [{"id": 0, "raw_title": "...", "feed_type": "...", "omdb_title": "...", "omdb_year": 2024, "omdb_type": "movie"}]
        Returns dict keyed by candidate id:
        {
           0: {"id": 0, "is_match": True, "confidence": 0.95, "reason": "Exact match"}
        }
        """
        if not self.is_available or not candidates:
            return {}

        expected_ids: Set[int] = set()
        bounded_candidates: List[Dict[str, Any]] = []
        for c in candidates:
            if not isinstance(c, dict) or type(c.get("id")) is not int:
                return {}
            expected_ids.add(c["id"])
            bounded_candidates.append({
                "id": c["id"],
                "raw_title": _bound_text(c.get("raw_title", "")),
                "feed_type": str(c.get("feed_type") or "unknown")[:50],
                "omdb_title": _bound_text(c.get("omdb_title", "")),
                "omdb_year": c.get("omdb_year") if type(c.get("omdb_year")) is int else None,
                "omdb_type": str(c.get("omdb_type") or "unknown")[:50],
            })

        if len(expected_ids) != len(candidates):
            return {}

        template = _load_prompt_template("validate_omdb_matches.txt")
        prompt = template.format(candidates_json=json.dumps(bounded_candidates, ensure_ascii=False))

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
            item_count=len(bounded_candidates),
        )
        if result is None:
            return {}

        validated = validate_batch_validate_omdb_results(result, expected_ids, min_confidence=min_confidence)
        if validated:
            logger.info(f"[AiMatcher] Validated OMDb matches for {len(validated)}/{len(candidates)} candidates.")
        else:
            logger.warning(f"[AiMatcher] batch_validate_omdb_matches validation failed or returned low confidence.")
        return validated

    def batch_recheck_matches(
        self,
        items: List[Dict[str, Any]],
        min_confidence: float = DEFAULT_MIN_AUDIT_CONFIDENCE,
    ) -> Dict[int, Dict[str, Any]]:
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
                "id": 0,
                "is_valid_match": False,
                "confidence": 0.90,
                "corrected_title": "Alien: Romulus",
                "corrected_year": 2024,
                "corrected_media_type": "movie",
                "reason": "Previous match was 1979 Alien instead of 2024 Alien Romulus"
            }
        }
        """
        if not self.is_available or not items:
            return {}

        expected_ids: Set[int] = set()
        bounded_items: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict) or type(it.get("id")) is not int:
                return {}
            expected_ids.add(it["id"])
            bounded_items.append({
                "id": it["id"],
                "raw_title": _bound_text(it.get("raw_title", "")),
                "feed_name": _bound_text(it.get("feed_name", ""), max_length=100),
                "current_omdb_title": _bound_text(it.get("current_omdb_title", "")),
                "current_omdb_year": it.get("current_omdb_year") if type(it.get("current_omdb_year")) is int else None,
                "current_omdb_type": str(it.get("current_omdb_type") or "")[:50],
                "current_imdb_id": str(it.get("current_imdb_id") or "")[:20],
            })

        if len(expected_ids) != len(items):
            return {}

        template = _load_prompt_template("recheck_matches.txt")
        prompt = template.format(items_json=json.dumps(bounded_items, ensure_ascii=False))

        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "is_valid_match": {"type": "BOOLEAN"},
                    "confidence": {"type": "NUMBER"},
                    "corrected_title": {"type": "STRING", "nullable": True},
                    "corrected_year": {"type": "INTEGER", "nullable": True},
                    "corrected_media_type": {"type": "STRING", "enum": ["movie", "series"], "nullable": True},
                    "reason": {"type": "STRING"}
                },
                "required": ["id", "is_valid_match", "confidence"]
            }
        }

        result = self._call_gemini(
            prompt,
            schema,
            action_name="batch_recheck_matches",
            item_count=len(bounded_items),
        )
        if result is None:
            return {}

        validated = validate_batch_recheck_results(result, expected_ids, min_confidence=min_confidence)
        if validated:
            logger.info(f"[AiMatcher] Audited {len(validated)}/{len(items)} database titles.")
        else:
            logger.warning(f"[AiMatcher] batch_recheck_matches validation failed or returned low confidence.")
        return validated
