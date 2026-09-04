import datetime
import json
import unittest
from pathlib import Path
from typing import Any

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from movies_feed.firestore_codecs import (
    occurrence_from_dict,
    rss_snapshot_from_dict,
    rss_snapshot_item_from_dict,
    rss_snapshot_state_to_dict,
    title_from_dict,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "test-contracts" / "firestore" / "v1"


def _load_fixture(name: str) -> dict:
    with (FIXTURE_ROOT / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _as_python_document(document: dict, *timestamp_fields: str) -> dict:
    result = dict(document)
    for field_name in timestamp_fields:
        result[field_name] = datetime.datetime.fromisoformat(
            result[field_name].replace("Z", "+00:00")
        )
    return result


def _as_fixture_value(value: Any) -> Any:
    if isinstance(value, datetime.datetime):
        return value.astimezone(datetime.timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
    if isinstance(value, dict):
        return {key: _as_fixture_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_fixture_value(item) for item in value]
    return value


class FirestoreContractTests(unittest.TestCase):
    def test_title_serialization_matches_shared_fixture(self) -> None:
        fixture = _load_fixture("title.json")
        title = title_from_dict(
            _as_python_document(fixture, "firstSeenAt", "lastSeenAt", "updatedAt")
        )

        self.assertEqual(_as_fixture_value(title.to_dict()), fixture)

    def test_occurrence_serialization_matches_shared_fixture(self) -> None:
        fixture = _load_fixture("occurrence.json")
        occurrence = occurrence_from_dict(
            _as_python_document(fixture, "firstSeenAt", "lastSeenAt")
        )

        self.assertEqual(_as_fixture_value(occurrence.to_dict()), fixture)

    def test_rss_snapshot_state_serialization_matches_shared_fixture(self) -> None:
        fixture = _load_fixture("rss-snapshot-state.json")
        snapshot = rss_snapshot_from_dict(
            _as_python_document(fixture, "createdAt"),
            doc_id=fixture["snapshotId"],
        )

        self.assertEqual(_as_fixture_value(rss_snapshot_state_to_dict(snapshot)), fixture)

    def test_rss_snapshot_item_serialization_matches_shared_fixture(self) -> None:
        fixture = _load_fixture("rss-snapshot-item.json")
        item = rss_snapshot_item_from_dict(fixture)

        self.assertEqual(item.to_dict(), fixture)

    def test_missing_snapshot_ordering_field_fails_explicitly(self) -> None:
        fixture = _load_fixture("rss-snapshot-item.json")
        for field_name in ("groupOrder", "feedOrder", "entryOrder", "rssPosition"):
            with self.subTest(field_name=field_name):
                invalid_fixture = dict(fixture)
                del invalid_fixture[field_name]
                with self.assertRaises(KeyError):
                    rss_snapshot_item_from_dict(invalid_fixture)


if __name__ == "__main__":
    unittest.main()
