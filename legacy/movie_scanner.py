import feedparser
import requests
import json
import os
import sys
import logging
import time
from datetime import datetime, timedelta

from rutracker_parser import iter_feed_definitions, parse_rutracker_title


DATA_DIR = "data"
OUTPUT_DIR = "output"
REPORTS_DIR = os.path.join(OUTPUT_DIR, "reports")
TEMPLATES_DIR = "templates"

CONFIG_FILE = "config.json"
HISTORY_FILE = os.path.join(DATA_DIR, "scan_history.json")
DATA_FILE = os.path.join(DATA_DIR, "data_storage.json")
API_CACHE_FILE = os.path.join(DATA_DIR, "api_cache.json")
LOG_FILE = os.path.join(DATA_DIR, "scanner.log")


def ensure_directories():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)


ensure_directories()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setLevel(logging.ERROR)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

logger.addHandler(console_handler)
logger.addHandler(file_handler)

API_CACHE = {}


def load_api_cache():
    global API_CACHE
    if os.path.exists(API_CACHE_FILE):
        try:
            with open(API_CACHE_FILE, "r", encoding="utf-8") as f:
                API_CACHE = json.load(f)
                logger.info(f"API cache loaded: {len(API_CACHE)} entries")
        except Exception as e:
            logger.error(f"Error loading API cache: {e}")
            API_CACHE = {}


def save_api_cache():
    try:
        with open(API_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(API_CACHE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving API cache: {e}")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"{CONFIG_FILE} not found!")
        raise SystemExit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()

if CONFIG.get("cache", {}).get("enabled", True):
    load_api_cache()
    logger.info("API cache is enabled")
else:
    logger.info("API cache is disabled")


def get_movie_info(title, year):
    api_key = os.environ.get("OMDB_API_KEY") or CONFIG.get("omdb_api_key", "")
    cache_enabled = CONFIG.get("cache", {}).get("enabled", True)
    cache_days = CONFIG.get("cache", {}).get("cache_days", 5)
    cache_seconds = cache_days * 24 * 3600

    cache_key = f"{title}_{year}"
    if cache_enabled and cache_key in API_CACHE:
        cache_entry = API_CACHE[cache_key]
        age = time.time() - cache_entry.get("timestamp", 0)
        if age < cache_seconds:
            return cache_entry["data"]
        logger.debug(f"Cache expired: {title}")

    def make_request(request_title, request_year=None):
        params = {"apikey": api_key, "t": request_title}
        if request_year:
            params["y"] = request_year
        try:
            response = requests.get("http://www.omdbapi.com/", params=params, timeout=10)
            return response.json()
        except Exception as e:
            logger.error(f"API request failed for {request_title}: {e}")
            return None

    data = make_request(title, year)
    if not data or data.get("Response") == "False":
        if data and "limit reached" in data.get("Error", "").lower():
            return "LIMIT_REACHED"
        data = make_request(title)

    result = data if data and data.get("Response") == "True" else None
    if cache_enabled and result:
        API_CACHE[cache_key] = {"data": result, "timestamp": time.time()}
        save_api_cache()

    return result


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def load_database():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_scan_state(history, db):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-3000:], f)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)


def print_safe(line):
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write((line + "\n").encode("utf-8", errors="replace"))
    else:
        print(line.encode("utf-8", errors="replace").decode("utf-8"))


def get_feed_definitions_for_flag(flag_name):
    flag_index = sys.argv.index(flag_name)
    feed_path = None
    if flag_index + 1 < len(sys.argv) and not sys.argv[flag_index + 1].startswith("--"):
        feed_path = sys.argv[flag_index + 1]

    if feed_path:
        guessed_type = "series" if "series" in os.path.basename(feed_path).lower() else "movie"
        return [{
            "name": os.path.basename(feed_path),
            "url": feed_path,
            "type": guessed_type,
            "feed": feedparser.parse(feed_path),
        }]

    return list(iter_feed_definitions(CONFIG["rss_feeds"]))


def run_parser_test_mode():
    logger.info("=== PARSER TEST MODE (No API calls) ===")
    for feed_def in get_feed_definitions_for_flag("--test-parser"):
        logger.info(f"\nScanning: {feed_def['name']}")
        feed = feed_def.get("feed") or feedparser.parse(feed_def["url"])
        for entry in feed.entries:
            parsed = parse_rutracker_title(
                entry.title,
                content_type=feed_def.get("type"),
                video_settings=CONFIG.get("video_settings", {}),
            )
            print_safe(f"IN:  {entry.title[:90]}...")
            print_safe(
                f"OUT: Title: '{parsed.title}' | Year: {parsed.year} "
                f"| Series: {parsed.is_series} | Quality: {parsed.quality} | Rip: {parsed.rip_type}"
            )


def get_parse_issues(parsed):
    issues = []
    if not parsed.title:
        issues.append("missing title")
    if not parsed.year:
        issues.append("missing year")
    return issues


def run_parse_only_mode():
    logger.info("=== PARSE ONLY MODE (RSS + title parsing, no API calls) ===")
    total_entries = 0
    total_problems = 0

    for feed_def in get_feed_definitions_for_flag("--parse-only"):
        logger.info(f"\nScanning: {feed_def['name']}")
        feed = feed_def.get("feed") or feedparser.parse(feed_def["url"])
        feed_problems = 0

        if getattr(feed, "bozo", False):
            logger.warning(f"Feed parse warning for '{feed_def['name']}': {feed.bozo_exception}")

        for index, entry in enumerate(feed.entries, start=1):
            parsed = parse_rutracker_title(
                entry.title,
                content_type=feed_def.get("type"),
                video_settings=CONFIG.get("video_settings", {}),
            )
            issues = get_parse_issues(parsed)
            total_entries += 1

            if issues:
                feed_problems += 1
                total_problems += 1
                print_safe(
                    f"[{feed_def['name']}] #{index} PROBLEM | Title: '{parsed.title or '-'}' | "
                    f"Year: {parsed.year or '-'} | Issues: {', '.join(issues)} | Raw: {entry.title}"
                )
            else:
                print_safe(
                    f"[{feed_def['name']}] #{index} OK | Title: '{parsed.title}' | Year: {parsed.year}"
                )

        logger.info(
            f"Completed '{feed_def['name']}': parsed={len(feed.entries)} entries, problems={feed_problems}"
        )

    logger.info(f"Parse-only summary: parsed={total_entries} entries, problems={total_problems}")


def build_display_type(info, is_series):
    genre_info = info.get("Genre", "")
    if "Documentary" in genre_info:
        return "Documentary"
    if info.get("Type") == "series" or is_series:
        return "TV Series"
    return "Movie"


def is_excluded(info, excluded_countries, excluded_genres):
    country_info = info.get("Country", "")
    genre_info = info.get("Genre", "")
    countries = [country.strip() for country in country_info.split(",") if country.strip()]
    matched_country = None
    excluded_country_set = {country.lower() for country in excluded_countries}
    if countries and all(country.lower() in excluded_country_set for country in countries):
        matched_country = ", ".join(countries)
    matched_genre = next((g for g in excluded_genres if g.lower() in genre_info.lower()), None)
    return matched_country, matched_genre


def process_feed_entry(entry, feed_def, seen_in_db, history, db, today_str, excluded_countries, excluded_genres):
    if entry.id in history:
        return False

    parsed = parse_rutracker_title(
        entry.title,
        content_type=feed_def.get("type"),
        video_settings=CONFIG.get("video_settings", {}),
    )

    title = parsed.title
    year = parsed.year
    if not title or (title.lower(), year) in seen_in_db:
        history.append(entry.id)
        return False

    info = get_movie_info(title, year)
    if info == "LIMIT_REACHED":
        logger.warning(f"API limit reached while processing '{entry.title}' (parsed_title='{title}', year={year}).")
        return True

    if info:
        matched_country, matched_genre = is_excluded(info, excluded_countries, excluded_genres)
        if matched_country or matched_genre:
            reasons = []
            if matched_country:
                reasons.append(f"excluded_country='{matched_country}'")
            if matched_genre:
                reasons.append(f"excluded_genre='{matched_genre}'")
            logger.info(
                f"IGNORED: '{title}' year={year} | country='{info.get('Country', '')}' "
                f"genre='{info.get('Genre', '')}' | reason={', '.join(reasons)}"
            )
            history.append(entry.id)
            return False

        info.update(
            {
                "Link": entry.link,
                "Category": feed_def["name"],
                "DisplayType": build_display_type(info, parsed.is_series),
                "Quality": parsed.quality,
                "Rip": parsed.rip_type,
                "ScanDate": today_str,
            }
        )
        db[today_str].append(info)
        seen_in_db.add((title.lower(), info.get("Year")))
        logger.info(f" OK {title} ({info.get('imdbRating')})")
    else:
        logger.warning(f"IGNORED: parsed_title='{title}' year={year} | reason=omdb_no_match_or_error | '{entry.title}'")

    history.append(entry.id)
    return False


def apply_retention(db):
    cutoff = datetime.now() - timedelta(days=CONFIG.get("days_to_keep", 5))
    return {day: items for day, items in db.items() if datetime.strptime(day, "%Y-%m-%d") > cutoff}


def main():
    only_html = "--html" in sys.argv
    test_mode = "--test-parser" in sys.argv
    parse_only_mode = "--parse-only" in sys.argv

    if test_mode:
        run_parser_test_mode()
        return
    if parse_only_mode:
        run_parse_only_mode()
        return

    history = load_history()
    db = load_database()
    today_str = datetime.now().strftime("%Y-%m-%d")
    db.setdefault(today_str, [])

    seen_in_db = {(item["Title"].lower(), item.get("Year")) for date in db for item in db[date]}

    if not only_html:
        excluded_countries = CONFIG.get("filters", {}).get("excluded_countries", [])
        excluded_genres = CONFIG.get("filters", {}).get("excluded_genres", [])

        for feed_def in iter_feed_definitions(CONFIG["rss_feeds"]):
            logger.info(f"Processing: {feed_def['name']}...")
            feed = feedparser.parse(feed_def["url"])

            for entry in feed.entries:
                should_stop = process_feed_entry(
                    entry,
                    feed_def,
                    seen_in_db,
                    history,
                    db,
                    today_str,
                    excluded_countries,
                    excluded_genres,
                )
                if should_stop:
                    break

        db = apply_retention(db)
        save_scan_state(history, db)

    import report_gen

    report_gen.generate(db, CONFIG)


if __name__ == "__main__":
    main()
