import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


SERIES_KEYWORDS = [
    "сезон",
    "серии",
    "season",
    "series",
    "episodes",
    "серия",
]

SERIES_PATTERN = re.compile(
    r"\b(?:s\d{1,2}(?:e\d{1,2})?|season\s*\d+|episodes?\b|серия|серии|сезон)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedTitle:
    title: str
    year: Optional[str]
    is_series: bool
    quality: str
    rip_type: str


def is_latin_candidate(text: str) -> bool:
    if not text:
        return False

    has_latin = bool(re.search(r"[a-zA-Z0-9]", text))
    has_exotic = bool(re.search(r"[\u0590-\u05FF\u0600-\u06FF]", text))
    cyrillic_chars = len(re.findall(r"[а-яА-Я]", text))
    return has_latin and not has_exotic and cyrillic_chars < 3


def normalize_feed_definition(name: str, value: Any) -> Dict[str, Optional[str]]:
    if isinstance(value, str):
        return {"name": name, "url": value, "type": infer_feed_type(name)}

    if isinstance(value, dict):
        return {
            "name": value.get("name", name),
            "url": value.get("url"),
            "type": (value.get("type") or infer_feed_type(name)),
        }

    raise ValueError(f"Unsupported rss feed definition for '{name}'")


def iter_feed_definitions(rss_feeds: Dict[str, Any]) -> Iterable[Dict[str, Optional[str]]]:
    for name, value in rss_feeds.items():
        yield normalize_feed_definition(name, value)


def infer_feed_type(feed_name: str) -> Optional[str]:
    lowered = feed_name.lower()
    if "сериал" in lowered or "series" in lowered:
        return "series"
    if "филм" in lowered or "movie" in lowered:
        return "movie"
    return None


def parse_rutracker_title(
    raw_title: str,
    *,
    content_type: Optional[str] = None,
    video_settings: Optional[Dict[str, Any]] = None,
) -> ParsedTitle:
    clean = re.sub(r"^\[.*?\]\s*", "", raw_title).strip()
    year = extract_year(clean)
    title_section = extract_title_section(clean)
    parts = split_title_parts(title_section)

    normalized_type = (content_type or "").lower()
    if normalized_type == "movie":
        title = parse_movie_title(parts)
        is_series = False
    elif normalized_type == "series":
        title = parse_series_title(parts)
        is_series = True
    else:
        title = parse_series_title(parts) if looks_like_series(clean) else parse_movie_title(parts)
        is_series = looks_like_series(clean)

    quality, rip_type = extract_video_tags(clean, video_settings or {})
    return ParsedTitle(title=title, year=year, is_series=is_series, quality=quality, rip_type=rip_type)


def extract_year(clean_title: str) -> Optional[str]:
    year_match = re.search(r"\[(\d{4})", clean_title)
    if year_match:
        return year_match.group(1)

    title_match = re.search(r"\((\d{4})\)", clean_title)
    return title_match.group(1) if title_match else None


def extract_title_section(clean_title: str) -> str:
    title_section = clean_title.split("[", 1)[0].strip()
    return re.sub(r"\s*\([^)]*\)$", "", title_section).strip()


def split_title_parts(title_section: str) -> List[str]:
    return [part.strip(" -") for part in title_section.split("/") if part.strip()]


def parse_movie_title(parts: List[str]) -> str:
    candidates = []
    for part in parts:
        cleaned = cleanup_title_part(part, remove_series_markers=True)
        if cleaned:
            candidates.append(cleaned)

    latin_match = next((part for part in candidates if is_latin_candidate(part)), "")
    if latin_match:
        return latin_match

    return candidates[0] if candidates else ""


def parse_series_title(parts: List[str]) -> str:
    normalized_parts = []
    for part in parts:
        cleaned = cleanup_title_part(part, remove_series_markers=False)
        if cleaned:
            normalized_parts.append(cleaned)

    latin_match = next((part for part in normalized_parts if is_latin_candidate(part)), "")
    return latin_match or (normalized_parts[0] if normalized_parts else "")


def cleanup_title_part(part: str, *, remove_series_markers: bool) -> str:
    cleaned = re.sub(r"\s+", " ", part).strip(" -")
    cleaned = re.sub(r"\((?:\d{4}|[^)]*реж[^)]*)\)", "", cleaned, flags=re.IGNORECASE).strip(" -")

    if remove_series_markers:
        cleaned = re.sub(
            r"[\s,.-]+(?:s\d{1,2}(?:e\d{1,2})?|season\s*\d+|episodes?\b|серия|серии|сезон)\b.*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" -")

    return cleaned


def looks_like_series(text: str) -> bool:
    lowered = text.lower()
    if any(keyword in lowered for keyword in SERIES_KEYWORDS):
        return True
    return bool(SERIES_PATTERN.search(text))


def extract_video_tags(clean_title: str, video_settings: Dict[str, Any]) -> Tuple[str, str]:
    q_list = video_settings.get("quality_tags", [])
    r_list = video_settings.get("rip_tags", [])
    lowered = clean_title.lower()
    quality = next((q for q in q_list if q.lower() in lowered), "")
    rip_type = next((r for r in r_list if r.lower() in lowered), "")
    return quality, rip_type
