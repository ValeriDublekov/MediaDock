import json
import logging
import os
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

    def __init__(self, api_key: Optional[str] = None, model: str = GEMINI_MODEL):
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def _call_gemini(self, prompt: str, schema: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not self.is_available:
            return None

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

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp_bytes = resp.read()
                resp_json = json.loads(resp_bytes.decode("utf-8"))
                candidates = resp_json.get("candidates", [])
                if candidates:
                    first_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                    return json.loads(first_part)
        except urllib.error.HTTPError as e:
            logger.warning(f"Gemini API HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            logger.warning(f"Gemini API URL error: {e.reason}")
        except Exception as e:
            logger.warning(f"Gemini API call failed: {e}")

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

        result = self._call_gemini(prompt, schema)
        if not result or not isinstance(result, list):
            return {}

        out = {}
        for entry in result:
            if isinstance(entry, dict) and "id" in entry:
                out[entry["id"]] = entry
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

        result = self._call_gemini(prompt, schema)
        if not result or not isinstance(result, list):
            return {}

        out = {}
        for entry in result:
            if isinstance(entry, dict) and "id" in entry:
                out[entry["id"]] = entry
        return out
