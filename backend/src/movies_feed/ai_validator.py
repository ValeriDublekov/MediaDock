"""Shared validation module for Gemini AI outputs in movies_feed.

Enforces strict typed, bounded, and confidence-aware schemas for:
- batch_extract_titles
- batch_validate_omdb_matches
- batch_recheck_matches
"""

import math
from typing import Any, Dict, List, Optional, Set, Tuple

DEFAULT_MIN_EXTRACTION_CONFIDENCE = 0.70
DEFAULT_MIN_CANDIDATE_VALIDATION_CONFIDENCE = 0.70
DEFAULT_MIN_AUDIT_CONFIDENCE = 0.80

ALLOWED_MEDIA_TYPES = {"movie", "series"}
MAX_TITLE_LENGTH = 500
MAX_REASON_LENGTH = 1000
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MiB safeguard


def parse_finite_confidence(val: Any) -> Optional[float]:
    """Parses a confidence value into a float in inclusive range [0.0, 1.0].
    
    Returns None if val is missing, wrong type (e.g. bool), NaN, inf, or out of range.
    """
    if val is None or isinstance(val, bool):
        return None
    if not isinstance(val, (int, float)):
        return None
    c_val = float(val)
    if not math.isfinite(c_val) or not (0.0 <= c_val <= 1.0):
        return None
    return c_val


def validate_ai_batch_structure(
    raw_response: Any,
    expected_ids: Set[int],
) -> Optional[Dict[int, Dict[str, Any]]]:
    """Validates raw response structure against requested integer IDs.
    
    Requires:
    - raw_response is a list of dicts or an id-keyed dict of dicts
    - exactly one result for every requested ID
    - no duplicate, missing, or unknown IDs
    - ID field must be an integer
    """
    if isinstance(raw_response, dict):
        if set(raw_response.keys()) != expected_ids:
            return None
        entries = list(raw_response.values())
    elif isinstance(raw_response, list):
        entries = raw_response
    else:
        return None

    if len(entries) != len(expected_ids):
        return None

    by_id: Dict[int, Dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        item_id = entry.get("id")
        if type(item_id) is not int:
            return None
        if item_id not in expected_ids or item_id in by_id:
            return None
        by_id[item_id] = entry

    if set(by_id.keys()) != expected_ids:
        return None
    return by_id


def validate_batch_extract_results(
    raw_response: Any,
    expected_ids: Set[int],
    min_confidence: float = DEFAULT_MIN_EXTRACTION_CONFIDENCE,
) -> Dict[int, Dict[str, Any]]:
    """Validates output of batch_extract_titles.
    
    Required per entry:
    - id: integer in expected_ids
    - title: non-empty string, <= MAX_TITLE_LENGTH
    - media_type: 'movie' or 'series'
    - confidence: float in [0.0, 1.0] and >= min_confidence
    - year: optional integer (1880..2100) or None
    
    Fail-closed: if any entry fails validation, returns empty dict {}.
    """
    by_id = validate_ai_batch_structure(raw_response, expected_ids)
    if by_id is None:
        return {}

    validated: Dict[int, Dict[str, Any]] = {}
    for item_id, entry in by_id.items():
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE_LENGTH:
            return {}

        media_type = entry.get("media_type")
        if not isinstance(media_type, str) or media_type.lower() not in ALLOWED_MEDIA_TYPES:
            return {}

        year = entry.get("year")
        if year is not None:
            if type(year) is not int or year < 1880 or year > 2100:
                return {}

        conf_raw = entry.get("confidence")
        conf_val = parse_finite_confidence(conf_raw)
        if conf_val is None or conf_val < min_confidence:
            return {}

        validated[item_id] = {
            "id": item_id,
            "title": title.strip(),
            "year": year,
            "media_type": media_type.lower(),
            "confidence": conf_val,
        }

    return validated


def validate_batch_validate_omdb_results(
    raw_response: Any,
    expected_ids: Set[int],
    min_confidence: float = DEFAULT_MIN_CANDIDATE_VALIDATION_CONFIDENCE,
) -> Dict[int, Dict[str, Any]]:
    """Validates output of batch_validate_omdb_matches.
    
    Required per entry:
    - id: integer in expected_ids
    - is_match: explicit boolean (True/False)
    - confidence: float in [0.0, 1.0] and >= min_confidence
    - reason: optional string
    
    Fail-closed: if any entry fails validation, returns empty dict {}.
    """
    by_id = validate_ai_batch_structure(raw_response, expected_ids)
    if by_id is None:
        return {}

    validated: Dict[int, Dict[str, Any]] = {}
    for item_id, entry in by_id.items():
        is_match = entry.get("is_match")
        if type(is_match) is not bool:
            return {}

        conf_raw = entry.get("confidence")
        conf_val = parse_finite_confidence(conf_raw)
        if conf_val is None or conf_val < min_confidence:
            return {}

        reason = entry.get("reason")
        if reason is not None and not isinstance(reason, str):
            return {}
        if isinstance(reason, str) and len(reason) > MAX_REASON_LENGTH:
            reason = reason[:MAX_REASON_LENGTH]

        validated[item_id] = {
            "id": item_id,
            "is_match": is_match,
            "confidence": conf_val,
            "reason": reason or "",
        }

    return validated


def validate_batch_recheck_results(
    raw_response: Any,
    expected_ids: Set[int],
    min_confidence: float = DEFAULT_MIN_AUDIT_CONFIDENCE,
) -> Dict[int, Dict[str, Any]]:
    """Validates output of batch_recheck_matches.
    
    Required per entry:
    - id: integer in expected_ids
    - is_valid_match: explicit boolean (True/False)
    - confidence: float in [0.0, 1.0] and >= min_confidence
    - If is_valid_match is False:
        - corrected_title: non-empty string or None (if None, must not be an empty string; if string, <= MAX_TITLE_LENGTH)
        - corrected_year: integer (1880..2100) or None
        - corrected_media_type: 'movie', 'series', or None
    - If is_valid_match is True:
        - corrected fields can be omitted or None
    
    Fail-closed: if any entry fails validation, returns empty dict {}.
    """
    by_id = validate_ai_batch_structure(raw_response, expected_ids)
    if by_id is None:
        return {}

    validated: Dict[int, Dict[str, Any]] = {}
    for item_id, entry in by_id.items():
        is_valid_match = entry.get("is_valid_match")
        if type(is_valid_match) is not bool:
            return {}

        conf_raw = entry.get("confidence")
        conf_val = parse_finite_confidence(conf_raw)
        if conf_val is None or conf_val < min_confidence:
            return {}

        reason = entry.get("reason")
        if reason is not None and not isinstance(reason, str):
            return {}
        if isinstance(reason, str) and len(reason) > MAX_REASON_LENGTH:
            reason = reason[:MAX_REASON_LENGTH]

        corr_title = entry.get("corrected_title")
        if corr_title is not None:
            if not isinstance(corr_title, str) or not corr_title.strip() or len(corr_title) > MAX_TITLE_LENGTH:
                return {}
            corr_title = corr_title.strip()

        corr_year = entry.get("corrected_year")
        if corr_year is not None:
            if type(corr_year) is not int or corr_year < 1880 or corr_year > 2100:
                return {}

        corr_media_type = entry.get("corrected_media_type")
        if corr_media_type is not None:
            if not isinstance(corr_media_type, str) or corr_media_type.lower() not in ALLOWED_MEDIA_TYPES:
                return {}
            corr_media_type = corr_media_type.lower()

        validated[item_id] = {
            "id": item_id,
            "is_valid_match": is_valid_match,
            "confidence": conf_val,
            "reason": reason or "",
            "corrected_title": corr_title,
            "corrected_year": corr_year,
            "corrected_media_type": corr_media_type,
        }

    return validated
