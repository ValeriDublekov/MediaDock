import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .scan_contracts import FeedDefinition

logger = logging.getLogger(__name__)

# Realistic year range for cinema and television releases
MIN_REALISTIC_YEAR = 1888
MAX_REALISTIC_YEAR = 2035

SERIES_MARKER_PATTERN = re.compile(
    r"\b(?:"
    r"s\d{1,2}(?:\s*-\s*s?\d{1,2})?(?:\s*e\d{1,2}(?:\s*-\s*e?\d{1,2})?)?"
    r"|season\s*\d+(?:\s*-\s*\d+)?"
    r"|seasons\s*\d+(?:\s*-\s*\d+)?"
    r"|сезон:?\s*\d+(?:\s*-\s*\d+)?"
    r"|сезоны:?\s*\d+(?:\s*-\s*\d+)?"
    r"|сери[яи]:?\s*\d+(?:\s*-\s*\d+)?(?:\s*из\s*\d+)?"
    r"|episodes?\s*\d+(?:\s*-\s*\d+)?(?:\s*of\s*\d+)?"
    r"|т/с|телесериал|мини-сериал"
    r")\b",
    re.IGNORECASE,
)

# Standard tags to detect quality and rip types if not configured
DEFAULT_QUALITY_TAGS = ["2160p", "4K", "1080p", "1080i", "720p", "576p", "480p"]
DEFAULT_RIP_TAGS = [
    "BDRemux",
    "BDRip",
    "Blu-ray",
    "WEB-DLRip",
    "WEB-DL",
    "WEBRip",
    "HDTVRip",
    "HDTV",
    "DVDRip",
    "DVD",
    "Remux",
]


@dataclass(frozen=True)
class ParsedTitle:
    title: str
    year: Optional[str]
    is_series: bool
    quality: str
    rip_type: str
    confidence: float = 1.0
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    def __init__(
        self,
        title: str,
        year: Optional[str],
        is_series: bool,
        quality: str,
        rip_type: str,
        confidence: float = 1.0,
        reasons: Iterable[str] = (),
    ):
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "year", year)
        object.__setattr__(self, "is_series", is_series)
        object.__setattr__(self, "quality", quality)
        object.__setattr__(self, "rip_type", rip_type)
        object.__setattr__(self, "confidence", round(float(confidence), 2))
        object.__setattr__(self, "reasons", tuple(reasons))


def is_latin_candidate(text: str) -> bool:
    """Returns True if text contains at least one Latin letter and is predominantly Latin."""
    if not text or not isinstance(text, str):
        return False

    # Must contain at least one Latin letter (digits alone are NOT Latin letters)
    has_latin = bool(re.search(r"[a-zA-Z]", text))
    if not has_latin:
        return False

    # Disallow exotic non-Latin scripts (Hebrew, Arabic, CJK, etc.)
    has_exotic = bool(
        re.search(
            r"[\u0590-\u05FF\u0600-\u06FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]",
            text,
        )
    )
    if has_exotic:
        return False

    cyrillic_chars = len(re.findall(r"[а-яА-ЯёЁ]", text))
    latin_chars = len(re.findall(r"[a-zA-Z]", text))
    return cyrillic_chars < 3 and latin_chars >= cyrillic_chars


def normalize_feed_definition(name: str, value: Any) -> FeedDefinition:
    if isinstance(value, str):
        feed_name = name
        feed_url = value
        feed_type = infer_feed_type(name)
    elif isinstance(value, dict):
        feed_name = value.get("name", name)
        feed_url = value.get("url")
        feed_type = value.get("type") or infer_feed_type(name)
    else:
        raise ValueError(f"Unsupported rss feed definition for '{name}'")

    if not isinstance(feed_url, str):
        raise ValueError("configured feed URL is missing")

    return FeedDefinition(
        id=name,
        name=feed_name,
        url=feed_url,
        type=feed_type,
    )


def iter_feed_definitions(rss_feeds: Dict[str, Any]) -> Iterable[FeedDefinition]:
    for name, value in rss_feeds.items():
        yield normalize_feed_definition(name, value)


def infer_feed_type(feed_name: str) -> Optional[str]:
    lowered = feed_name.lower()
    if "сериал" in lowered or "series" in lowered or "tv" in lowered:
        return "series"
    if (
        "филм" in lowered
        or "фильм" in lowered
        or "кино" in lowered
        or "movie" in lowered
        or "cinema" in lowered
    ):
        return "movie"
    return None


def is_metadata_parenthesis(paren_text: str) -> bool:
    """Returns True if the content inside parentheses is recognized metadata (director, year, translation, voiceover)."""
    text = paren_text.strip("() ")
    if not text:
        return True

    # 4-digit release year e.g. (1995) or (1995-1996)
    if re.match(r"^\d{4}(?:-\d{4})?$", text):
        return True

    # Known meaningful subtitles/cuts to preserve
    meaningful_subtitles = {
        "death and rebirth",
        "the end of evangelion",
        "stand alone complex",
        "the movie",
        "extended cut",
        "extended edition",
        "director's cut",
        "directors cut",
        "special edition",
        "unrated",
        "remastered",
        "final cut",
    }
    if text.lower() in meaningful_subtitles:
        return False
    if re.match(r"^(?:part|vol|chapter|edition|version)\s*\d*$", text, flags=re.IGNORECASE):
        return False

    # Explicit director indicators e.g. (реж. Квентин Тарантино) or (directed by ...)
    if re.search(r"\b(?:реж(?:исс?[её]р|\.|\b)|directed\s+by|dir\.)", text, flags=re.IGNORECASE):
        return True

    # Russian/Cyrillic text in trailing parentheses is director/creator/audio credit in RuTracker
    if re.search(r"[а-яА-ЯёЁ]", text):
        return True

    # Slashes inside parentheses (e.g. multiple directors or bilingual names)
    if "/" in text:
        return True

    # Audio / translation / dubbing metadata
    if re.match(
        r"^(?:дубляж|перевод|dvo|mvo|avo|vo|sub|lostfilm|hdrezka|newstudio|кураж-бамбей|звук)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return True

    # Series marker metadata inside parenthesis
    if re.match(r"^(?:сезон|серии|season|episodes?)\b", text, flags=re.IGNORECASE):
        return True

    return False


def is_part_series_marker(part: str) -> bool:
    """Checks if a title candidate part is purely a series marker or episode information."""
    stripped = part.strip()
    if not stripped:
        return True

    if re.match(
        r"^(?:сезон:?\s*\d+|сезоны:?\s*\d+|сери[яи]:?\s*\d+|season\s*\d+|seasons\s*\d+|episodes?\s*\d+|s\d{1,2})\b",
        stripped,
        flags=re.IGNORECASE,
    ):
        return True

    return False


def is_numeric_candidate(text: str) -> bool:
    """Returns True if text consists of numbers/symbols without Cyrillic letters."""
    if not text or not isinstance(text, str):
        return False
    has_cyrillic = bool(re.search(r"[а-яА-ЯёЁ]", text))
    has_exotic = bool(
        re.search(
            r"[\u0590-\u05FF\u0600-\u06FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]",
            text,
        )
    )
    return not has_cyrillic and not has_exotic and bool(re.search(r"\d", text))


def extract_year(clean_title: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts a 4-digit release year within realistic bounds (1888..2035).

    Returns (year_string or None, reason_code).
    """
    # 1. Bracketed block [1995, ...] or [2016-2017, ...] (excluding resolution tags like 1080p, 2160p)
    bracket_match = re.search(r"\[\s*(\d{4})(?:-\d{4})?(?!\s*[piPI])\b", clean_title)
    if bracket_match:
        y_val = int(bracket_match.group(1))
        if MIN_REALISTIC_YEAR <= y_val <= MAX_REALISTIC_YEAR:
            return str(y_val), "valid_year_extracted"
        return None, "invalid_year_range"

    # 2. Parenthesized year (1995) or (1995-1996)
    paren_match = re.search(r"\b\((\d{4})(?:-\d{4})?\)", clean_title)
    if paren_match:
        y_val = int(paren_match.group(1))
        if MIN_REALISTIC_YEAR <= y_val <= MAX_REALISTIC_YEAR:
            return str(y_val), "valid_year_extracted"
        return None, "invalid_year_range"

    # 3. Standalone year in title (bounded, excluding resolution tags)
    standalone_match = re.search(r"\b(188[89]|189\d|19\d{2}|20[0-3]\d)\b(?!\s*[piPI])", clean_title)
    if standalone_match:
        y_val = int(standalone_match.group(1))
        if MIN_REALISTIC_YEAR <= y_val <= MAX_REALISTIC_YEAR:
            return str(y_val), "valid_year_extracted"

    # 4. Out of range check if 4 digits were present in brackets/parentheses (excluding resolution tags)
    any_four_digits = re.search(r"(?:\[|\()\s*(\d{4})(?!\s*[piPI])", clean_title)
    if any_four_digits:
        return None, "invalid_year_range"

    return None, "year_missing"


def extract_title_section(clean_title: str) -> str:
    """Extracts the title portion before the main bracketed metadata block, stripping trailing metadata parentheses."""
    title_section = clean_title.split("[", 1)[0].strip()

    trailing_paren_match = re.search(r"\s*(\([^)]*\))$", title_section)
    if trailing_paren_match:
        paren_content = trailing_paren_match.group(1)
        if is_metadata_parenthesis(paren_content):
            title_section = title_section[: trailing_paren_match.start()].strip()

    return title_section


def split_title_parts(title_section: str) -> List[str]:
    """Splits multi-language or alternate title sections while preserving embedded slashes like 'Face/Off'."""
    parts = re.split(r"\s+/\s+|\s+/\s*|\s*/\s+", title_section)
    return [p.strip(" -") for p in parts if p.strip(" -")]


def cleanup_title_part(part: str, *, remove_series_markers: bool) -> str:
    cleaned = re.sub(r"\s+", " ", part).strip(" -")
    trailing_paren_match = re.search(r"\s*(\([^)]*\))$", cleaned)
    if trailing_paren_match:
        if is_metadata_parenthesis(trailing_paren_match.group(1)):
            cleaned = cleaned[: trailing_paren_match.start()].strip(" -")

    if remove_series_markers:
        cleaned = re.sub(
            r"[\s,.-]+(?:s\d{1,2}(?:e\d{1,2})?|season\s*\d+|episodes?\b|сери[яи]\b|сезон\b).*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" -")

    return cleaned


def looks_like_series(text: str) -> bool:
    """Detects if text contains unambiguous series markers without false positives on movie titles."""
    return bool(SERIES_MARKER_PATTERN.search(text))


def parse_movie_title(parts: List[str]) -> Tuple[str, List[str]]:
    candidates = []
    reasons = []
    for part in parts:
        if is_part_series_marker(part):
            continue
        cleaned = cleanup_title_part(part, remove_series_markers=True)
        if cleaned:
            candidates.append(cleaned)

    latin_match = next((part for part in candidates if is_latin_candidate(part)), "")
    if latin_match:
        reasons.append("latin_candidate_selected")
        return latin_match, reasons

    numeric_match = next((part for part in candidates if is_numeric_candidate(part)), "")
    if numeric_match:
        reasons.append("numeric_candidate_selected")
        return numeric_match, reasons

    if candidates:
        first = candidates[0]
        if re.search(r"[а-яА-ЯёЁ]", first):
            reasons.append("cyrillic_candidate_selected")
        elif not re.search(r"[a-zA-Z]", first):
            reasons.append("numeric_candidate_selected")
        return first, reasons

    reasons.append("no_title_candidate")
    return "", reasons


def parse_series_title(parts: List[str]) -> Tuple[str, List[str]]:
    candidates = []
    reasons = []
    for part in parts:
        if is_part_series_marker(part):
            continue
        cleaned = cleanup_title_part(part, remove_series_markers=False)
        if cleaned:
            candidates.append(cleaned)

    latin_match = next((part for part in candidates if is_latin_candidate(part)), "")
    if latin_match:
        reasons.append("latin_candidate_selected")
        return latin_match, reasons

    numeric_match = next((part for part in candidates if is_numeric_candidate(part)), "")
    if numeric_match:
        reasons.append("numeric_candidate_selected")
        return numeric_match, reasons

    if candidates:
        first = candidates[0]
        if re.search(r"[а-яА-ЯёЁ]", first):
            reasons.append("cyrillic_candidate_selected")
        elif not re.search(r"[a-zA-Z]", first):
            reasons.append("numeric_candidate_selected")
        return first, reasons

    reasons.append("no_title_candidate")
    return "", reasons


def extract_video_tags(clean_title: str, video_settings: Dict[str, Any]) -> Tuple[str, str]:
    q_list = video_settings.get("quality_tags") or DEFAULT_QUALITY_TAGS
    r_list = video_settings.get("rip_tags") or DEFAULT_RIP_TAGS
    lowered = clean_title.lower()

    sorted_q = sorted(q_list, key=len, reverse=True)
    sorted_r = sorted(r_list, key=len, reverse=True)

    quality = next((q for q in sorted_q if q.lower() in lowered), "")
    rip_type = next((r for r in sorted_r if r.lower() in lowered), "")
    return quality, rip_type


def parse_rutracker_title(
    raw_title: str,
    *,
    content_type: Optional[str] = None,
    video_settings: Optional[Dict[str, Any]] = None,
) -> ParsedTitle:
    if not raw_title or not isinstance(raw_title, str) or not raw_title.strip():
        return ParsedTitle(
            title="",
            year=None,
            is_series=False,
            quality="",
            rip_type="",
            confidence=0.0,
            reasons=("empty_raw_title",),
        )

    reasons: List[str] = []
    clean = re.sub(r"^\[.*?\]\s*", "", raw_title).strip()
    if not clean:
        return ParsedTitle(
            title="",
            year=None,
            is_series=False,
            quality="",
            rip_type="",
            confidence=0.0,
            reasons=("empty_raw_title",),
        )

    year, year_reason = extract_year(clean)
    if year_reason:
        reasons.append(year_reason)

    title_section = extract_title_section(clean)
    parts = split_title_parts(title_section)

    normalized_type = (content_type or "").lower().strip()
    if normalized_type == "movie":
        title, title_reasons = parse_movie_title(parts)
        is_series = False
        reasons.extend(title_reasons)
        reasons.append("feed_type_authoritative_movie")
    elif normalized_type == "series":
        title, title_reasons = parse_series_title(parts)
        is_series = True
        reasons.extend(title_reasons)
        reasons.append("feed_type_authoritative_series")
    else:
        series_detected = looks_like_series(clean)
        if series_detected:
            title, title_reasons = parse_series_title(parts)
            is_series = True
            reasons.extend(title_reasons)
            reasons.append("series_inferred_from_markers")
        else:
            title, title_reasons = parse_movie_title(parts)
            is_series = False
            reasons.extend(title_reasons)

    if "/" in title:
        reasons.append("embedded_slash_preserved")

    quality, rip_type = extract_video_tags(clean, video_settings or {})

    # Calculate confidence score
    if not title:
        confidence = 0.0
    else:
        if "latin_candidate_selected" in reasons:
            confidence = 0.95
        elif "cyrillic_candidate_selected" in reasons:
            confidence = 0.85
        elif "numeric_candidate_selected" in reasons:
            confidence = 0.80
        else:
            confidence = 0.70

        if year:
            confidence = min(1.0, confidence + 0.05)
        elif year_reason == "invalid_year_range":
            confidence = min(0.50, confidence)
        elif year_reason == "year_missing":
            confidence = max(0.0, confidence - 0.15)

    return ParsedTitle(
        title=title,
        year=year,
        is_series=is_series,
        quality=quality,
        rip_type=rip_type,
        confidence=confidence,
        reasons=tuple(reasons),
    )

