import time
from typing import Dict, List, Optional, Set, Tuple

from .ids import normalize_title
from .models import ManualMapping, Occurrence, ParseLog, ScanRun, Title
from .repository import (
    ManualMappingRepository,
    OccurrenceRepository,
    ParseLogRepository,
    TitleRepository,
    merge_occurrences,
    merge_titles,
    occurrence_validation_fingerprint,
)


class ScanWriteBuffer:
    def __init__(
        self,
        *,
        title_repo: TitleRepository,
        occurrence_repo: OccurrenceRepository,
        parse_log_repo: Optional[ParseLogRepository] = None,
        manual_mapping_repo: Optional[ManualMappingRepository] = None,
        is_dry_run: bool = False,
        is_parse_only: bool = False,
    ) -> None:
        self.title_repo = title_repo
        self.occurrence_repo = occurrence_repo
        self.parse_log_repo = parse_log_repo
        self.manual_mapping_repo = manual_mapping_repo
        self.is_dry_run = is_dry_run
        self.is_parse_only = is_parse_only

        self._session_titles: Dict[str, Optional[Title]] = {}
        self._session_occurrences: Dict[Tuple[str, str], Optional[Occurrence]] = {}
        self._pending_parse_logs: List[ParseLog] = []
        self._pending_titles: Dict[str, Title] = {}
        self._pending_occurrences: Dict[Tuple[str, str], Occurrence] = {}
        self._pending_manual_mappings: Dict[str, ManualMapping] = {}
        self._manual_mappings_by_id: Dict[str, ManualMapping] = {}
        self._manual_mappings_by_raw_title: Dict[str, ManualMapping] = {}
        self._manual_mappings_by_parsed_title: Dict[str, ManualMapping] = {}
        self._run_written_title_ids: Set[str] = set()
        self._run_written_occurrence_keys: Set[Tuple[str, str]] = set()
        self._run_written_parse_log_ids: Set[str] = set()

    @property
    def pending_titles(self) -> Dict[str, Title]:
        return self._pending_titles

    @property
    def pending_occurrences(self) -> Dict[Tuple[str, str], Occurrence]:
        return self._pending_occurrences

    @property
    def pending_parse_logs(self) -> List[ParseLog]:
        return self._pending_parse_logs

    @property
    def pending_manual_mappings(self) -> Dict[str, ManualMapping]:
        return self._pending_manual_mappings

    @property
    def written_title_ids(self) -> Set[str]:
        return self._run_written_title_ids

    @property
    def written_occurrence_keys(self) -> Set[Tuple[str, str]]:
        return self._run_written_occurrence_keys

    @property
    def written_parse_log_ids(self) -> Set[str]:
        return self._run_written_parse_log_ids

    def load_manual_mappings(self) -> None:
        if not self.manual_mapping_repo:
            return
        mappings = self.manual_mapping_repo.get_all()
        for mapping in mappings:
            self._manual_mappings_by_id[mapping.id] = mapping
            if mapping.raw_title:
                self._manual_mappings_by_raw_title[mapping.raw_title.strip().lower()] = mapping
            if mapping.parsed_title:
                self._manual_mappings_by_parsed_title[normalize_title(mapping.parsed_title)] = mapping

    def find_manual_mapping(
        self,
        *,
        source_item_id: Optional[str] = None,
        legacy_item_id: Optional[str] = None,
        raw_title: Optional[str] = None,
        parsed_title: Optional[str] = None,
    ) -> Optional[ManualMapping]:
        mapping = (
            self._manual_mappings_by_id.get(source_item_id or "")
            or self._manual_mappings_by_id.get(legacy_item_id or "")
        )
        if mapping is not None and mapping.id not in self._pending_manual_mappings:
            return mapping
        if mapping is not None:
            return None
        if raw_title:
            mapping = self._manual_mappings_by_raw_title.get(raw_title.strip().lower())
            if mapping is not None and mapping.id not in self._pending_manual_mappings:
                return mapping
            if mapping is not None:
                return None
        if parsed_title:
            mapping = self._manual_mappings_by_parsed_title.get(normalize_title(parsed_title))
            if mapping is not None and mapping.id not in self._pending_manual_mappings:
                return mapping
        return None

    def consume_manual_mapping(self, manual_mapping: ManualMapping) -> None:
        if self.is_dry_run or not self.manual_mapping_repo:
            return
        self.manual_mapping_repo.delete(manual_mapping.id)
        if self._manual_mappings_by_id.get(manual_mapping.id) == manual_mapping:
            self._manual_mappings_by_id.pop(manual_mapping.id, None)
        if manual_mapping.raw_title:
            raw_key = manual_mapping.raw_title.strip().lower()
            if self._manual_mappings_by_raw_title.get(raw_key) == manual_mapping:
                self._manual_mappings_by_raw_title.pop(raw_key, None)
        if manual_mapping.parsed_title:
            parsed_key = normalize_title(manual_mapping.parsed_title)
            if self._manual_mappings_by_parsed_title.get(parsed_key) == manual_mapping:
                self._manual_mappings_by_parsed_title.pop(parsed_key, None)

    def get_title(self, title_id: str) -> Optional[Title]:
        if title_id in self._session_titles:
            return self._session_titles[title_id]
        title = self.title_repo.get(title_id)
        self._session_titles[title_id] = title
        return title

    def get_occurrence(self, title_id: str, occurrence_id: str) -> Optional[Occurrence]:
        key = (title_id, occurrence_id)
        if key in self._session_occurrences:
            return self._session_occurrences[key]
        occurrence = self.occurrence_repo.get(title_id, occurrence_id)
        self._session_occurrences[key] = occurrence
        return occurrence

    def stage_title_and_occurrence(
        self,
        title_id: str,
        title_record: Title,
        occurrence_id: str,
        occurrence_record: Occurrence,
        run: ScanRun,
    ) -> None:
        existing_title = self.get_title(title_id)
        if existing_title is None:
            run.titles_created += 1
            merged_title = title_record
        else:
            run.titles_updated += 1
            merged_title = merge_titles(existing_title, title_record)
        self._session_titles[title_id] = merged_title
        self._pending_titles[title_id] = merged_title
        self._run_written_title_ids.add(title_id)

        existing_occurrence = self.get_occurrence(title_id, occurrence_id)
        if existing_occurrence is None:
            run.occurrences_created += 1
            merged_occurrence = occurrence_record
            merged_title.ai_validated = False
            merged_title.ai_checked_at = None
        else:
            run.occurrences_updated += 1
            merged_occurrence = merge_occurrences(existing_occurrence, occurrence_record)
            if (
                occurrence_validation_fingerprint(existing_occurrence, existing_title)
                != occurrence_validation_fingerprint(occurrence_record, merged_title)
            ):
                merged_occurrence.validation_status = None
                merged_occurrence.validation_policy_version = None
                merged_occurrence.validation_reason = None
                merged_occurrence.validated_at = None
            if existing_occurrence.validation_status is not None and merged_occurrence.validation_status is None:
                merged_title.ai_validated = False
                merged_title.ai_checked_at = None
        occurrence_key = (title_id, occurrence_id)
        self._session_occurrences[occurrence_key] = merged_occurrence
        self._pending_occurrences[occurrence_key] = merged_occurrence
        self._run_written_occurrence_keys.add(occurrence_key)

    def stage_parse_log(self, log: ParseLog) -> None:
        self._run_written_parse_log_ids.add(log.id)
        if not self.parse_log_repo or self.is_dry_run:
            return
        self._pending_parse_logs.append(log)

    def stage_manual_mapping(self, manual_mapping: ManualMapping) -> None:
        self._pending_manual_mappings[manual_mapping.id] = manual_mapping

    def flush_parse_logs(self, section_timings: Optional[Dict[str, float]] = None) -> None:
        if (
            not self._pending_parse_logs
            or not self.parse_log_repo
            or self.is_dry_run
            or self.is_parse_only
        ):
            return
        t0 = time.perf_counter()
        self.parse_log_repo.add_many(self._pending_parse_logs)
        if section_timings is not None:
            section_timings["parse_log_write"] += time.perf_counter() - t0
        self._pending_parse_logs.clear()

    def flush_pending_db_upserts(self, section_timings: Optional[Dict[str, float]] = None) -> None:
        if self.is_dry_run:
            self._pending_titles.clear()
            self._pending_occurrences.clear()
            return

        t0 = time.perf_counter()
        if self._pending_titles:
            titles_to_upsert = list(self._pending_titles.items())
            self.title_repo.upsert_many(titles_to_upsert)
            self._pending_titles.clear()

        if self._pending_occurrences:
            occurrences_to_upsert = [
                (title_id, occurrence_id, occurrence)
                for (title_id, occurrence_id), occurrence in self._pending_occurrences.items()
            ]
            self.occurrence_repo.upsert_many(occurrences_to_upsert)
            self._pending_occurrences.clear()

        if self.manual_mapping_repo:
            for manual_mapping in list(self._pending_manual_mappings.values()):
                self.consume_manual_mapping(manual_mapping)
                self._pending_manual_mappings.pop(manual_mapping.id, None)

        if section_timings is not None:
            section_timings["db_upsert"] += time.perf_counter() - t0