"""Regression tests for get_next_job_and_process line-skipping when the head-of-queue job's
model is not loaded on any process.

These cover the startup stall where the worker has popped jobs and preloaded a model, but
inference never starts because the *head* of the queue references a different model that is not
yet on any process. Before the fix, get_next_job_and_process returned None in that situation
(leaving the already-preloaded process idle); it must instead line-skip to a pending job whose
model IS ready.
"""

from unittest.mock import MagicMock

from horde_sdk.ai_horde_api.apimodels import ImageGenerateJobPopResponse

from horde_worker_regen.process_management.messages import HordeProcessState
from horde_worker_regen.process_management.process_manager import (
    HordeProcessInfo,
    HordeWorkerProcessManager,
    NextJobAndProcess,
)


def _make_job(model: str, job_id: str, *, n_iter: int = 1) -> MagicMock:
    """Return a spec'd ImageGenerateJobPopResponse mock (passes NextJobAndProcess validation)."""
    job = MagicMock(spec=ImageGenerateJobPopResponse)
    job.model = model
    job.id_ = job_id
    job.payload = MagicMock()
    job.payload.n_iter = n_iter
    job.payload.loras = None
    return job


def _make_process(
    model: str | None,
    state: HordeProcessState,
    *,
    can_accept: bool,
    process_id: int,
) -> MagicMock:
    """Return a spec'd HordeProcessInfo mock with a controllable can_accept_job()."""
    proc = MagicMock(spec=HordeProcessInfo)
    proc.loaded_horde_model_name = model
    proc.last_process_state = state
    proc.process_id = process_id
    proc.can_accept_job.return_value = can_accept
    return proc


def _build_manager(
    *,
    jobs_pending: list,
    process_for_model: dict,
) -> MagicMock:
    """Build a MagicMock manager wired up just enough to run get_next_job_and_process."""
    mock_manager = MagicMock()
    mock_manager._skipped_line_next_job_and_process = None
    mock_manager.jobs_pending_inference = jobs_pending
    mock_manager.jobs_in_progress = []
    # Real ints / bools so comparisons in the method behave (not MagicMock truthiness).
    mock_manager.max_concurrent_inference_processes = 4
    mock_manager.post_process_job_overlap_allowed = False
    mock_manager._preload_delay_notified = False

    process_map = MagicMock()
    process_map.num_busy_with_post_processing.return_value = 0
    process_map.get_process_by_horde_model_name.side_effect = lambda m: process_for_model.get(m)
    mock_manager._process_map = process_map

    mock_manager.bridge_data.high_performance_mode = False
    mock_manager.bridge_data.moderate_performance_mode = False

    mock_manager._horde_model_map.is_model_loading.return_value = False
    return mock_manager


def _call(mock_manager: MagicMock, *, information_only: bool = False):
    bound = HordeWorkerProcessManager.get_next_job_and_process.__get__(
        mock_manager,
        HordeWorkerProcessManager,
    )
    return bound(information_only=information_only)


class TestHeadOfQueueLineSkip:
    """get_next_job_and_process must not stall behind an un-loaded head-of-queue model."""

    def test_skips_to_ready_job_when_head_model_has_no_process(self) -> None:
        """Head job's model is on no process; a later job's model IS preloaded -> line-skip to it."""
        job_a = _make_job("modelA", "aaaa-head")
        job_b = _make_job("modelB", "bbbb-ready")
        proc_b = _make_process(
            "modelB",
            HordeProcessState.MODEL_PRELOADED,
            can_accept=True,
            process_id=1,
        )

        mock_manager = _build_manager(
            jobs_pending=[job_a, job_b],
            process_for_model={"modelA": None, "modelB": proc_b},
        )

        result = _call(mock_manager)

        assert isinstance(result, NextJobAndProcess)
        assert result.next_job is job_b
        assert result.process_with_model is proc_b
        assert result.skipped_line is True
        assert result.skipped_line_for is job_a
        # The decision is cached for the immediately-following real start_inference call.
        assert mock_manager._skipped_line_next_job_and_process is result

    def test_returns_none_when_head_unloaded_and_no_other_job_ready(self) -> None:
        """Head model not loaded and nothing else ready -> None (and the missing-model path runs)."""
        job_a = _make_job("modelA", "aaaa-head")
        job_b = _make_job("modelB", "bbbb-not-ready")
        # modelB exists on a process but it cannot accept a job yet (still preloading).
        proc_b = _make_process(
            "modelB",
            HordeProcessState.MODEL_PRELOADING,
            can_accept=False,
            process_id=1,
        )

        mock_manager = _build_manager(
            jobs_pending=[job_a, job_b],
            process_for_model={"modelA": None, "modelB": proc_b},
        )

        result = _call(mock_manager)

        assert result is None
        # No line-skip candidate was found, so nothing was cached and the head job remains queued
        # (the missing-head-model recovery path runs internally and re-triggers its preload).
        assert mock_manager._skipped_line_next_job_and_process is None

    def test_normal_head_job_runs_without_skipping(self) -> None:
        """When the head job's own model is ready, it runs as-is (no line-skip)."""
        job_a = _make_job("modelA", "aaaa-head")
        proc_a = _make_process(
            "modelA",
            HordeProcessState.MODEL_PRELOADED,
            can_accept=True,
            process_id=0,
        )

        mock_manager = _build_manager(
            jobs_pending=[job_a],
            process_for_model={"modelA": proc_a},
        )

        result = _call(mock_manager)

        assert isinstance(result, NextJobAndProcess)
        assert result.next_job is job_a
        assert result.process_with_model is proc_a
        assert result.skipped_line is False
        assert result.skipped_line_for is None
