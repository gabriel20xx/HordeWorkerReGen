"""Tests for job state transitions between INFERENCE_PROCESSING, INFERENCE_POST_PROCESSING,
and SAFETY_EVALUATING, and correctness of handle_job_fault cleanup."""

from unittest.mock import MagicMock

import pytest

from horde_worker_regen.process_management.messages import HordeProcessState


def _make_mock_job(job_id: str = "a1b2c3d4") -> MagicMock:
    """Return a minimal mock ImageGenerateJobPopResponse."""
    job = MagicMock()
    job.id_ = MagicMock()
    job.id_.root = f"{job_id}-1234-5678-abcd-ef0123456789"
    # Make id_ compare equal to itself by value via __eq__
    job.id_.__eq__ = lambda _self, other: _self.root == getattr(other, "root", None)
    job.model = "test_model"
    job.payload = MagicMock()
    job.payload.n_iter = 1
    return job


def _make_horde_job_info(job: MagicMock, job_id_str: str) -> MagicMock:
    """Return a minimal mock HordeJobInfo wrapping *job*."""
    info = MagicMock()
    info.sdk_api_job_info = job
    info.sdk_api_job_info.id_ = MagicMock()
    info.sdk_api_job_info.id_.root = job_id_str
    return info


def _make_process_info(state: HordeProcessState) -> MagicMock:
    """Return a minimal mock HordeProcessInfo in the given state."""
    process = MagicMock()
    process.last_process_state = state
    process.process_id = 99
    return process


class TestHandleJobFaultStatePhase:
    """Tests for the fault-phase classification in handle_job_fault."""

    def _invoke_handle_job_fault(
        self,
        process_state: HordeProcessState,
    ) -> str | None:
        """Call handle_job_fault with a process in *process_state* and return fault_phase."""
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        # Capture the fault_phase passed to _record_faulted_job_history
        recorded_phase: list[str | None] = []

        mock_manager = MagicMock()
        mock_manager.MAX_JOB_RETRIES = 0  # skip retry path so we reach fault_phase logic
        mock_manager.jobs_pending_inference = []
        mock_manager.jobs_in_progress = []
        mock_manager.jobs_pending_safety_check = []
        mock_manager.jobs_being_safety_checked = []
        mock_manager.jobs_pending_submit = []
        mock_manager._skipped_line_next_job_and_process = None
        mock_manager._failed_models = {}

        def capture_record(faulted_job, phase=None):
            recorded_phase.append(phase)

        mock_manager._record_faulted_job_history.side_effect = capture_record

        faulted_job = _make_mock_job()
        job_info = MagicMock()
        job_info.retry_count = 0
        mock_manager.jobs_lookup = {faulted_job: job_info}

        process_info = _make_process_info(process_state)

        bound = HordeWorkerProcessManager.handle_job_fault.__get__(mock_manager, HordeWorkerProcessManager)
        bound(faulted_job=faulted_job, process_info=process_info)

        return recorded_phase[0] if recorded_phase else None

    def test_fault_phase_inference_processing(self) -> None:
        """INFERENCE_PROCESSING maps to 'During Inference'."""
        phase = self._invoke_handle_job_fault(HordeProcessState.INFERENCE_PROCESSING)
        assert phase == "During Inference"

    def test_fault_phase_inference_starting(self) -> None:
        """INFERENCE_STARTING maps to 'During Inference'."""
        phase = self._invoke_handle_job_fault(HordeProcessState.INFERENCE_STARTING)
        assert phase == "During Inference"

    def test_fault_phase_inference_post_processing(self) -> None:
        """INFERENCE_POST_PROCESSING maps to 'Post Processing'."""
        phase = self._invoke_handle_job_fault(HordeProcessState.INFERENCE_POST_PROCESSING)
        assert phase == "Post Processing"

    def test_fault_phase_safety_evaluating(self) -> None:
        """SAFETY_EVALUATING maps to 'Safety Check'."""
        phase = self._invoke_handle_job_fault(HordeProcessState.SAFETY_EVALUATING)
        assert phase == "Safety Check"

    def test_fault_phase_safety_starting(self) -> None:
        """SAFETY_STARTING must also map to 'Safety Check' (not fall through to default).

        This was previously broken: the condition checked SAFETY_EVALUATING twice instead
        of checking SAFETY_EVALUATING and SAFETY_STARTING.
        """
        phase = self._invoke_handle_job_fault(HordeProcessState.SAFETY_STARTING)
        assert phase == "Safety Check", (
            f"Expected 'Safety Check' for SAFETY_STARTING, got {phase!r}. "
            "The duplicate SAFETY_EVALUATING condition was not replaced with "
            "the SAFETY_EVALUATING | SAFETY_STARTING pair."
        )


class TestHandleJobFaultSafetyListCleanup:
    """Tests that handle_job_fault removes the faulted job from safety-related lists."""

    def _build_manager_with_safety_lists(
        self,
        *,
        in_pending: bool = False,
        in_being_checked: bool = False,
    ) -> tuple:
        """Return (mock_manager, faulted_job) with the faulted job optionally placed
        in jobs_pending_safety_check and/or jobs_being_safety_checked."""
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        job_id = "deadbeef"
        faulted_job = _make_mock_job(job_id)
        faulted_job.id_.root = f"{job_id}-0000-0000-0000-000000000000"

        # Build a HordeJobInfo-like mock whose sdk_api_job_info.id_ matches faulted_job.id_
        def _make_matching_info() -> MagicMock:
            info = MagicMock()
            info.sdk_api_job_info = MagicMock()
            info.sdk_api_job_info.id_ = faulted_job.id_
            return info

        job_info = MagicMock()
        job_info.retry_count = 0

        mock_manager = MagicMock()
        mock_manager.MAX_JOB_RETRIES = 0
        mock_manager.jobs_lookup = {faulted_job: job_info}
        mock_manager.jobs_pending_inference = []
        mock_manager.jobs_in_progress = []
        mock_manager.jobs_pending_safety_check = [_make_matching_info()] if in_pending else []
        mock_manager.jobs_being_safety_checked = [_make_matching_info()] if in_being_checked else []
        mock_manager.jobs_pending_submit = []
        mock_manager._skipped_line_next_job_and_process = None
        mock_manager._failed_models = {}

        return mock_manager, faulted_job, HordeWorkerProcessManager

    def test_removes_from_jobs_pending_safety_check(self) -> None:
        """When a job faults while in jobs_pending_safety_check it must be removed."""
        mock_manager, faulted_job, Manager = self._build_manager_with_safety_lists(in_pending=True)

        assert len(mock_manager.jobs_pending_safety_check) == 1

        bound = Manager.handle_job_fault.__get__(mock_manager, Manager)
        bound(faulted_job=faulted_job, process_info=None)

        assert len(mock_manager.jobs_pending_safety_check) == 0, (
            "handle_job_fault must remove the job from jobs_pending_safety_check. "
            "The previously dead-code guard (faulted_job in jobs_pending_safety_check) "
            "caused this cleanup to never execute."
        )

    def test_removes_from_jobs_being_safety_checked(self) -> None:
        """When a job faults while in jobs_being_safety_checked it must be removed.

        This was previously missing: handle_job_fault cleaned up jobs_pending_safety_check
        (though via dead code) but had no code at all for jobs_being_safety_checked.
        A job stuck in jobs_being_safety_checked would prevent clean shutdown because
        is_time_for_shutdown() gates on that list being empty.
        """
        mock_manager, faulted_job, Manager = self._build_manager_with_safety_lists(in_being_checked=True)

        assert len(mock_manager.jobs_being_safety_checked) == 1

        bound = Manager.handle_job_fault.__get__(mock_manager, Manager)
        bound(faulted_job=faulted_job, process_info=None)

        assert len(mock_manager.jobs_being_safety_checked) == 0, (
            "handle_job_fault must remove the job from jobs_being_safety_checked. "
            "Without this, a crashed safety process leaves the job there forever, "
            "blocking is_time_for_shutdown()."
        )

    def test_removes_from_both_safety_lists(self) -> None:
        """Defensive: if a job somehow appears in both safety lists, both are cleaned."""
        mock_manager, faulted_job, Manager = self._build_manager_with_safety_lists(
            in_pending=True,
            in_being_checked=True,
        )

        bound = Manager.handle_job_fault.__get__(mock_manager, Manager)
        bound(faulted_job=faulted_job, process_info=None)

        assert len(mock_manager.jobs_pending_safety_check) == 0
        assert len(mock_manager.jobs_being_safety_checked) == 0

    def test_no_error_when_job_not_in_safety_lists(self) -> None:
        """handle_job_fault must not raise when the job is in neither safety list."""
        mock_manager, faulted_job, Manager = self._build_manager_with_safety_lists()

        bound = Manager.handle_job_fault.__get__(mock_manager, Manager)
        # Should not raise
        bound(faulted_job=faulted_job, process_info=None)


class TestInferenceToPostProcessingTransition:
    """Tests for the state-machine transitions from INFERENCE_PROCESSING to
    INFERENCE_POST_PROCESSING and then into the safety-evaluation pipeline."""

    def test_is_process_busy_during_inference_post_processing(self) -> None:
        """A process in INFERENCE_POST_PROCESSING must be considered busy."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.last_process_state = HordeProcessState.INFERENCE_POST_PROCESSING
        mock_info.is_process_busy = HordeProcessInfo.is_process_busy.__get__(mock_info, HordeProcessInfo)

        assert mock_info.is_process_busy() is True, (
            "A process in INFERENCE_POST_PROCESSING must be considered busy"
        )

    def test_is_process_busy_during_safety_evaluating(self) -> None:
        """A process in SAFETY_EVALUATING must be considered busy."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.last_process_state = HordeProcessState.SAFETY_EVALUATING
        mock_info.is_process_busy = HordeProcessInfo.is_process_busy.__get__(mock_info, HordeProcessInfo)

        assert mock_info.is_process_busy() is True

    def test_is_process_busy_during_inference_processing(self) -> None:
        """A process in INFERENCE_PROCESSING must be considered busy."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        mock_info.is_process_busy = HordeProcessInfo.is_process_busy.__get__(mock_info, HordeProcessInfo)

        assert mock_info.is_process_busy() is True

    def test_cannot_accept_job_during_inference_post_processing(self) -> None:
        """A process in INFERENCE_POST_PROCESSING must NOT be able to accept a new job."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.last_process_state = HordeProcessState.INFERENCE_POST_PROCESSING
        mock_info.can_accept_job = HordeProcessInfo.can_accept_job.__get__(mock_info, HordeProcessInfo)

        assert mock_info.can_accept_job() is False, (
            "A process in INFERENCE_POST_PROCESSING must not accept new jobs; "
            "it still holds the VAE decode semaphore."
        )

    def test_cannot_accept_job_during_inference_processing(self) -> None:
        """A process in INFERENCE_PROCESSING must NOT be able to accept a new job."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        mock_info.can_accept_job = HordeProcessInfo.can_accept_job.__get__(mock_info, HordeProcessInfo)

        assert mock_info.can_accept_job() is False

    def test_on_process_state_change_resets_progress_on_inference_complete(self) -> None:
        """INFERENCE_COMPLETE must pin progress at 100% and reset heartbeat state."""
        import time

        from horde_worker_regen.process_management.process_manager import ProcessMap

        process_map = ProcessMap()
        mock_info = MagicMock()
        mock_info.last_process_state = HordeProcessState.INFERENCE_POST_PROCESSING
        mock_info.last_heartbeat_percent_complete = 80
        mock_info.last_heartbeat_delta = 0.0
        mock_info.last_heartbeat_timestamp = time.time()
        mock_info.heartbeats_inference_steps = 5
        mock_info.last_progress_timestamp = time.time()
        mock_info.last_progress_value = 80
        mock_info.last_inference_step_timestamp = None
        mock_info.last_received_timestamp = time.time()
        process_map[0] = mock_info

        process_map.on_process_state_change(process_id=0, new_state=HordeProcessState.INFERENCE_COMPLETE)

        assert mock_info.last_process_state == HordeProcessState.INFERENCE_COMPLETE
        assert mock_info.last_heartbeat_percent_complete == 100, (
            "Progress must be pinned at 100% when INFERENCE_COMPLETE is received"
        )

    def test_on_process_state_change_does_not_reset_on_inference_post_processing(self) -> None:
        """Transitioning to INFERENCE_POST_PROCESSING must NOT reset the heartbeat state.

        The process is mid-inference; discarding its progress data would break stall
        detection.  The heartbeat state is only reset on inference completion or start.
        """
        import time

        from horde_worker_regen.process_management.process_manager import ProcessMap

        process_map = ProcessMap()
        mock_info = MagicMock()
        mock_info.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        mock_info.last_heartbeat_percent_complete = 70
        mock_info.last_heartbeat_delta = 0.0
        original_ts = time.time() - 5.0
        mock_info.last_heartbeat_timestamp = original_ts
        mock_info.heartbeats_inference_steps = 10
        mock_info.last_progress_timestamp = original_ts
        mock_info.last_progress_value = 70
        mock_info.last_inference_step_timestamp = original_ts
        mock_info.last_received_timestamp = original_ts
        process_map[0] = mock_info

        process_map.on_process_state_change(
            process_id=0, new_state=HordeProcessState.INFERENCE_POST_PROCESSING
        )

        assert mock_info.last_process_state == HordeProcessState.INFERENCE_POST_PROCESSING
        # heartbeats_inference_steps and last_progress_value must NOT be zeroed/cleared
        assert mock_info.heartbeats_inference_steps == 10, (
            "heartbeats_inference_steps must not be reset on INFERENCE_POST_PROCESSING"
        )
        assert mock_info.last_progress_value == 70, (
            "last_progress_value must not be reset on INFERENCE_POST_PROCESSING"
        )

    def test_is_stuck_on_inference_returns_false_for_post_processing(self) -> None:
        """is_stuck_on_inference() must return False for INFERENCE_POST_PROCESSING.

        Post-processing stall detection is handled by replace_hung_processes() via a
        separate timeout path, not by is_stuck_on_inference().
        """
        import time

        from horde_worker_regen.process_management.process_manager import ProcessMap

        process_map = ProcessMap()
        mock_info = MagicMock()
        mock_info.last_process_state = HordeProcessState.INFERENCE_POST_PROCESSING
        # Make it appear very stale so a true INFERENCE_PROCESSING check would trigger
        mock_info.last_heartbeat_timestamp = time.time() - 9999
        mock_info.last_received_timestamp = time.time() - 9999
        mock_info.last_progress_timestamp = time.time() - 9999
        mock_info.last_progress_value = 50
        mock_info.last_inference_step_timestamp = time.time() - 9999
        mock_info.heartbeats_inference_steps = 0
        process_map[0] = mock_info

        result = process_map.is_stuck_on_inference(process_id=0, inference_step_timeout=60)
        assert result is False, (
            "is_stuck_on_inference() must return False for INFERENCE_POST_PROCESSING; "
            "post-processing stall is detected separately."
        )
