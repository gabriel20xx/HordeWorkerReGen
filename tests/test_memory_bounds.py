"""Regression tests for the process manager's memory-bounding behaviour.

These guard against unbounded RAM growth in a long-running worker:
- API worker messages must be evicted when expired and capped in count.
- ``_purge_jobs`` must not orphan bookkeeping entries (``jobs_lookup`` et al.) for jobs it
  drops — those entries retain base64 image results and downloaded source images.
"""

from collections import deque
from unittest.mock import MagicMock

from horde_worker_regen.process_management.process_manager import (
    APIWorkerMessage,
    HordeWorkerProcessManager,
)


def _api_message(message_id: str, expiry: str | None) -> APIWorkerMessage:
    return APIWorkerMessage(
        message_id=message_id,
        message_text="text",
        message_origin=None,
        message_expiry=expiry,
    )


def _bind(mgr: MagicMock, method_name: str):
    return getattr(HordeWorkerProcessManager, method_name).__get__(mgr, HordeWorkerProcessManager)


class TestPruneApiMessages:
    def test_expired_messages_are_evicted(self) -> None:
        """Messages past their expiry are removed; future/unparseable/None expiries are kept."""
        mgr = MagicMock()
        mgr._MAX_API_MESSAGES_KEPT = 50
        mgr._api_messages_received = {
            "expired": _api_message("expired", "2000-01-01T00:00:00Z"),
            "future": _api_message("future", "2099-01-01T00:00:00+00:00"),
            "unparseable": _api_message("unparseable", "whenever"),
            "no-expiry": _api_message("no-expiry", None),
        }

        _bind(mgr, "_prune_api_messages")()

        assert set(mgr._api_messages_received) == {"future", "unparseable", "no-expiry"}

    def test_naive_expiry_treated_as_utc(self) -> None:
        """An expiry without timezone info must still be comparable (assumed UTC)."""
        mgr = MagicMock()
        mgr._MAX_API_MESSAGES_KEPT = 50
        mgr._api_messages_received = {
            "expired-naive": _api_message("expired-naive", "2000-01-01T00:00:00"),
        }

        _bind(mgr, "_prune_api_messages")()

        assert mgr._api_messages_received == {}

    def test_count_cap_evicts_oldest_first(self) -> None:
        """Beyond the cap, the oldest-inserted messages are evicted."""
        mgr = MagicMock()
        mgr._MAX_API_MESSAGES_KEPT = 3
        mgr._api_messages_received = {f"m{i}": _api_message(f"m{i}", None) for i in range(5)}

        _bind(mgr, "_prune_api_messages")()

        assert list(mgr._api_messages_received) == ["m2", "m3", "m4"]

    def test_empty_dict_is_a_noop(self) -> None:
        mgr = MagicMock()
        mgr._MAX_API_MESSAGES_KEPT = 3
        mgr._api_messages_received = {}

        _bind(mgr, "_prune_api_messages")()

        assert mgr._api_messages_received == {}


def _job(job_id: str) -> MagicMock:
    job = MagicMock()
    job.id_ = job_id
    return job


class TestPurgeJobsBookkeepingCleanup:
    def test_dropped_jobs_are_removed_from_all_tracking_structures(self) -> None:
        """Jobs _purge_jobs drops must not leak in jobs_lookup / timestamps / faults / timings.

        Leaked jobs_lookup entries retain HordeJobInfo objects that can hold base64 image
        results and downloaded source images, so repeated purge-recovery cycles would leak
        real memory. Jobs kept for retry must keep their bookkeeping.
        """
        kept_job = _job("kept")
        dropped_job = _job("dropped")  # retry_count == 0 → not kept for retry
        submitted_job = _job("submitted")  # sits in jobs_pending_submit, which gets cleared

        kept_info = MagicMock()
        kept_info.retry_count = 1
        dropped_info = MagicMock()
        dropped_info.retry_count = 0
        submitted_info = MagicMock()
        submitted_info.sdk_api_job_info = submitted_job

        mgr = MagicMock()
        mgr._shutting_down = False
        mgr.jobs_in_progress = []
        mgr.jobs_pending_inference = deque([kept_job, dropped_job])
        mgr.jobs_lookup = {kept_job: kept_info, dropped_job: dropped_info, submitted_job: submitted_info}
        mgr.job_pop_timestamps = {kept_job: 1.0, dropped_job: 2.0, submitted_job: 3.0}
        mgr._pending_completed_job_timings = {kept_job: {}, dropped_job: {}, submitted_job: {}}
        mgr.job_faults = {"kept": [], "dropped": [], "submitted": []}
        mgr.jobs_pending_safety_check = []
        mgr.jobs_being_safety_checked = []
        mgr.jobs_pending_submit = [submitted_info]
        mgr._skipped_line_next_job_and_process = None

        _bind(mgr, "_purge_jobs")()

        assert list(mgr.jobs_pending_inference) == [kept_job]
        assert set(mgr.jobs_lookup) == {kept_job}
        assert set(mgr.job_pop_timestamps) == {kept_job}
        assert set(mgr._pending_completed_job_timings) == {kept_job}
        assert set(mgr.job_faults) == {"kept"}
        assert mgr.jobs_pending_submit == []

    def test_shutdown_purge_clears_all_bookkeeping(self) -> None:
        """During shutdown everything is dropped, so no bookkeeping may survive."""
        job_a = _job("a")
        info_a = MagicMock()
        info_a.retry_count = 1

        mgr = MagicMock()
        mgr._shutting_down = True
        mgr.jobs_in_progress = []
        mgr.jobs_pending_inference = deque([job_a])
        mgr.jobs_lookup = {job_a: info_a}
        mgr.job_pop_timestamps = {job_a: 1.0}
        mgr._pending_completed_job_timings = {job_a: {}}
        mgr.job_faults = {"a": []}
        mgr.jobs_pending_safety_check = []
        mgr.jobs_being_safety_checked = []
        mgr.jobs_pending_submit = []
        mgr._skipped_line_next_job_and_process = None

        _bind(mgr, "_purge_jobs")()

        assert len(mgr.jobs_pending_inference) == 0
        assert mgr.jobs_lookup == {}
        assert mgr.job_pop_timestamps == {}
        assert mgr._pending_completed_job_timings == {}
        assert mgr.job_faults == {}
