import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.7-flash"


class AiMatcher:
    """
    AI-powered batch parsing and validation helper for media scanner.
    Uses Gemini REST API with structured outputs to parse complex torrent titles
    and validate candidate OMDb matches in batches.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = GEMINI_MODEL,
        forbidden_cooldown_seconds: float = 300.0,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        self.forbidden_cooldown_seconds = forbidden_cooldown_seconds
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.failed_calls: int = 0
        self.total_items_processed: int = 0

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def get_stats(self) -> Dict[str, int]:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "total_items_processed": self.total_items_processed,
        }

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

        logger.info(
            f"[Gemini API #{call_id}] Starting '{action_name}' request "
            f"(model: {self.model}, items: {item_count}, prompt_len: {len(prompt)} chars)..."
        )

        url = f"{self.endpoint}?key={self.api_key}"
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            }
        }
        if schema:
            payload["generationConfig"]["responseSchema"] = schema

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    resp_bytes = resp.read()
                    resp_json = json.loads(resp_bytes.decode("utf-8"))
                    candidates = resp_json.get("candidates", [])
                    if candidates:
                        first_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                        parsed_res = json.loads(first_part)
                        elapsed = time.perf_counter() - t0
                        self.successful_calls += 1
                        self.total_items_processed += item_count
                        logger.info(
                            f"[Gemini API #{call_id}] Request '{action_name}' SUCCEEDED in {elapsed:.2f}s "
                            f"(processed {item_count} items)."
                        )
                        return parsed_res
                    logger.warning(f"[Gemini API #{call_id}] No candidates returned in response.")
                    self.failed_calls += 1
                    return None
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    if attempt < max_retries - 1:
                        cooldown_mins = self.forbidden_cooldown_seconds / 60.0
                        logger.warning(
                            f"[Gemini API #{call_id}] HTTP 403 Forbidden received. "
                            f"Pausing execution for {int(self.forbidden_cooldown_seconds)}s ({cooldown_mins:.1f} minutes) "
                            f"before retry (attempt {attempt + 1}/{max_retries})..."
                        )
                        time.sleep(self.forbidden_cooldown_seconds)
                        continue
                    else:
                        logger.error(
                            f"[Gemini API #{call_id}] HTTP 403 Forbidden: persistent error "
                            f"after {max_retries} attempts."
                        )
                        self.failed_calls += 1
                        break
                if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) * 2.0
                    logger.warning(
                        f"[Gemini API #{call_id}] HTTP {e.code} ({e.reason}). "
                        f"Retrying in {sleep_time:.1f}s (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(sleep_time)
                    continue
                logger.warning(f"[Gemini API #{call_id}] HTTP error {e.code}: {e.reason}")
                self.failed_calls += 1
                break
            except urllib.error.URLError as e:
                logger.warning(f"[Gemini API #{call_id}] URL error: {e.reason}")
                self.failed_calls += 1
                break
            except Exception as e:
                logger.warning(f"[Gemini API #{call_id}] Call failed: {e}")
                self.failed_calls += 1
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
            "3. If seasons/episodes are present (e.g. 'Сезон 1', '[01-08 из 08]', 'S01'), media_type MUST be 'series'.\n"
            "4. If feed_type is 'movie' but title is clearly a multi-episode TV series, set media_type to 'series'.\n"
            "5. If feed_type is 'series' but title is a single standalone movie, set media_type to 'movie'.\n\n"
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
            "2. If movie years differ by more than 1 year, is_match MUST be false.\n"
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
            "3. If release years differ by more than 1 year, it is INVALID.\n"
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

        out = {}
        for entry in result:
            if isinstance(entry, dict) and "id" in entry:
                out[entry["id"]] = entry
        logger.info(f"[AiMatcher] Audited {len(out)}/{len(items)} database titles.")
        return out
