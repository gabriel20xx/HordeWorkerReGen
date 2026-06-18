"""Regression tests for _reap_orphaned_in_progress_jobs.

An in-progress job whose handling process died / was replaced / hung before completing a step
(common shortly after startup) must be faulted so the inference slot is freed and shutdown can
complete instead of hanging forever on "Finishing current jobs...".
"""

from unittest.mock import MagicMock

from horde_worker_regen.process_management.messages import HordeProcessState
from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager


def _job(job_id: str) -> MagicMock:
    job = MagicMock()
    job.id_ = job_id  # plain string id; _is_same_job compares ids by equality
    return job


def _process(state: HordeProcessState, last_job, *, alive: bool) -> MagicMock:
    p = MagicMock()
    p.last_process_state = state
    p.last_job_referenced = last_job
    # Drive is_process_alive() via the real method using mp_process.is_alive() + state.
    p.mp_process.is_alive.return_value = alive
    # Bind the real is_process_alive so state-based logic is exercised.
    from horde_worker_regen.process_management.process_manager import HordeProcessInfo

    p.is_process_alive = HordeProcessInfo.is_process_alive.__get__(p, HordeProcessInfo)
    return p


def _manager(jobs_in_progress, processes, *, shutting_down=False, now=1000.0):
    mgr = MagicMock()
    mgr.jobs_in_progress = list(jobs_in_progress)
    mgr._process_map = {i: p for i, p in enumerate(processes)}
    mgr._job_orphan_since = {}
    mgr._shutting_down = shutting_down
    mgr.MAX_JOB_RETRIES = 1
    mgr.jobs_lookup = {}
    # Bind the real helpers under test.
    mgr._is_same_job = HordeWorkerProcessManager._is_same_job
    mgr._ORPHANED_JOB_GRACE_SECONDS = HordeWorkerProcessManager._ORPHANED_JOB_GRACE_SECONDS
    return mgr


def _reap(mgr):
    return HordeWorkerProcessManager._reap_orphaned_in_progress_jobs.__get__(
        mgr,
        HordeWorkerProcessManager,
    )()


class TestOrphanReaper:
    def test_not_faulted_while_live_process_handles_job(self) -> None:
        """A job actively handled by a live INFERENCE_PROCESSING process is never faulted."""
        job = _job("job-a")
        proc = _process(HordeProcessState.INFERENCE_PROCESSING, job, alive=True)
        mgr = _manager([job], [proc])

        result = _reap(mgr)

        assert result is False
        mgr.handle_job_fault.assert_not_called()

    def test_grace_period_before_faulting_orphan(self) -> None:
        """An orphaned job is not faulted on first sighting (grace period)."""
        job = _job("job-a")
        # Process that ended (PROCESS_ENDING => not alive) and no longer references the job.
        dead = _process(HordeProcessState.PROCESS_ENDING, None, alive=False)
        mgr = _manager([job], [dead])

        result = _reap(mgr)

        assert result is False
        mgr.handle_job_fault.assert_not_called()
        # It is now being tracked as orphaned.
        assert "job-a" in mgr._job_orphan_since

    def test_orphan_faulted_after_grace(self) -> None:
        """After the grace period, an orphaned in-progress job is faulted (re-queued in normal op)."""
        job = _job("job-a")
        dead = _process(HordeProcessState.PROCESS_ENDING, None, alive=False)
        mgr = _manager([job], [dead])
        # Pretend it was first seen orphaned well beyond the grace window.
        mgr._job_orphan_since["job-a"] = 0.0  # far in the past relative to time.time()

        result = _reap(mgr)

        assert result is True
        mgr.handle_job_fault.assert_called_once()
        _, kwargs = mgr.handle_job_fault.call_args
        assert kwargs.get("faulted_job") is job
        # Normal operation => retry path (retry_skipped not forced).
        assert kwargs.get("retry_skipped") in (None, False)

    def test_orphan_permanently_faulted_during_shutdown(self) -> None:
        """During shutdown the orphan is permanently faulted (retry_skipped=True) so it can't hang shutdown."""
        job = _job("job-a")
        job_info = MagicMock()
        job_info.retry_count = 0
        dead = _process(HordeProcessState.PROCESS_ENDING, None, alive=False)
        mgr = _manager([job], [dead], shutting_down=True)
        mgr.jobs_lookup = {job: job_info}
        mgr._job_orphan_since["job-a"] = 0.0

        result = _reap(mgr)

        assert result is True
        mgr.handle_job_fault.assert_called_once()
        _, kwargs = mgr.handle_job_fault.call_args
        assert kwargs.get("retry_skipped") is True
        # retry_count was forced to MAX so handle_job_fault permanently faults rather than retries.
        assert job_info.retry_count == mgr.MAX_JOB_RETRIES

    def test_job_handled_by_ending_process_is_orphan(self) -> None:
        """A job still referenced only by a PROCESS_ENDING (not-alive) process is treated as orphaned."""
        job = _job("job-a")
        ending = _process(HordeProcessState.PROCESS_ENDING, job, alive=False)
        mgr = _manager([job], [ending])
        mgr._job_orphan_since["job-a"] = 0.0

        result = _reap(mgr)

        assert result is True
        mgr.handle_job_fault.assert_called_once()
