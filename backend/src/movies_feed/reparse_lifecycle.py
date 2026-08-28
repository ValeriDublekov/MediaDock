import copy
import datetime
import logging
import time
from typing import Any, Callable, Dict, Optional

from .models import ParseLog, ParseLogResolution, ScanRun
from .repository import ParseLogRepository

logger = logging.getLogger(__name__)


class ReparseLogLifecycle:
    """Owns same-log retry, terminal, and resolved state transitions."""

    def __init__(
        self,
        *,
        parse_log_repo: ParseLogRepository,
        stored_source_type: Callable[[ParseLog], Optional[str]],
        record_phase_error: Callable[[Optional[ScanRun], str], None],
        now: datetime.datetime,
        is_dry_run: bool,
    ) -> None:
        self.parse_log_repo = parse_log_repo
        self.stored_source_type = stored_source_type
        self.record_phase_error = record_phase_error
        self.now = now
        self.is_dry_run = is_dry_run

    def record_retry(
        self,
        log: ParseLog,
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
        reason: str,
        parsed_title: Optional[str] = None,
        parsed_year: Optional[int] = None,
        counted_as_skipped: bool = False,
    ) -> None:
        try:
            self.write(
                self.updated_log(
                    log,
                    state="retryable",
                    omdb_status="error",
                    ignored=True,
                    ignore_reason=reason,
                    parsed_title=parsed_title,
                    parsed_year=parsed_year,
                    trace_details={
                        "feedType": self.stored_source_type(log) or "unknown",
                        "reparseOutcome": "skipped" if counted_as_skipped else "retried",
                        "retryReason": reason,
                    },
                    resolution=None,
                ),
                section_timings,
            )
            if counted_as_skipped:
                stats["skipped"] += 1
            else:
                stats["retried"] += 1
        except Exception as exc:
            logger.warning("Could not persist reparse retry state (%s)", type(exc).__name__)
            self.record_phase_error(run, "AI reparse retry state persistence failed")
            stats["failed"] += 1

    def record_terminal(
        self,
        log: ParseLog,
        stats: Dict[str, int],
        *,
        run: Optional[ScanRun],
        section_timings: Optional[Dict[str, float]],
        reason: str,
        ignore_reason: str,
        parsed_title: Optional[str],
        parsed_year: Optional[int],
    ) -> None:
        try:
            self.write(
                self.updated_log(
                    log,
                    state="terminal",
                    omdb_status="found",
                    ignored=True,
                    ignore_reason=ignore_reason,
                    parsed_title=parsed_title,
                    parsed_year=parsed_year,
                    trace_details={
                        "feedType": self.stored_source_type(log) or "unknown",
                        "reparseOutcome": "skipped",
                        "terminalReason": reason,
                    },
                    resolution=ParseLogResolution(
                        resolved_at=self.now,
                        outcome="terminal",
                        reason=reason,
                    ),
                ),
                section_timings,
            )
            stats["skipped"] += 1
        except Exception as exc:
            logger.warning("Could not persist reparse terminal state (%s)", type(exc).__name__)
            self.record_phase_error(run, "AI reparse terminal state persistence failed")
            stats["failed"] += 1

    def write(
        self,
        log: ParseLog,
        section_timings: Optional[Dict[str, float]],
    ) -> None:
        if self.is_dry_run:
            return
        t0 = time.perf_counter()
        self.parse_log_repo.add(log)
        if section_timings is not None:
            section_timings["parse_log_write"] = section_timings.get("parse_log_write", 0.0) + (
                time.perf_counter() - t0
            )

    def updated_log(
        self,
        log: ParseLog,
        *,
        state: str,
        omdb_status: str,
        ignored: bool,
        ignore_reason: Optional[str],
        parsed_title: Optional[str],
        parsed_year: Optional[int],
        trace_details: Dict[str, Any],
        resolution: Optional[ParseLogResolution],
    ) -> ParseLog:
        context = copy.deepcopy(log.source_context)
        merged_trace = dict(log.trace_details) if isinstance(log.trace_details, dict) else {}
        merged_trace.update(trace_details)
        return ParseLog(
            id=log.id,
            raw_title=log.raw_title or (context.raw_title if context else "") or "",
            feed_name=log.feed_name or (context.source_feed_name if context else "") or "",
            parsed_successfully=log.parsed_successfully or bool(parsed_title),
            parsed_title=parsed_title or log.parsed_title,
            parsed_year=parsed_year if parsed_year is not None else log.parsed_year,
            omdb_status=omdb_status,
            ignored=ignored,
            ignore_reason=ignore_reason,
            processed_at=self.now,
            error_message=None if state == "resolved" else reason_message(ignore_reason),
            trace_details=merged_trace,
            decision=state,
            source_context=context,
            event_kind="source",
            retry_state=state,
            attempt_count=log.attempt_count + 1,
            last_attempt_at=self.now,
            resolution=resolution,
        )


def reason_message(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return None
    return f"Reparse retry: {reason}"[:256]
