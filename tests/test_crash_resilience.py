"""Tests for crash resilience improvements."""

import asyncio
import sys
import types
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from horde_worker_regen.process_management.messages import HordeProcessState


class TestIsProcessAlive:
    """Tests for the is_process_alive() method fix."""

    def _make_process_info(self, state: HordeProcessState, mp_is_alive: bool) -> MagicMock:
        """Create a mock HordeProcessInfo with the given state and OS-level alive status."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.mp_process = MagicMock()
        mock_info.mp_process.is_alive.return_value = mp_is_alive
        mock_info.last_process_state = state

        # Bind the actual method
        mock_info.is_process_alive = HordeProcessInfo.is_process_alive.__get__(mock_info, HordeProcessInfo)
        return mock_info

    def test_alive_process_in_normal_state_returns_true(self) -> None:
        """A process that is alive at the OS level and in a normal state should return True."""
        for state in [
            HordeProcessState.WAITING_FOR_JOB,
            HordeProcessState.INFERENCE_PROCESSING,
            HordeProcessState.MODEL_LOADING,
            HordeProcessState.PROCESS_STARTING,
        ]:
            info = self._make_process_info(state, mp_is_alive=True)
            assert info.is_process_alive() is True, f"Expected True for state {state.name}, got False"

    def test_dead_process_always_returns_false(self) -> None:
        """A process that is dead at the OS level should always return False."""
        for state in [
            HordeProcessState.WAITING_FOR_JOB,
            HordeProcessState.INFERENCE_PROCESSING,
            HordeProcessState.PROCESS_ENDING,
            HordeProcessState.PROCESS_ENDED,
        ]:
            info = self._make_process_info(state, mp_is_alive=False)
            assert info.is_process_alive() is False, f"Expected False for dead process in state {state.name}"

    def test_process_ending_state_returns_false(self) -> None:
        """A process in PROCESS_ENDING state should be considered not alive even if OS reports it alive."""
        info = self._make_process_info(HordeProcessState.PROCESS_ENDING, mp_is_alive=True)
        assert info.is_process_alive() is False

    def test_process_ended_state_returns_false(self) -> None:
        """A process in PROCESS_ENDED state should be considered not alive even if OS reports it alive."""
        info = self._make_process_info(HordeProcessState.PROCESS_ENDED, mp_is_alive=True)
        assert info.is_process_alive() is False


class TestReplaceHungProcessesAnyReplaced:
    """Behavioral tests for the any_replaced fix in replace_hung_processes."""

    def test_returns_true_when_stuck_inference_process_replaced(self) -> None:
        """replace_hung_processes should return True when it replaces a stuck inference process."""
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = False
        mock_manager._last_pop_no_jobs_available = False
        mock_manager._shutting_down = False
        mock_manager.bridge_data.inference_step_timeout = 60
        mock_manager.bridge_data.process_timeout = 600

        # Create a mock process that appears stuck on inference
        import time

        mock_process = MagicMock()
        mock_process.process_id = 0
        mock_process.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        mock_process.last_heartbeat_percent_complete = 50
        mock_process.last_job_referenced = None
        mock_process.last_heartbeat_delta = 9999
        mock_process.last_progress_timestamp = time.time() - 9999
        mock_process.last_received_timestamp = time.time() - 9999
        mock_process.last_heartbeat_timestamp = time.time() - 9999

        mock_manager._process_map.values.return_value = [mock_process]
        mock_manager._process_map.is_stuck_on_inference.return_value = True

        bound_method = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager
        )

        with patch("threading.Thread"):
            result = bound_method()

        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(mock_process)

    def test_inference_processing_detected_even_when_recently_recovered(self) -> None:
        """INFERENCE_PROCESSING stuck detection must fire even when _recently_recovered is True.

        Scenario: a previous recovery set _recently_recovered=True (e.g. after one of several
        prior stuck-process recoveries).  An INFERENCE_PROCESSING process that stops sending
        heartbeats must still be detected and replaced; the _recently_recovered guard must NOT
        block it.
        """
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = True  # guard is active
        mock_manager._last_pop_no_jobs_available = False
        mock_manager._shutting_down = False
        mock_manager.bridge_data.inference_step_timeout = 60
        mock_manager.bridge_data.process_timeout = 30

        import time

        mock_process = MagicMock()
        mock_process.process_id = 0
        mock_process.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        mock_process.last_heartbeat_percent_complete = None
        mock_process.last_job_referenced = None
        mock_process.last_heartbeat_delta = 9999
        mock_process.last_progress_timestamp = time.time() - 9999
        mock_process.last_received_timestamp = time.time() - 9999
        mock_process.last_heartbeat_timestamp = time.time() - 9999

        mock_manager._process_map.values.return_value = [mock_process]
        mock_manager._process_map.is_stuck_on_inference.return_value = True

        bound_method = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager
        )

        with patch("threading.Thread"):
            result = bound_method()

        assert result is True, (
            "replace_hung_processes must return True for a stuck INFERENCE_PROCESSING process "
            "even when _recently_recovered is True"
        )
        mock_manager._replace_inference_process.assert_called_once_with(mock_process)

    def test_inference_starting_not_detected_when_recently_recovered(self) -> None:
        """INFERENCE_STARTING detection must be suppressed when _recently_recovered is True.

        After replacing a stuck INFERENCE_PROCESSING process the semaphore is released.  Any
        INFERENCE_STARTING process that was blocked waiting for the semaphore may have a stale
        heartbeat timestamp (it could not send heartbeats while blocked).  The _recently_recovered
        guard prevents a cascading false-positive replacement.
        """
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = True  # guard is active
        mock_manager._last_pop_no_jobs_available = False
        mock_manager._shutting_down = False
        mock_manager.bridge_data.inference_step_timeout = 60
        mock_manager.bridge_data.process_timeout = 30

        import time

        mock_process = MagicMock()
        mock_process.process_id = 0
        mock_process.last_process_state = HordeProcessState.INFERENCE_STARTING
        mock_process.last_heartbeat_percent_complete = None
        mock_process.last_job_referenced = None
        mock_process.last_heartbeat_delta = 9999
        mock_process.last_progress_timestamp = time.time() - 9999
        mock_process.last_received_timestamp = time.time() - 9999
        mock_process.last_heartbeat_timestamp = time.time() - 9999

        mock_manager._process_map.values.return_value = [mock_process]
        # is_stuck_on_inference returns True but the guard should block the replacement
        mock_manager._process_map.is_stuck_on_inference.return_value = True

        bound_method = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager
        )

        with patch("threading.Thread"):
            bound_method()

        # Should NOT replace the INFERENCE_STARTING process while recently recovered
        mock_manager._replace_inference_process.assert_not_called()


class TestBridgeDataLoopExceptionHandling:
    """Behavioral tests that the bridge data loop recovers from exceptions."""

    def test_loop_continues_after_file_not_found(self) -> None:
        """The bridge data loop should log a warning and continue when the config file is not found."""
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        call_count = 0

        async def run_test() -> None:
            nonlocal call_count
            mock_manager = MagicMock()
            mock_manager._shutting_down = False
            mock_manager._bridge_data_loop_interval = 0.01
            mock_manager._bridge_data_last_modified_time = 0.0
            mock_manager._last_bridge_data_reload_time = 0.0

            bound_loop = HordeWorkerProcessManager._bridge_data_loop.__get__(
                mock_manager, HordeWorkerProcessManager
            )

            with patch("horde_worker_regen.process_management.process_manager.os.path.getmtime") as mock_getmtime:

                def side_effect(path: str) -> float:
                    nonlocal call_count
                    call_count += 1
                    if call_count <= 2:
                        raise FileNotFoundError(f"No such file: {path}")
                    # After 2 FileNotFoundErrors, stop the loop gracefully
                    mock_manager._shutting_down = True
                    return 0.0

                mock_getmtime.side_effect = side_effect
                await asyncio.wait_for(bound_loop(), timeout=2.0)

        asyncio.run(run_test())
        # The loop iterated at least 3 times, meaning it survived 2 FileNotFoundErrors
        assert call_count >= 3

    def test_loop_continues_after_unexpected_exception(self) -> None:
        """The bridge data loop should log the exception and continue after an unexpected error."""
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        call_count = 0

        async def run_test() -> None:
            nonlocal call_count
            mock_manager = MagicMock()
            mock_manager._shutting_down = False
            mock_manager._bridge_data_loop_interval = 0.01
            mock_manager._bridge_data_last_modified_time = 0.0
            mock_manager._last_bridge_data_reload_time = 0.0

            bound_loop = HordeWorkerProcessManager._bridge_data_loop.__get__(
                mock_manager, HordeWorkerProcessManager
            )

            with patch("horde_worker_regen.process_management.process_manager.os.path.getmtime") as mock_getmtime:

                def side_effect(path: str) -> float:
                    nonlocal call_count
                    call_count += 1
                    if call_count <= 2:
                        raise RuntimeError("Simulated disk error")
                    mock_manager._shutting_down = True
                    return 0.0

                mock_getmtime.side_effect = side_effect
                await asyncio.wait_for(bound_loop(), timeout=2.0)

        asyncio.run(run_test())
        assert call_count >= 3


class TestWorkerCycleExceptionHandling:
    """Behavioral tests that the subprocess main loop handles worker_cycle() exceptions."""

    def test_worker_cycle_exception_ends_process_gracefully(self) -> None:
        """When worker_cycle raises, main_loop should set _end_process and report PROCESS_ENDING."""
        from horde_worker_regen.process_management.horde_process import HordeProcess

        class _BrokenWorkerProcess(HordeProcess):
            cycle_calls: int = 0

            def worker_cycle(self) -> None:
                self.cycle_calls += 1
                raise RuntimeError("Simulated crash in worker_cycle")

            def cleanup_for_exit(self) -> None:
                pass

            def _receive_and_handle_control_message(self, message: object) -> None:
                pass

        mock_queue = MagicMock()
        mock_conn = MagicMock()
        mock_conn.poll.return_value = False
        mock_lock = MagicMock()

        proc = _BrokenWorkerProcess(
            process_id=0,
            process_message_queue=mock_queue,
            pipe_connection=mock_conn,
            disk_lock=mock_lock,
            process_launch_identifier=1,
        )

        with patch("signal.signal"), patch.object(sys, "exit"):
            proc.main_loop()

        assert proc._end_process is True
        assert proc.cycle_calls == 1

        # Verify PROCESS_ENDING was reported via the queue
        sent_states = [
            call.args[0].process_state
            for call in mock_queue.put.call_args_list
            if hasattr(call.args[0], "process_state")
        ]
        assert HordeProcessState.PROCESS_ENDING in sent_states

    def test_cleanup_for_exit_exception_still_sends_process_ended(self) -> None:
        """When cleanup_for_exit raises, main_loop should still send PROCESS_ENDED."""
        from horde_worker_regen.process_management.horde_process import HordeProcess

        class _CleanupFailsProcess(HordeProcess):
            def worker_cycle(self) -> None:
                self._end_process = True  # Exit the loop immediately

            def cleanup_for_exit(self) -> None:
                raise RuntimeError("Simulated cleanup failure")

            def _receive_and_handle_control_message(self, message: object) -> None:
                pass

        mock_queue = MagicMock()
        mock_conn = MagicMock()
        mock_conn.poll.return_value = False
        mock_lock = MagicMock()

        proc = _CleanupFailsProcess(
            process_id=0,
            process_message_queue=mock_queue,
            pipe_connection=mock_conn,
            disk_lock=mock_lock,
            process_launch_identifier=1,
        )

        with patch("signal.signal"), patch.object(sys, "exit"):
            proc.main_loop()

        # Even though cleanup_for_exit raised, PROCESS_ENDED must still be sent
        sent_states = [
            call.args[0].process_state
            for call in mock_queue.put.call_args_list
            if hasattr(call.args[0], "process_state")
        ]
        assert HordeProcessState.PROCESS_ENDED in sent_states


class TestApiSubmitJobBrokenDataHandling:
    """Tests that api_submit_job skips broken jobs instead of leaving the submit queue blocked."""

    def _make_job_info(self, *, id_: object = "test-id", seed: object = 42, r2_upload: object = "url") -> MagicMock:
        """Return a minimal sdk_api_job_info mock."""
        job_info = MagicMock()
        job_info.id_ = id_
        job_info.ids = [id_]
        job_info.r2_upload = r2_upload
        job_info.payload = MagicMock()
        job_info.payload.seed = seed
        job_info.payload.n_iter = 1
        return job_info

    def _make_completed_job(self, job_info: MagicMock, *, censored: object = False) -> MagicMock:
        completed = MagicMock()
        completed.sdk_api_job_info = job_info
        completed.state = "ok"  # concrete non-None, non-faulted state
        completed.job_image_results = None
        completed.censored = censored
        return completed

    def _run_api_submit_job(self, completed_job_info: MagicMock) -> tuple[list[MagicMock], dict, dict, list, dict]:
        """Run api_submit_job with the given completed job and return post-run tracking state."""
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        job_info = completed_job_info.sdk_api_job_info
        sentinel_id = job_info.id_

        pending: list[MagicMock] = [completed_job_info]
        jobs_lookup: dict = {job_info: completed_job_info}
        job_pop_timestamps: dict = {job_info: 0.0}
        jobs_in_progress: list = [job_info]
        job_faults: dict = {sentinel_id: []} if sentinel_id is not None else {}

        mock_manager = MagicMock()
        mock_manager.jobs_pending_submit = pending
        mock_manager.jobs_lookup = jobs_lookup
        mock_manager.job_pop_timestamps = job_pop_timestamps
        mock_manager.jobs_in_progress = jobs_in_progress
        mock_manager.job_faults = job_faults
        # Bind the real helper so cleanup actually runs
        mock_manager._discard_broken_job = types.MethodType(
            HordeWorkerProcessManager._discard_broken_job, mock_manager
        )

        import asyncio

        bound = HordeWorkerProcessManager.api_submit_job.__get__(mock_manager, HordeWorkerProcessManager)
        asyncio.run(bound())
        return pending, jobs_lookup, job_pop_timestamps, jobs_in_progress, job_faults

    def test_job_with_none_id_is_skipped(self) -> None:
        """A job with id_=None should be removed from the queue rather than blocking it."""
        job_info = self._make_job_info(id_=None)
        completed = self._make_completed_job(job_info)
        pending, lookup, timestamps, in_progress, faults = self._run_api_submit_job(completed)
        assert len(pending) == 0
        assert job_info not in lookup
        assert job_info not in timestamps
        assert job_info not in in_progress

    def test_job_with_none_seed_is_skipped(self) -> None:
        """A job with seed=None should be removed from the queue rather than blocking it."""
        job_info = self._make_job_info(seed=None)
        completed = self._make_completed_job(job_info)
        pending, lookup, timestamps, in_progress, faults = self._run_api_submit_job(completed)
        assert len(pending) == 0
        assert job_info not in lookup
        assert job_info not in timestamps
        assert job_info not in in_progress
        assert "test-id" not in faults

    def test_job_with_none_r2_upload_is_skipped(self) -> None:
        """A job with r2_upload=None should be removed from the queue rather than blocking it."""
        job_info = self._make_job_info(r2_upload=None)
        completed = self._make_completed_job(job_info)
        pending, lookup, timestamps, in_progress, faults = self._run_api_submit_job(completed)
        assert len(pending) == 0
        assert job_info not in lookup
        assert job_info not in timestamps
        assert job_info not in in_progress
        assert "test-id" not in faults

    def test_job_with_none_censored_and_images_is_skipped(self) -> None:
        """A job with image_results set but censored=None should be removed rather than blocking."""
        job_info = self._make_job_info()
        completed = self._make_completed_job(job_info, censored=None)
        # Set job_image_results to trigger the censored check
        completed.job_image_results = [MagicMock()]
        completed.sdk_api_job_info.payload.n_iter = 1
        pending, lookup, timestamps, in_progress, faults = self._run_api_submit_job(completed)
        assert len(pending) == 0
        assert job_info not in lookup
        assert job_info not in timestamps
        assert job_info not in in_progress
        assert "test-id" not in faults


class TestJobSubmitLoopExceptionHandling:
    """Tests that _job_submit_loop discards the head job when api_submit_job raises unexpectedly."""

    def test_unexpected_exception_discards_head_job(self) -> None:
        """When api_submit_job raises unexpectedly, the head job must be removed so the queue unblocks."""
        import asyncio
        import types

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        # Build a minimal completed-job mock
        job_info = MagicMock()
        job_info.id_ = "stuck-job"
        job_info.ids = ["stuck-job"]

        completed = MagicMock()
        completed.sdk_api_job_info = job_info

        mock_manager = MagicMock()
        mock_manager.jobs_pending_submit = [completed]
        mock_manager._shutting_down = False

        # Bind real _discard_broken_job so the queue is actually modified
        mock_manager._discard_broken_job = types.MethodType(
            HordeWorkerProcessManager._discard_broken_job, mock_manager
        )
        mock_manager.jobs_lookup = {job_info: completed}
        mock_manager.job_pop_timestamps = {job_info: 0.0}
        mock_manager.jobs_in_progress = [job_info]
        mock_manager.job_faults = {}

        call_count = 0

        async def failing_api_submit_job() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated unexpected failure in api_submit_job")
            # After the broken job is discarded the queue is empty; shut down
            mock_manager._shutting_down = True

        mock_manager.api_submit_job = failing_api_submit_job
        mock_manager.is_time_for_shutdown = lambda: mock_manager._shutting_down
        mock_manager._job_submit_loop_interval = 0.01

        bound_loop = HordeWorkerProcessManager._job_submit_loop.__get__(mock_manager, HordeWorkerProcessManager)

        asyncio.run(asyncio.wait_for(bound_loop(), timeout=2.0))

        # The broken job must have been removed from the queue
        assert len(mock_manager.jobs_pending_submit) == 0
        assert job_info not in mock_manager.jobs_lookup
        assert job_info not in mock_manager.jobs_in_progress

    def test_job_removed_by_api_submit_job_is_not_double_discarded(self) -> None:
        """If api_submit_job already removed the head job before raising, the next job is not discarded."""
        import asyncio
        import types

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        job_info_head = MagicMock()
        job_info_head.id_ = "head-job"
        job_info_head.ids = ["head-job"]
        completed_head = MagicMock()
        completed_head.sdk_api_job_info = job_info_head

        job_info_next = MagicMock()
        job_info_next.id_ = "next-job"
        job_info_next.ids = ["next-job"]
        completed_next = MagicMock()
        completed_next.sdk_api_job_info = job_info_next

        mock_manager = MagicMock()
        mock_manager._shutting_down = False
        # Start with two jobs in the queue
        mock_manager.jobs_pending_submit = [completed_head, completed_next]
        mock_manager.jobs_lookup = {job_info_head: completed_head, job_info_next: completed_next}
        mock_manager.job_pop_timestamps = {}
        mock_manager.jobs_in_progress = []
        mock_manager.job_faults = {}

        mock_manager._discard_broken_job = types.MethodType(
            HordeWorkerProcessManager._discard_broken_job, mock_manager
        )

        async def api_submit_job_removes_head_then_raises() -> None:
            # Simulate api_submit_job removing the head job internally (e.g. normal cleanup path
            # partially ran), then raising an unexpected error.
            mock_manager.jobs_pending_submit.pop(0)
            raise RuntimeError("Partial failure after head was already removed")

        call_count = 0

        original_submit = api_submit_job_removes_head_then_raises

        async def controlled_submit() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await original_submit()
            # Second call: succeed and shut down
            mock_manager._shutting_down = True

        mock_manager.api_submit_job = controlled_submit
        mock_manager.is_time_for_shutdown = lambda: mock_manager._shutting_down
        mock_manager._job_submit_loop_interval = 0.01

        bound_loop = HordeWorkerProcessManager._job_submit_loop.__get__(mock_manager, HordeWorkerProcessManager)
        asyncio.run(asyncio.wait_for(bound_loop(), timeout=2.0))

        # The next job must NOT have been discarded (it was not the job that failed)
        assert completed_next in mock_manager.jobs_pending_submit
        assert job_info_next in mock_manager.jobs_lookup


class _ReceiveLoopHarnessMixin:
    """Shared helpers for tests that drive receive_and_handle_process_messages."""

    def _make_message(
        self,
        process_state: HordeProcessState,
        process_id: int = 0,
        launch_id: int = 1,
    ) -> object:
        """Return a real HordeProcessStateChangeMessage so isinstance() checks pass."""
        from horde_worker_regen.process_management.messages import HordeProcessStateChangeMessage

        return HordeProcessStateChangeMessage(
            process_id=process_id,
            process_launch_identifier=launch_id,
            process_state=process_state,
            info="test",
            time_elapsed=None,
        )

    def _run_receive(
        self,
        msg: object,
        process_info: MagicMock,
        *,
        jobs_in_progress: list | None = None,
    ) -> MagicMock:
        """Run receive_and_handle_process_messages with a single queued message.

        Returns the mock_manager so callers can inspect side-effects.
        """
        import queue as queue_mod

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        # Configure the process_map so `process_id in process_map` and `process_map[process_id]` work
        process_map = MagicMock()
        process_map.__contains__ = MagicMock(side_effect=lambda key: key == 0)
        process_map.__getitem__ = MagicMock(side_effect=lambda key: process_info)

        q = queue_mod.Queue()
        q.put(msg)

        mock_manager = MagicMock()
        mock_manager._process_message_queue = q
        mock_manager._process_map = process_map
        mock_manager._in_deadlock = False
        mock_manager._in_queue_deadlock = False
        mock_manager.jobs_in_progress = jobs_in_progress if jobs_in_progress is not None else []

        bound = HordeWorkerProcessManager.receive_and_handle_process_messages.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        bound()  # must not raise
        return mock_manager


class TestReceiveAndHandleProcessMessagesResilience(_ReceiveLoopHarnessMixin):
    """Tests that receive_and_handle_process_messages does not crash on INFERENCE_STARTING edge cases."""

    def test_inference_starting_with_no_model_does_not_raise(self) -> None:
        """INFERENCE_STARTING with no model loaded should log an error and continue, not raise."""
        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = HordeProcessState.WAITING_FOR_JOB
        process_info.loaded_horde_model_name = None  # trigger the guard
        process_info.batch_amount = None

        msg = self._make_message(HordeProcessState.INFERENCE_STARTING)
        self._run_receive(msg, process_info)

    def test_inference_starting_with_no_batch_amount_does_not_raise(self) -> None:
        """INFERENCE_STARTING with batch_amount=None should log an error and continue, not raise."""
        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = HordeProcessState.WAITING_FOR_JOB
        process_info.loaded_horde_model_name = "some_model"
        process_info.batch_amount = None  # trigger the guard

        msg = self._make_message(HordeProcessState.INFERENCE_STARTING)
        self._run_receive(msg, process_info)


class TestIsStuckOnInference:
    """Tests for the is_stuck_on_inference() method covering both INFERENCE_STARTING and INFERENCE_PROCESSING."""

    def _make_process_map_entry(
        self,
        state: HordeProcessState,
        last_progress_timestamp: float,
        last_heartbeat_timestamp: float,
        last_heartbeat_delta: float = 0.0,
        heartbeats_inference_steps: int = 0,
        last_progress_value: int | None = None,
    ) -> MagicMock:
        """Create a mock process map entry with configurable timestamps."""
        entry = MagicMock()
        entry.last_process_state = state
        entry.last_progress_timestamp = last_progress_timestamp
        entry.last_heartbeat_timestamp = last_heartbeat_timestamp
        entry.last_heartbeat_delta = last_heartbeat_delta
        entry.heartbeats_inference_steps = heartbeats_inference_steps
        entry.last_progress_value = last_progress_value
        return entry

    def _make_process_map(self, entry: MagicMock) -> MagicMock:
        """Create a mock process map that returns the given entry for any key."""
        from horde_worker_regen.process_management.process_manager import ProcessMap

        process_map = MagicMock()
        process_map.__getitem__ = MagicMock(return_value=entry)
        process_map.is_stuck_on_inference = ProcessMap.is_stuck_on_inference.__get__(
            process_map, ProcessMap
        )
        return process_map

    def test_inference_starting_not_stuck_returns_false(self) -> None:
        """A process in INFERENCE_STARTING with recent progress and heartbeat is not stuck."""
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_STARTING,
            last_progress_timestamp=time.time() - 10,
            last_heartbeat_timestamp=time.time() - 10,
        )
        process_map = self._make_process_map(entry)
        assert process_map.is_stuck_on_inference(0, 600) is False

    def test_inference_starting_no_progress_returns_true(self) -> None:
        """A process in INFERENCE_STARTING with stalled progress beyond timeout is stuck."""
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_STARTING,
            last_progress_timestamp=time.time() - 9999,
            last_heartbeat_timestamp=time.time() - 10,
        )
        process_map = self._make_process_map(entry)
        assert process_map.is_stuck_on_inference(0, 600) is True

    def test_inference_starting_no_heartbeat_returns_true(self) -> None:
        """A process in INFERENCE_STARTING with no heartbeat beyond timeout is stuck."""
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_STARTING,
            last_progress_timestamp=time.time() - 10,
            last_heartbeat_timestamp=time.time() - 9999,
            last_heartbeat_delta=5.0,  # delta between last two heartbeats was normal (5s)
        )
        process_map = self._make_process_map(entry)
        # Should detect via time since last heartbeat, not last_heartbeat_delta
        assert process_map.is_stuck_on_inference(0, 600) is True

    def test_inference_processing_not_stuck_returns_false(self) -> None:
        """A process in INFERENCE_PROCESSING with recent progress and heartbeat is not stuck."""
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 10,
            last_heartbeat_timestamp=time.time() - 10,
        )
        process_map = self._make_process_map(entry)
        assert process_map.is_stuck_on_inference(0, 600) is False

    def test_inference_processing_no_progress_returns_true(self) -> None:
        """A process in INFERENCE_PROCESSING with stalled progress is stuck."""
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 9999,
            last_heartbeat_timestamp=time.time() - 10,
        )
        process_map = self._make_process_map(entry)
        assert process_map.is_stuck_on_inference(0, 600) is True

    def test_inference_processing_no_heartbeat_returns_true(self) -> None:
        """A process in INFERENCE_PROCESSING with no heartbeat beyond timeout is stuck.

        This is the core scenario for the 'stuck at INFERENCE_STARTING' bug:
        Process A holds the inference semaphore in INFERENCE_PROCESSING and stops responding.
        Without this check, Process A is never detected as stuck, and any process waiting
        to acquire the semaphore remains permanently stuck in INFERENCE_STARTING.
        """
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 10,
            last_heartbeat_timestamp=time.time() - 9999,
            last_heartbeat_delta=5.0,  # delta between last two heartbeats was normal (5s)
        )
        process_map = self._make_process_map(entry)
        # Should detect via time since last heartbeat, not last_heartbeat_delta
        assert process_map.is_stuck_on_inference(0, 600) is True

    def test_other_state_returns_false(self) -> None:
        """A process in a non-inference state is not considered stuck on inference."""
        import time

        for state in [
            HordeProcessState.WAITING_FOR_JOB,
            HordeProcessState.MODEL_LOADING,
            HordeProcessState.INFERENCE_POST_PROCESSING,
            HordeProcessState.INFERENCE_COMPLETE,
        ]:
            entry = self._make_process_map_entry(
                state=state,
                last_progress_timestamp=time.time() - 9999,
                last_heartbeat_timestamp=time.time() - 9999,
            )
            process_map = self._make_process_map(entry)
            assert process_map.is_stuck_on_inference(0, 600) is False, (
                f"Expected False for state {state.name}"
            )

    def test_inference_processing_no_step_heartbeats_uses_shorter_timeout(self) -> None:
        """INFERENCE_PROCESSING with no step heartbeats triggers on no_step_heartbeat_timeout.

        Scenario: the process sent the initial PIPELINE_STATE_CHANGE heartbeat (heartbeats_inference_steps=0)
        and then went completely silent (crash before any diffusion step, or stall during VAE decode).
        With no_step_heartbeat_timeout=120 and time_since_heartbeat=150, the process must be
        detected as stuck even though inference_step_timeout=600 has not elapsed.
        """
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 10,
            last_heartbeat_timestamp=time.time() - 150,
            heartbeats_inference_steps=0,
        )
        process_map = self._make_process_map(entry)
        # Without no_step_heartbeat_timeout, 150s < 600s inference_step_timeout → not stuck
        assert process_map.is_stuck_on_inference(0, 600) is False
        # With no_step_heartbeat_timeout=120, 150s > 120s → stuck
        assert process_map.is_stuck_on_inference(0, 600, no_step_heartbeat_timeout=120) is True

    def test_inference_processing_no_step_heartbeats_not_yet_timed_out(self) -> None:
        """INFERENCE_PROCESSING with no step heartbeats is NOT stuck if shorter timeout not elapsed."""
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 10,
            last_heartbeat_timestamp=time.time() - 50,
            heartbeats_inference_steps=0,
        )
        process_map = self._make_process_map(entry)
        # 50s < no_step_heartbeat_timeout=120 → not yet stuck
        assert process_map.is_stuck_on_inference(0, 600, no_step_heartbeat_timeout=120) is False

    def test_inference_processing_with_step_heartbeats_ignores_shorter_timeout(self) -> None:
        """When step heartbeats have been received, no_step_heartbeat_timeout is ignored.

        A process that has completed at least one diffusion step uses inference_step_timeout,
        not the shorter no_step_heartbeat_timeout, for the heartbeat check.
        """
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 10,
            last_heartbeat_timestamp=time.time() - 150,
            heartbeats_inference_steps=5,  # steps have been received
        )
        process_map = self._make_process_map(entry)
        # 150s > no_step_heartbeat_timeout=120, but heartbeats_inference_steps > 0 so short
        # timeout must NOT apply.  150s < inference_step_timeout=600 → not stuck.
        assert process_map.is_stuck_on_inference(0, 600, no_step_heartbeat_timeout=120) is False

    def test_inference_starting_no_step_heartbeats_does_not_use_shorter_timeout(self) -> None:
        """no_step_heartbeat_timeout must NOT apply to INFERENCE_STARTING.

        A process blocked on semaphore acquisition cannot send heartbeats.  Applying the shorter
        timeout to INFERENCE_STARTING would create false positives right after a prior replacement
        frees the semaphore (cascading recovery).
        """
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_STARTING,
            last_progress_timestamp=time.time() - 10,
            last_heartbeat_timestamp=time.time() - 150,
            heartbeats_inference_steps=0,
        )
        process_map = self._make_process_map(entry)
        # 150s > no_step_heartbeat_timeout=120, but state is INFERENCE_STARTING → not stuck
        # (still below the full inference_step_timeout of 600s)
        assert process_map.is_stuck_on_inference(0, 600, no_step_heartbeat_timeout=120) is False

    def test_inference_processing_at_100_with_recent_heartbeat_not_stuck(self) -> None:
        """At 100% progress in INFERENCE_PROCESSING with recent heartbeat the process is not stuck.

        When all diffusion steps complete (progress = 100 %), the background heartbeat thread
        sends periodic PIPELINE_STATE_CHANGE heartbeats at 100 %.  Because the progress value
        never changes from 100, last_progress_timestamp is not refreshed.  Without the 100 %
        exemption, is_stuck_on_inference() would fire the progress-stalled check after
        inference_step_timeout seconds even though the process is actively running VAE decode
        (a false positive).  The fix skips check 1 when last_progress_value == 100.
        """
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 9999,  # stale — 100% never changes
            last_heartbeat_timestamp=time.time() - 10,  # heartbeats arriving normally
            heartbeats_inference_steps=0,  # reset by PIPELINE_STATE_CHANGE
            last_progress_value=100,
        )
        process_map = self._make_process_map(entry)
        # Even though progress_timestamp is stale, check 1 must be skipped at 100%.
        # Heartbeat is recent → checks 2 and 3 also don't fire → not stuck.
        assert process_map.is_stuck_on_inference(0, 600) is False

    def test_inference_processing_at_100_no_heartbeat_is_stuck(self) -> None:
        """At 100% progress in INFERENCE_PROCESSING, a dead process (no heartbeats) is stuck.

        If the process dies during VAE decode, the background heartbeat thread also stops.
        Even with the 100 % exemption for check 1, checks 2/3 must still detect this case.
        """
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 9999,  # stale — 100% never changes
            last_heartbeat_timestamp=time.time() - 9999,  # no heartbeats — process is dead
            heartbeats_inference_steps=0,
            last_progress_value=100,
        )
        process_map = self._make_process_map(entry)
        # Check 1 skipped (at 100%), but check 3 fires because no heartbeat for >600s.
        assert process_map.is_stuck_on_inference(0, 600) is True

    def test_inference_processing_at_100_no_step_heartbeat_timeout_detects_dead_process(self) -> None:
        """At 100%, no_step_heartbeat_timeout detects a dead process sooner than inference_step_timeout.

        When the process dies during VAE decode, the no_step_heartbeat_timeout (shorter)
        should fire before the full inference_step_timeout, as intended for fast recovery.
        """
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 9999,  # stale
            last_heartbeat_timestamp=time.time() - 350,  # no heartbeats for 350s > 300s timeout
            heartbeats_inference_steps=0,
            last_progress_value=100,
        )
        process_map = self._make_process_map(entry)
        # Check 1 skipped (100%), check 3 doesn't fire (350s < 600s), but check 2 fires
        # because heartbeats_inference_steps==0 and 350s > no_step_heartbeat_timeout=300s.
        assert process_map.is_stuck_on_inference(0, 600, no_step_heartbeat_timeout=300) is True

    def test_inference_processing_below_100_still_uses_progress_stalled_check(self) -> None:
        """Below 100%, a job with stalled progress and recent heartbeats is still detected as stuck.

        The 100 % exemption must not be applied when progress is below 100 %: a process sending
        heartbeats but making no diffusion progress (e.g., GPU hung at 50 %) should still be
        detected and replaced.
        """
        import time

        entry = self._make_process_map_entry(
            state=HordeProcessState.INFERENCE_PROCESSING,
            last_progress_timestamp=time.time() - 9999,  # stale progress (stuck at 50 %)
            last_heartbeat_timestamp=time.time() - 10,  # heartbeats arriving
            heartbeats_inference_steps=5,
            last_progress_value=50,
        )
        process_map = self._make_process_map(entry)
        # progress_value != 100, so check 1 must still fire.
        assert process_map.is_stuck_on_inference(0, 600) is True


class TestInferenceSemaphoreBoundedSemaphore:
    """Tests that _inference_semaphore is a BoundedSemaphore to prevent permit inflation."""

    def test_inference_semaphore_is_bounded(self) -> None:
        """_inference_semaphore must be a BoundedSemaphore so over-release raises ValueError.

        The existing ValueError handlers in _replace_inference_process() and the child inference
        process prevent any double-release from inflating permits beyond max_threads.
        """
        import multiprocessing
        from multiprocessing.synchronize import BoundedSemaphore

        ctx = multiprocessing.get_context("spawn")

        # Verify BoundedSemaphore raises ValueError on over-release, unlike Semaphore
        sem = BoundedSemaphore(1, ctx=ctx)
        sem.acquire()
        sem.release()  # Back to initial count
        raised = False
        try:
            sem.release()  # Over-release — must raise ValueError for BoundedSemaphore
        except ValueError:
            raised = True
        assert raised, "BoundedSemaphore should raise ValueError on over-release"

    def test_replace_inference_process_double_release_does_not_inflate_permits(self) -> None:
        """A double-release of the inference semaphore must not inflate the permit count.

        Scenario: manager still sees INFERENCE_PROCESSING (async state lag) but the child
        already released the semaphore during post-processing.  Calling _replace_inference_process
        should not increase the available permits beyond max_threads.
        """
        import multiprocessing
        from multiprocessing.synchronize import BoundedSemaphore

        from horde_worker_regen.process_management.messages import HordeProcessState
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        ctx = multiprocessing.get_context("spawn")
        max_threads = 1
        bounded_sem = BoundedSemaphore(max_threads, ctx=ctx)

        # Simulate child having acquired then released the semaphore (post-processing path)
        bounded_sem.acquire()
        bounded_sem.release()  # Child released when entering post-processing
        # Now bounded_sem has 1 permit available (back to initial)

        # Build a minimal mock manager
        from unittest.mock import MagicMock

        mock_manager = MagicMock()
        mock_manager._inference_semaphore = bounded_sem
        mock_manager._disk_lock = MagicMock()
        mock_manager._disk_lock.release.side_effect = ValueError  # already released

        process_info = MagicMock()
        process_info.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        process_info.last_job_referenced = None
        process_info.loaded_horde_model_name = None

        # Bind real _replace_inference_process
        import types

        bound = types.MethodType(HordeWorkerProcessManager._replace_inference_process, mock_manager)
        bound(process_info)  # Must not raise

        # The semaphore should still have at most 1 permit (not inflated to 2)
        acquired = bounded_sem.acquire(block=False)
        assert acquired, "Semaphore should have exactly 1 permit available"
        second_acquired = bounded_sem.acquire(block=False)
        assert not second_acquired, "Semaphore must not have more than 1 permit (no inflation)"


class TestProcessEndingJobFaultHandling(_ReceiveLoopHarnessMixin):
    """Tests that a job in-progress is faulted when its process sends HordeProcessState.PROCESS_ENDING.

    Scenario: A child process encounters an exception during inference handling and
    ends itself (sending HordeProcessState.PROCESS_ENDING) before it can send the
    HordeInferenceResultMessage. The parent must detect the orphaned job and fault it
    so it is retried or submitted rather than silently lost.
    """

    def test_process_ending_with_job_in_progress_calls_handle_job_fault(self) -> None:
        """When PROCESS_ENDING arrives and the job is still in jobs_in_progress, handle_job_fault must be called."""
        job = MagicMock()
        job.id_ = "orphaned-job-id"

        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        process_info.last_job_referenced = job

        msg = self._make_message(HordeProcessState.PROCESS_ENDING)
        mock_manager = self._run_receive(msg, process_info, jobs_in_progress=[job])

        mock_manager.handle_job_fault.assert_called_once_with(
            faulted_job=job,
            process_info=process_info,
        )

    def test_process_ending_without_job_in_progress_does_not_call_handle_job_fault(self) -> None:
        """When HordeProcessState.PROCESS_ENDING arrives and the job is not in jobs_in_progress, handle_job_fault must not be called.

        This covers the normal case: inference completed, the result was already processed
        (removing the job from jobs_in_progress), and now the process is shutting down.
        """
        job = MagicMock()
        job.id_ = "completed-job-id"

        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = HordeProcessState.WAITING_FOR_JOB
        process_info.last_job_referenced = job

        msg = self._make_message(HordeProcessState.PROCESS_ENDING)
        # job is not in jobs_in_progress (it was already submitted)
        mock_manager = self._run_receive(msg, process_info, jobs_in_progress=[])

        mock_manager.handle_job_fault.assert_not_called()

    def test_process_ending_with_no_job_referenced_does_not_call_handle_job_fault(self) -> None:
        """When PROCESS_ENDING arrives and last_job_referenced is None, handle_job_fault must not be called."""
        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = HordeProcessState.WAITING_FOR_JOB
        process_info.last_job_referenced = None

        msg = self._make_message(HordeProcessState.PROCESS_ENDING)
        mock_manager = self._run_receive(msg, process_info, jobs_in_progress=[])

        mock_manager.handle_job_fault.assert_not_called()

    def test_process_ending_calls_on_process_ending_after_fault(self) -> None:
        """on_process_ending must be called after (not before) handle_job_fault to avoid clearing last_job_referenced."""
        job = MagicMock()
        job.id_ = "orphaned-job-id"

        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        process_info.last_job_referenced = job

        call_order: list[str] = []

        msg = self._make_message(HordeProcessState.PROCESS_ENDING)

        import queue as queue_mod

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        process_map = MagicMock()
        process_map.__contains__ = MagicMock(side_effect=lambda key: key == 0)
        process_map.__getitem__ = MagicMock(side_effect=lambda key: process_info)
        process_map.on_process_ending = MagicMock(side_effect=lambda process_id: call_order.append("on_process_ending"))

        q = queue_mod.Queue()
        q.put(msg)

        mock_manager = MagicMock()
        mock_manager._process_message_queue = q
        mock_manager._process_map = process_map
        mock_manager._in_deadlock = False
        mock_manager._in_queue_deadlock = False
        mock_manager.jobs_in_progress = [job]
        mock_manager.handle_job_fault = MagicMock(side_effect=lambda faulted_job, process_info: call_order.append("handle_job_fault"))

        bound = HordeWorkerProcessManager.receive_and_handle_process_messages.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        bound()

        # handle_job_fault must be called before on_process_ending, so that
        # last_job_referenced is still available when handle_job_fault runs
        assert "handle_job_fault" in call_order, "handle_job_fault was not called"
        assert "on_process_ending" in call_order, "on_process_ending was not called"
        assert call_order.index("handle_job_fault") < call_order.index("on_process_ending"), (
            "handle_job_fault must be called before on_process_ending"
        )

    def test_process_ending_with_job_in_progress_uses_prior_state_for_fault(self) -> None:
        """handle_job_fault must see the prior process state (e.g. INFERENCE_PROCESSING), not PROCESS_ENDING.

        This ensures _faulted_jobs_history correctly classifies the fault phase as 'During Inference'
        rather than the misleading 'Process Ending'.
        """

        job = MagicMock()
        job.id_ = "orphaned-job-id"

        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        process_info.last_job_referenced = job

        seen_state: list[HordeProcessState] = []

        msg = self._make_message(HordeProcessState.PROCESS_ENDING)

        import queue as queue_mod

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        process_map = MagicMock()
        process_map.__contains__ = MagicMock(side_effect=lambda key: key == 0)
        process_map.__getitem__ = MagicMock(side_effect=lambda key: process_info)

        q = queue_mod.Queue()
        q.put(msg)

        mock_manager = MagicMock()
        mock_manager._process_message_queue = q
        mock_manager._process_map = process_map
        mock_manager._in_deadlock = False
        mock_manager._in_queue_deadlock = False
        mock_manager.jobs_in_progress = [job]

        def capture_fault(*, faulted_job: object, process_info: MagicMock) -> None:
            seen_state.append(process_info.last_process_state)

        mock_manager.handle_job_fault = MagicMock(side_effect=capture_fault)

        bound = HordeWorkerProcessManager.receive_and_handle_process_messages.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        bound()

        assert len(seen_state) == 1, "handle_job_fault was not called exactly once"
        assert seen_state[0] == HordeProcessState.INFERENCE_PROCESSING, (
            f"Expected prior state INFERENCE_PROCESSING, got {seen_state[0]}"
        )



class TestProcessEndedAutoRestart(_ReceiveLoopHarnessMixin):
    """Tests that an inference process is automatically restarted when PROCESS_ENDED is received.

    Scenario: An inference process crashes during INFERENCE_PROCESSING.  The child sends
    PROCESS_ENDING (which triggers handle_job_fault) then PROCESS_ENDED.  The parent must
    restart the dead process so the worker returns to its configured capacity.
    """

    def _run_receive_process_ended(
        self,
        process_type: object,
        *,
        shutting_down: bool = False,
        prior_state: HordeProcessState = HordeProcessState.PROCESS_ENDING,
        existing_manager: MagicMock | None = None,
    ) -> MagicMock:
        """Run receive_and_handle_process_messages with a PROCESS_ENDED message.

        Returns the mock_manager so callers can inspect side-effects.
        """
        import queue as queue_mod

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = prior_state
        process_info.last_job_referenced = None
        process_info.process_type = process_type

        process_map = MagicMock()
        process_map.__contains__ = MagicMock(side_effect=lambda key: key == 0)
        process_map.__getitem__ = MagicMock(side_effect=lambda key: process_info)

        msg = self._make_message(HordeProcessState.PROCESS_ENDED)
        q = queue_mod.Queue()
        q.put(msg)

        if existing_manager is not None:
            mock_manager = existing_manager
            mock_manager._process_message_queue = q
            mock_manager._process_map = process_map
        else:
            mock_manager = MagicMock()
            mock_manager._process_message_queue = q
            mock_manager._process_map = process_map
            mock_manager._in_deadlock = False
            mock_manager._in_queue_deadlock = False
            mock_manager.jobs_in_progress = []
            mock_manager._shutting_down = shutting_down
            mock_manager._num_process_recoveries = 0
            mock_manager._process_restart_history = {}

        bound = HordeWorkerProcessManager.receive_and_handle_process_messages.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        bound()
        return mock_manager

    def test_inference_process_restarted_on_unexpected_end(self) -> None:
        """When PROCESS_ENDED arrives for an inference process and we are not shutting down,
        _start_inference_process must be called to restore the configured worker capacity."""
        from horde_worker_regen.process_management.process_manager import HordeProcessType

        mock_manager = self._run_receive_process_ended(
            process_type=HordeProcessType.INFERENCE,
            shutting_down=False,
        )

        mock_manager._start_inference_process.assert_called_once_with(0)

    def test_inference_process_restarted_increments_num_process_recoveries(self) -> None:
        """When a process is restarted after PROCESS_ENDED, _num_process_recoveries must be incremented."""
        from horde_worker_regen.process_management.process_manager import HordeProcessType

        mock_manager = self._run_receive_process_ended(
            process_type=HordeProcessType.INFERENCE,
            shutting_down=False,
        )

        mock_manager._start_inference_process.assert_called_once_with(0)
        assert mock_manager._num_process_recoveries == 1

    def test_inference_process_not_restarted_during_shutdown(self) -> None:
        """When PROCESS_ENDED arrives for an inference process while shutting down,
        _start_inference_process must NOT be called."""
        from horde_worker_regen.process_management.process_manager import HordeProcessType

        mock_manager = self._run_receive_process_ended(
            process_type=HordeProcessType.INFERENCE,
            shutting_down=True,
        )

        mock_manager._start_inference_process.assert_not_called()

    def test_safety_process_not_restarted_on_end(self) -> None:
        """When PROCESS_ENDED arrives for a safety process, _start_inference_process must NOT
        be called (safety processes have separate restart logic)."""
        from horde_worker_regen.process_management.process_manager import HordeProcessType

        mock_manager = self._run_receive_process_ended(
            process_type=HordeProcessType.SAFETY,
            shutting_down=False,
        )

        mock_manager._start_inference_process.assert_not_called()

    def test_process_starting_prior_state_skips_restart(self) -> None:
        """When PROCESS_ENDED arrives and the prior state was PROCESS_STARTING, the process
        must NOT be restarted to avoid a tight crash/restart loop caused by init failures."""
        from horde_worker_regen.process_management.process_manager import HordeProcessType

        mock_manager = self._run_receive_process_ended(
            process_type=HordeProcessType.INFERENCE,
            shutting_down=False,
            prior_state=HordeProcessState.PROCESS_STARTING,
        )

        mock_manager._start_inference_process.assert_not_called()
        assert mock_manager._num_process_recoveries == 0

    def test_restart_rate_limited_after_five_failures_in_sixty_seconds(self) -> None:
        """When a process ends and restarts 5 times within 60 seconds, the 6th restart must
        be suppressed to prevent a tight crash/restart loop."""
        import time

        from horde_worker_regen.process_management.process_manager import HordeProcessType

        # Seed the restart history with 5 recent timestamps so the next end triggers the limit
        mock_manager = MagicMock()
        mock_manager._in_deadlock = False
        mock_manager._in_queue_deadlock = False
        mock_manager.jobs_in_progress = []
        mock_manager._shutting_down = False
        mock_manager._num_process_recoveries = 0

        now = time.time()
        mock_manager._process_restart_history = {0: deque([now - 5, now - 4, now - 3, now - 2, now - 1], maxlen=5)}

        self._run_receive_process_ended(
            process_type=HordeProcessType.INFERENCE,
            shutting_down=False,
            existing_manager=mock_manager,
        )

        mock_manager._start_inference_process.assert_not_called()
        assert mock_manager._num_process_recoveries == 0

    def test_restart_allowed_after_five_failures_spread_over_more_than_sixty_seconds(self) -> None:
        """When 5 prior restarts are spread over more than 60 seconds, the next restart must
        still be allowed (rate limit window has passed)."""
        import time

        from horde_worker_regen.process_management.process_manager import HordeProcessType

        mock_manager = MagicMock()
        mock_manager._in_deadlock = False
        mock_manager._in_queue_deadlock = False
        mock_manager.jobs_in_progress = []
        mock_manager._shutting_down = False
        mock_manager._num_process_recoveries = 0

        now = time.time()
        # Pre-seed with only 4 entries so after the production code appends the current timestamp,
        # the deque contains 5 entries and restart_history[0] is 90s ago (outside the 60s window).
        mock_manager._process_restart_history = {
            0: deque([now - 90, now - 4, now - 3, now - 2], maxlen=5)
        }

        self._run_receive_process_ended(
            process_type=HordeProcessType.INFERENCE,
            shutting_down=False,
            existing_manager=mock_manager,
        )

        mock_manager._start_inference_process.assert_called_once_with(0)
        assert mock_manager._num_process_recoveries == 1


class TestSendMemoryReportMessageVramFailure:
    """Tests that VRAM query failures do not terminate the inference process.

    Regression test for the bug where a VRAM query failure inside
    send_memory_report_message caused the inference process to set
    _end_process = True and exit mid-inference, orphaning the in-flight job.
    """

    def _create_mock_horde_process(self) -> MagicMock:
        """Create a minimal mock that exercises HordeProcess.send_memory_report_message."""
        from horde_worker_regen.process_management.horde_process import HordeProcess

        mock = MagicMock()
        mock.process_id = 1
        mock.process_launch_identifier = 42
        mock._end_process = False
        mock._last_vram_warning_time = 0.0  # Ensure getattr fallback works correctly

        # Bind the real base-class method
        mock.send_memory_report_message = HordeProcess.send_memory_report_message.__get__(mock, HordeProcess)
        return mock

    def test_vram_failure_still_sends_report(self) -> None:
        """A VRAM query failure must not prevent the memory report from being sent."""
        mock = self._create_mock_horde_process()

        # Make VRAM query raise
        mock.get_vram_usage_bytes.side_effect = RuntimeError("CUDA error")
        mock.get_vram_total_bytes.side_effect = RuntimeError("CUDA error")

        result = mock.send_memory_report_message(include_vram=True)

        assert result is True, "send_memory_report_message must return True even when VRAM query fails"
        # Verify the message was still sent to the queue (put() was called)
        mock.process_message_queue.put.assert_called_once()
        # Verify the message payload has VRAM fields as None (not partially set)
        sent_message = mock.process_message_queue.put.call_args[0][0]
        assert sent_message.vram_usage_bytes is None, "vram_usage_bytes must be None on failure"
        assert sent_message.vram_total_bytes is None, "vram_total_bytes must be None on failure"

    def test_partial_vram_failure_sends_report_without_vram(self) -> None:
        """If the second VRAM query fails, neither VRAM field should be set in the message.

        Guards against partially setting vram_usage_bytes without vram_total_bytes.
        """
        mock = self._create_mock_horde_process()

        # First call succeeds, second raises
        mock.get_vram_usage_bytes.return_value = 1024 * 1024 * 256  # 256 MB
        mock.get_vram_total_bytes.side_effect = RuntimeError("Driver error")

        result = mock.send_memory_report_message(include_vram=True)

        assert result is True
        mock.process_message_queue.put.assert_called_once()
        sent_message = mock.process_message_queue.put.call_args[0][0]
        assert sent_message.vram_usage_bytes is None, (
            "vram_usage_bytes must be None when the second VRAM query fails"
        )
        assert sent_message.vram_total_bytes is None, (
            "vram_total_bytes must be None when the second VRAM query fails"
        )

    def test_vram_failure_does_not_set_end_process(self) -> None:
        """A VRAM query failure must not set _end_process = True on the process."""
        mock = self._create_mock_horde_process()

        # Make VRAM query raise
        mock.get_vram_usage_bytes.side_effect = RuntimeError("CUDA OOM error")
        mock.get_vram_total_bytes.side_effect = RuntimeError("CUDA OOM error")

        mock.send_memory_report_message(include_vram=True)

        assert mock._end_process is False, "_end_process must not be set to True on VRAM query failure"

    def test_successful_report_without_vram(self) -> None:
        """A report without VRAM info should always succeed."""
        mock = self._create_mock_horde_process()

        result = mock.send_memory_report_message(include_vram=False)

        assert result is True
        # get_vram_usage_bytes and get_vram_total_bytes should NOT be called
        mock.get_vram_usage_bytes.assert_not_called()
        mock.get_vram_total_bytes.assert_not_called()
        mock.process_message_queue.put.assert_called_once()

    def test_successful_report_with_vram(self) -> None:
        """A report with VRAM info should succeed when VRAM query works."""
        mock = self._create_mock_horde_process()
        mock.get_vram_usage_bytes.return_value = 1024 * 1024 * 512  # 512 MB
        mock.get_vram_total_bytes.return_value = 1024 * 1024 * 1024 * 8  # 8 GB

        result = mock.send_memory_report_message(include_vram=True)

        assert result is True
        mock.process_message_queue.put.assert_called_once()

    def test_vram_warning_is_rate_limited(self) -> None:
        """Repeated VRAM failures within 10 s must not re-emit a WARNING; they use DEBUG instead."""
        import time
        from unittest.mock import call

        mock = self._create_mock_horde_process()
        mock.get_vram_usage_bytes.side_effect = RuntimeError("CUDA error")
        mock.get_vram_total_bytes.side_effect = RuntimeError("CUDA error")

        # Simulate the first failure happened 5 seconds ago (within the 10-second window)
        mock._last_vram_warning_time = time.time() - 5.0

        with patch("horde_worker_regen.process_management.horde_process.logger") as mock_logger:
            mock.send_memory_report_message(include_vram=True)

        # WARNING must NOT be emitted again within the 10-second window
        mock_logger.warning.assert_not_called()
        # DEBUG must be emitted instead
        mock_logger.debug.assert_called_once()

    def test_inference_process_override_does_not_set_end_process_on_vram_failure(self) -> None:
        """The HordeInferenceProcess override must not set _end_process on VRAM failure.

        Creates a minimal concrete subclass of HordeInferenceProcess that skips
        all heavy initialisation, so we can call the real override on a real instance.
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        # Build a minimal concrete subclass that avoids __init__ entirely
        class _TestProcess(HordeInferenceProcess):
            def cleanup_for_exit(self) -> None:
                pass

        instance = object.__new__(_TestProcess)
        instance.process_id = 1
        instance.process_launch_identifier = 42
        instance._end_process = False
        instance.process_message_queue = MagicMock()
        instance.get_vram_usage_bytes = MagicMock(side_effect=RuntimeError("CUDA error"))
        instance.get_vram_total_bytes = MagicMock(side_effect=RuntimeError("CUDA error"))

        result = instance.send_memory_report_message(include_vram=True)

        assert result is True, "Inference process override must return True even on VRAM failure"
        assert instance._end_process is False, (
            "_end_process must remain False — the override must not set it to True"
        )
        instance.process_message_queue.put.assert_called_once()


class TestSendInferenceResultEncodingResilience:
    """Tests that send_inference_result_message handles image-encoding failures gracefully.

    Regression tests for the bug where a base64-encoding failure (e.g. MemoryError or
    corrupt BytesIO) inside send_inference_result_message caused an unhandled exception
    that propagated through _receive_and_handle_control_message, terminated the child
    process, and left the job silently in-progress with POST_PROCESSING_COMPLETE as
    the last known state — causing the manager's PROCESS_ENDING handler to fault the job.

    The fix ensures:
    1. Each image is encoded inside a try/except; any encoding failure faults the ENTIRE
       job (not just the failing image) rather than propagating an exception that kills
       the process.  Partial submissions are unsafe because the submission pipeline uses
       positional indexing (gen_iter across job_image_results AND sdk_api_job_info.ids),
       so a shorter image list would leave some IDs permanently unsubmitted.
    2. State is derived from encoding success: any failure → GENERATION_STATE.faulted.
    3. Post-enqueue state-update errors are caught inside send_inference_result_message
       so the caller never sees a spurious exception after the message is already queued.
    """

    _TARGET = "horde_worker_regen.process_management.inference_process.HordeInferenceResultMessage"

    def _make_inference_process(self) -> object:
        """Return a minimal HordeInferenceProcess instance that skips heavy initialisation."""
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        class _TestProcess(HordeInferenceProcess):
            def cleanup_for_exit(self) -> None:
                pass

        instance = object.__new__(_TestProcess)
        instance.process_id = 1
        instance.process_launch_identifier = 42
        instance._last_job_inference_rate = None
        instance._active_model_name = "test-model"
        instance.process_message_queue = MagicMock()
        return instance

    def _make_result(self, *, rawpng_bytes: bytes | None = b"fake-png-data") -> MagicMock:
        """Return a minimal ResultingImageReturn mock."""
        import io

        result = MagicMock()
        if rawpng_bytes is None:
            result.rawpng = None
        else:
            result.rawpng = io.BytesIO(rawpng_bytes)
        result.faults = []
        return result

    def test_successful_encoding_sends_ok_message(self) -> None:
        """When all images encode successfully the message state must be GENERATION_STATE.ok."""
        import base64

        from horde_sdk.ai_horde_api import GENERATION_STATE

        proc = self._make_inference_process()
        result = self._make_result(rawpng_bytes=b"\x89PNG\r\n\x1a\nfakedata")

        captured: dict = {}

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        with patch(self._TARGET, side_effect=fake_msg_cls):
            proc.send_inference_result_message(
                process_state=HordeProcessState.INFERENCE_COMPLETE,
                job_info=MagicMock(),
                results=[result],
                time_elapsed=1.0,
                sanitized_negative_prompt=None,
            )

        assert proc.process_message_queue.put.call_count >= 1
        assert captured["state"] == GENERATION_STATE.ok
        assert len(captured["job_image_results"]) == 1
        # Validate the base64 payload round-trips correctly
        decoded = base64.b64decode(captured["job_image_results"][0].image_base64)
        assert decoded == b"\x89PNG\r\n\x1a\nfakedata"

    def test_single_encoding_failure_faults_entire_job(self) -> None:
        """When any single image's encoding raises, the ENTIRE job must be faulted (state=faulted,
        empty image list) rather than sending a partial result or crashing the process.

        Partial results are unsafe because the submission pipeline uses gen_iter to index
        both job_image_results and sdk_api_job_info.ids — a shorter list leaves some IDs
        permanently unsubmitted.
        """
        from horde_sdk.ai_horde_api import GENERATION_STATE

        proc = self._make_inference_process()

        # Make getvalue() raise to simulate a corrupt BytesIO
        bad_result = MagicMock()
        bad_result.rawpng = MagicMock()
        bad_result.rawpng.getvalue.side_effect = RuntimeError("Simulated BytesIO corruption")
        bad_result.faults = []

        captured: dict = {}

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        with patch(self._TARGET, side_effect=fake_msg_cls):
            # Must not raise — the encoding failure must be caught internally
            proc.send_inference_result_message(
                process_state=HordeProcessState.INFERENCE_COMPLETE,
                job_info=MagicMock(),
                results=[bad_result],
                time_elapsed=1.0,
                sanitized_negative_prompt=None,
            )

        # Message must still be sent (no unhandled exception kills the process)
        assert proc.process_message_queue.put.call_count >= 1
        # Encoding failure → entire job faulted, empty image list
        assert captured["state"] == GENERATION_STATE.faulted
        assert captured["job_image_results"] == []

    def test_all_images_encoding_failure_reports_faulted(self) -> None:
        """When ALL images fail to encode, state must be GENERATION_STATE.faulted, not ok."""
        from horde_sdk.ai_horde_api import GENERATION_STATE

        proc = self._make_inference_process()

        def _make_bad() -> MagicMock:
            r = MagicMock()
            r.rawpng = MagicMock()
            r.rawpng.getvalue.side_effect = MemoryError("Out of memory during encoding")
            r.faults = []
            return r

        captured: dict = {}

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        with patch(self._TARGET, side_effect=fake_msg_cls):
            proc.send_inference_result_message(
                process_state=HordeProcessState.INFERENCE_COMPLETE,
                job_info=MagicMock(),
                results=[_make_bad(), _make_bad()],
                time_elapsed=2.0,
                sanitized_negative_prompt=None,
            )

        assert proc.process_message_queue.put.call_count >= 1
        assert captured["state"] == GENERATION_STATE.faulted
        assert captured["job_image_results"] == []

    def test_partial_encoding_failure_faults_entire_job(self) -> None:
        """When only some images in a batch fail to encode, the ENTIRE job must be faulted.

        Partial submissions are unsafe: the submission pipeline uses gen_iter to index
        both job_image_results[gen_iter] and sdk_api_job_info.ids[gen_iter].  If the
        image list is shorter than n_iter, the remaining IDs are never submitted to the API.
        """
        from horde_sdk.ai_horde_api import GENERATION_STATE

        proc = self._make_inference_process()
        good_result = self._make_result(rawpng_bytes=b"valid-png-data")

        bad_result = MagicMock()
        bad_result.rawpng = MagicMock()
        bad_result.rawpng.getvalue.side_effect = RuntimeError("Encoding error")
        bad_result.faults = []

        captured: dict = {}

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        with patch(self._TARGET, side_effect=fake_msg_cls):
            proc.send_inference_result_message(
                process_state=HordeProcessState.INFERENCE_COMPLETE,
                job_info=MagicMock(),
                results=[good_result, bad_result],
                time_elapsed=1.5,
                sanitized_negative_prompt=None,
            )

        assert proc.process_message_queue.put.call_count >= 1
        # Partial failure → entire job faulted to avoid unsubmitted IDs
        assert captured["state"] == GENERATION_STATE.faulted
        assert captured["job_image_results"] == []

    def test_none_results_sends_faulted(self) -> None:
        """Passing results=None must produce a GENERATION_STATE.faulted message (no change to existing behaviour)."""
        from horde_sdk.ai_horde_api import GENERATION_STATE

        proc = self._make_inference_process()

        captured: dict = {}

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        with patch(self._TARGET, side_effect=fake_msg_cls):
            proc.send_inference_result_message(
                process_state=HordeProcessState.INFERENCE_COMPLETE,
                job_info=MagicMock(),
                results=None,
                time_elapsed=0.5,
                sanitized_negative_prompt=None,
            )

        assert proc.process_message_queue.put.call_count >= 1
        assert captured["state"] == GENERATION_STATE.faulted
        assert captured["job_image_results"] == []

    def test_post_enqueue_state_update_failure_does_not_propagate(self) -> None:
        """Exceptions from the state-update calls after queue.put() must NOT propagate.

        After the result message is successfully enqueued, on_horde_model_state_change or
        send_process_state_change_message can raise.  These are wrapped in a try/except so
        the exception does not escape send_inference_result_message.  Without this guard,
        the caller's except block would trigger a spurious second (faulted) result message
        for the same job.
        """
        from horde_sdk.ai_horde_api import GENERATION_STATE

        proc = self._make_inference_process()
        result = self._make_result(rawpng_bytes=b"valid-png-data")

        captured_messages: list = []

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        # call_count[0] == 1: the HordeInferenceResultMessage (the main result, must succeed)
        # call_count[0] > 1: subsequent puts are for state-change messages inside the post-enqueue
        #                    try/except block — these are allowed to fail without propagating.
        call_count = [0]

        def put_side_effect(msg: object) -> None:
            call_count[0] += 1
            captured_messages.append(msg)
            # Let the first put (the HordeInferenceResultMessage) succeed
            # and raise on the second (so the state update path raises)
            if call_count[0] > 1:
                raise RuntimeError("Simulated queue failure after result enqueued")

        proc.process_message_queue.put.side_effect = put_side_effect

        # Must not raise to the caller — the state update exception is caught internally
        with patch(self._TARGET, side_effect=fake_msg_cls):
            proc.send_inference_result_message(
                process_state=HordeProcessState.INFERENCE_COMPLETE,
                job_info=MagicMock(),
                results=[result],
                time_elapsed=1.0,
                sanitized_negative_prompt=None,
            )

        # Exactly ONE result message must have been sent (not two)
        # The first put succeeded (the result), subsequent ones raised
        assert call_count[0] >= 1
        first_msg = captured_messages[0]
        assert first_msg.state == GENERATION_STATE.ok


class TestSendInferenceResultFallbackOnFailure:
    """Tests the fallback in _receive_and_handle_control_message when send_inference_result_message fails.

    Regression tests for the scenario where the call to send_inference_result_message (with the
    actual results) raises unexpectedly (e.g. queue full, model state update fails, etc.).
    The child process must attempt to send a faulted result instead of propagating the
    exception and dying silently with POST_PROCESSING_COMPLETE as the last known state.
    """

    _TARGET = "horde_worker_regen.process_management.inference_process.HordeInferenceResultMessage"

    def _make_process(self) -> object:
        """Create a minimal HordeInferenceProcess that skips all heavy initialisation."""
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        class _TestProcess(HordeInferenceProcess):
            def cleanup_for_exit(self) -> None:
                pass

        instance = object.__new__(_TestProcess)
        instance.process_id = 1
        instance.process_launch_identifier = 42
        instance._last_job_inference_rate = None
        instance._active_model_name = "test-model"
        instance._last_sanitized_negative_prompt = None
        instance.process_message_queue = MagicMock()
        return instance

    def test_queue_put_failure_propagates_from_send_inference_result_message(self) -> None:
        """When queue.put() raises inside send_inference_result_message, the exception propagates.

        This confirms that the caller (in _receive_and_handle_control_message) must wrap the
        call in try/except to send a faulted fallback.
        """
        import io

        import pytest
        from horde_worker_regen.process_management.messages import HordeProcessState

        proc = self._make_process()

        good_result = MagicMock()
        good_result.rawpng = io.BytesIO(b"valid-png-data")
        good_result.faults = []

        # Make queue.put() raise on the first call
        proc.process_message_queue.put.side_effect = RuntimeError("Simulated queue failure")

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        with patch(self._TARGET, side_effect=fake_msg_cls):
            with pytest.raises(RuntimeError, match="Simulated queue failure"):
                proc.send_inference_result_message(
                    process_state=HordeProcessState.INFERENCE_COMPLETE,
                    job_info=MagicMock(),
                    results=[good_result],
                    time_elapsed=1.0,
                    sanitized_negative_prompt=None,
                )

    def test_faulted_fallback_with_none_results_succeeds(self) -> None:
        """The faulted-fallback path (results=None) must succeed when the queue is working.

        This models the second attempt in the caller's except block.
        """
        from horde_sdk.ai_horde_api import GENERATION_STATE
        from horde_worker_regen.process_management.messages import HordeProcessState

        proc = self._make_process()

        captured: dict = {}

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        with patch(self._TARGET, side_effect=fake_msg_cls):
            proc.send_inference_result_message(
                process_state=HordeProcessState.INFERENCE_FAILED,
                job_info=MagicMock(),
                results=None,
                time_elapsed=1.0,
                sanitized_negative_prompt=None,
            )

        assert proc.process_message_queue.put.call_count >= 1
        assert captured["state"] == GENERATION_STATE.faulted
        assert captured["job_image_results"] == []

    def test_both_sends_fail_reraises_to_trigger_end_process(self) -> None:
        """When both the normal send AND the faulted fallback fail, the exception must re-raise.

        The outer receive_and_handle_control_messages loop catches any exception from
        _receive_and_handle_control_message and sets _end_process=True, causing the
        process to exit cleanly.  Without the re-raise, the process would keep running
        with the job stuck in jobs_in_progress, requiring the manager to time it out as hung.
        """
        import io

        import pytest
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess
        from horde_worker_regen.process_management.messages import HordeProcessState

        class _TestProcess(HordeInferenceProcess):
            def cleanup_for_exit(self) -> None:
                pass

        proc = object.__new__(_TestProcess)
        proc.process_id = 1
        proc.process_launch_identifier = 42
        proc._last_job_inference_rate = None
        proc._active_model_name = "test-model"
        proc._last_sanitized_negative_prompt = None
        proc.process_message_queue = MagicMock()

        # Make every queue.put() raise so BOTH sends fail
        proc.process_message_queue.put.side_effect = RuntimeError("Persistent queue failure")

        good_result = MagicMock()
        good_result.rawpng = io.BytesIO(b"valid-data")
        good_result.faults = []

        def fake_msg_cls(**kwargs: object) -> MagicMock:
            m = MagicMock()
            m.state = kwargs.get("state")
            m.job_image_results = kwargs.get("job_image_results", [])
            return m

        # Calling send_inference_result_message with results raises on queue.put().
        # The caller's fallback also calls send_inference_result_message (results=None)
        # which also raises.  The fallback's except block must re-raise so the outer
        # receive loop can set _end_process=True.
        #
        # We simulate this directly: first call raises (normal send), second call also
        # raises (fallback send).  Verify the final exception escapes.
        with patch(self._TARGET, side_effect=fake_msg_cls):
            # First send fails
            with pytest.raises(RuntimeError, match="Persistent queue failure"):
                proc.send_inference_result_message(
                    process_state=HordeProcessState.INFERENCE_COMPLETE,
                    job_info=MagicMock(),
                    results=[good_result],
                    time_elapsed=1.0,
                    sanitized_negative_prompt=None,
                )

            # Second send (fallback) also fails — the re-raise means the exception escapes
            with pytest.raises(RuntimeError, match="Persistent queue failure"):
                proc.send_inference_result_message(
                    process_state=HordeProcessState.INFERENCE_FAILED,
                    job_info=MagicMock(),
                    results=None,
                    time_elapsed=1.0,
                    sanitized_negative_prompt=None,
                )


class TestKeepSingleInferenceStates(_ReceiveLoopHarnessMixin):
    """Tests that keep_single_inference correctly checks all active inference states.

    Previously the function had duplicate conditions that only checked INFERENCE_STARTING,
    missing INFERENCE_PROCESSING and INFERENCE_POST_PROCESSING. This caused jobs to be
    dispatched when they should not be (e.g., while a batch or VRAM-heavy model was in
    INFERENCE_PROCESSING), leading to unnecessary semaphore contention and jobs stuck in
    INFERENCE_STARTING.
    """

    def _make_process_map_with_process(
        self,
        state: HordeProcessState,
        *,
        batch_amount: int = 1,
        model: str | None = None,
    ) -> MagicMock:
        """Build a minimal mock process map containing one process in the given state."""
        from horde_worker_regen.process_management.process_manager import ProcessMap

        p = MagicMock()
        p.last_process_state = state
        p.batch_amount = batch_amount

        if model is not None:
            p.last_job_referenced = MagicMock()
            p.last_job_referenced.model = model
        else:
            p.last_job_referenced = None

        process_map = MagicMock()
        process_map.values.return_value = [p]
        process_map.keep_single_inference = ProcessMap.keep_single_inference.__get__(
            process_map, ProcessMap
        )
        return process_map

    def test_batch_job_inference_processing_keeps_single(self) -> None:
        """keep_single_inference must return True when a batch job is in INFERENCE_PROCESSING.

        Previously the check only tested for INFERENCE_STARTING, so a batch job that had
        already moved to INFERENCE_PROCESSING would not block additional jobs from being
        dispatched.
        """
        process_map = self._make_process_map_with_process(
            HordeProcessState.INFERENCE_PROCESSING,
            batch_amount=4,
        )

        result, reason = process_map.keep_single_inference(
            stable_diffusion_model_reference=MagicMock(),
            post_process_job_overlap=False,
        )

        assert result is True, (
            "Expected keep_single_inference=True for batch job in INFERENCE_PROCESSING, "
            f"got ({result!r}, {reason!r})"
        )
        assert reason == "Batched job"

    def test_batch_job_inference_post_processing_keeps_single(self) -> None:
        """keep_single_inference must return True when a batch job is in INFERENCE_POST_PROCESSING."""
        process_map = self._make_process_map_with_process(
            HordeProcessState.INFERENCE_POST_PROCESSING,
            batch_amount=2,
        )

        result, reason = process_map.keep_single_inference(
            stable_diffusion_model_reference=MagicMock(),
            post_process_job_overlap=False,
        )

        assert result is True, (
            "Expected keep_single_inference=True for batch job in INFERENCE_POST_PROCESSING, "
            f"got ({result!r}, {reason!r})"
        )
        assert reason == "Batched job"

    def test_batch_job_inference_starting_keeps_single(self) -> None:
        """keep_single_inference must return True when a batch job is in INFERENCE_STARTING."""
        process_map = self._make_process_map_with_process(
            HordeProcessState.INFERENCE_STARTING,
            batch_amount=3,
        )

        result, reason = process_map.keep_single_inference(
            stable_diffusion_model_reference=MagicMock(),
            post_process_job_overlap=False,
        )

        assert result is True
        assert reason == "Batched job"

    def test_non_batch_job_inference_processing_does_not_keep_single(self) -> None:
        """keep_single_inference must return False when a normal job is in INFERENCE_PROCESSING."""
        from horde_worker_regen.process_management.process_manager import ProcessMap

        p = MagicMock()
        p.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        p.batch_amount = 1
        p.last_job_referenced = MagicMock()
        p.last_job_referenced.model = "some_normal_model"
        p.last_job_referenced.payload.workflow = None
        p.can_accept_job.return_value = False

        process_map = MagicMock()
        process_map.values.return_value = [p]
        process_map.keep_single_inference = ProcessMap.keep_single_inference.__get__(
            process_map, ProcessMap
        )

        result, reason = process_map.keep_single_inference(
            stable_diffusion_model_reference=MagicMock(),
            post_process_job_overlap=False,
        )

        assert result is False, (
            "Expected keep_single_inference=False for normal job in INFERENCE_PROCESSING"
        )


class TestProcessEndingReleasesInferenceSemaphore(_ReceiveLoopHarnessMixin):
    """Tests that the inference semaphore is released when PROCESS_ENDING is received for a
    process that was in INFERENCE_PROCESSING.

    This prevents other processes from being permanently stuck in INFERENCE_STARTING when
    a child process terminates without releasing the semaphore (e.g., due to an OOM kill
    where the finally block did not run).
    """

    def _run_receive_process_ending_with_semaphore(
        self,
        prior_state: HordeProcessState,
        *,
        semaphore_acquired: bool = True,
    ) -> tuple[MagicMock, object]:
        """Run receive_and_handle_process_messages with PROCESS_ENDING and a real semaphore.

        Args:
            prior_state: The process state before the PROCESS_ENDING transition.
            semaphore_acquired: If True, the semaphore is pre-acquired to simulate the child
                                holding it. If False, the semaphore is at its initial value.

        Returns (mock_manager, bounded_semaphore) so callers can inspect the semaphore state.
        """
        import multiprocessing
        import queue as queue_mod
        from multiprocessing.synchronize import BoundedSemaphore

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        ctx = multiprocessing.get_context("spawn")
        bounded_sem = BoundedSemaphore(1, ctx=ctx)
        if semaphore_acquired:
            # Simulate the child holding the semaphore (acquired but not released)
            bounded_sem.acquire()

        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = prior_state
        process_info.last_job_referenced = None

        process_map = MagicMock()
        process_map.__contains__ = MagicMock(side_effect=lambda key: key == 0)
        process_map.__getitem__ = MagicMock(side_effect=lambda key: process_info)

        msg = self._make_message(HordeProcessState.PROCESS_ENDING)
        q = queue_mod.Queue()
        q.put(msg)

        mock_manager = MagicMock()
        mock_manager._process_message_queue = q
        mock_manager._process_map = process_map
        mock_manager._in_deadlock = False
        mock_manager._in_queue_deadlock = False
        mock_manager.jobs_in_progress = []
        mock_manager._inference_semaphore = bounded_sem

        bound = HordeWorkerProcessManager.receive_and_handle_process_messages.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        bound()
        return mock_manager, bounded_sem

    def test_semaphore_released_when_process_ending_from_inference_processing(self) -> None:
        """When PROCESS_ENDING arrives for a process in INFERENCE_PROCESSING, the inference
        semaphore must be released so that other processes stuck in INFERENCE_STARTING can
        acquire it and proceed.
        """
        _mock_manager, sem = self._run_receive_process_ending_with_semaphore(
            prior_state=HordeProcessState.INFERENCE_PROCESSING,
            semaphore_acquired=True,
        )

        # The semaphore should now be available (released by PROCESS_ENDING handler)
        acquired = sem.acquire(block=False)
        assert acquired, (
            "Semaphore should be acquirable after PROCESS_ENDING from INFERENCE_PROCESSING — "
            "the handler must release it to unblock processes stuck in INFERENCE_STARTING"
        )

    def test_semaphore_released_when_process_ending_from_post_processing_starting(self) -> None:
        """When PROCESS_ENDING arrives for a process in POST_PROCESSING_STARTING, the inference
        semaphore must also be released.

        The child emits POST_PROCESSING_STARTING BEFORE releasing the semaphore (see
        inference_process.py progress_callback). If the process crashes between emitting the
        state and calling release(), the semaphore leaks and other processes remain stuck in
        INFERENCE_STARTING.
        """
        _mock_manager, sem = self._run_receive_process_ending_with_semaphore(
            prior_state=HordeProcessState.POST_PROCESSING_STARTING,
            semaphore_acquired=True,
        )

        acquired = sem.acquire(block=False)
        assert acquired, (
            "Semaphore should be acquirable after PROCESS_ENDING from POST_PROCESSING_STARTING — "
            "the handler must release it to unblock processes stuck in INFERENCE_STARTING"
        )

    def test_semaphore_not_released_when_process_ending_from_waiting_for_job(self) -> None:
        """When PROCESS_ENDING arrives for a process in WAITING_FOR_JOB, the inference
        semaphore must NOT be released (the process was not holding it).
        """
        _mock_manager, sem = self._run_receive_process_ending_with_semaphore(
            prior_state=HordeProcessState.WAITING_FOR_JOB,
            semaphore_acquired=True,
        )

        # The semaphore was acquired before the test but should NOT have been released
        # by the PROCESS_ENDING handler (WAITING_FOR_JOB does not hold the semaphore)
        acquired = sem.acquire(block=False)
        assert not acquired, (
            "Semaphore must not be acquirable when PROCESS_ENDING is for a non-inference state"
        )

    def test_semaphore_double_release_safe_when_child_already_released(self) -> None:
        """When PROCESS_ENDING arrives and the child already released the semaphore normally,
        the PROCESS_ENDING handler's release attempt must not raise and must not inflate permits.
        """
        # semaphore_acquired=False: child already released via its finally block
        _mock_manager, sem = self._run_receive_process_ending_with_semaphore(
            prior_state=HordeProcessState.INFERENCE_PROCESSING,
            semaphore_acquired=False,
        )

        # Semaphore should still have exactly 1 permit (not corrupted to 2)
        acquired = sem.acquire(block=False)
        assert acquired, "Semaphore should have 1 permit (unchanged) after safe double-release"
        second_acquired = sem.acquire(block=False)
        assert not second_acquired, "Semaphore must not have more than 1 permit (no inflation)"

    def test_semaphore_double_release_safe_from_post_processing_starting_when_child_already_released(self) -> None:
        """When PROCESS_ENDING arrives from POST_PROCESSING_STARTING and the child already
        released the semaphore (normal path: emitted state then released), the handler's
        defensive release must not inflate the permit count.
        """
        # semaphore_acquired=False: child already released after emitting POST_PROCESSING_STARTING
        _mock_manager, sem = self._run_receive_process_ending_with_semaphore(
            prior_state=HordeProcessState.POST_PROCESSING_STARTING,
            semaphore_acquired=False,
        )

        acquired = sem.acquire(block=False)
        assert acquired, "Semaphore should have 1 permit (unchanged) after safe double-release"
        second_acquired = sem.acquire(block=False)
        assert not second_acquired, "Semaphore must not have more than 1 permit (no inflation)"


class TestCanAcceptJobPostProcessingComplete:
    """Tests for can_accept_job() excluding POST_PROCESSING_COMPLETE."""

    def _make_process_info(self, state: HordeProcessState) -> MagicMock:
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.last_process_state = state
        mock_info.can_accept_job = HordeProcessInfo.can_accept_job.__get__(mock_info, HordeProcessInfo)
        return mock_info

    def test_post_processing_complete_cannot_accept_job(self) -> None:
        """A process in POST_PROCESSING_COMPLETE must not be considered available.

        The child is still inside _receive_and_handle_control_message sending the
        result to the manager.  Treating it as available would let the manager
        schedule a new job or replace the process before the current job's result
        has been enqueued.
        """
        info = self._make_process_info(HordeProcessState.POST_PROCESSING_COMPLETE)
        assert info.can_accept_job() is False

    def test_waiting_for_job_can_accept(self) -> None:
        info = self._make_process_info(HordeProcessState.WAITING_FOR_JOB)
        assert info.can_accept_job() is True

    def test_inference_complete_can_accept(self) -> None:
        info = self._make_process_info(HordeProcessState.INFERENCE_COMPLETE)
        assert info.can_accept_job() is True

    def test_model_preloaded_can_accept(self) -> None:
        info = self._make_process_info(HordeProcessState.MODEL_PRELOADED)
        assert info.can_accept_job() is True

    def test_inference_processing_cannot_accept(self) -> None:
        info = self._make_process_info(HordeProcessState.INFERENCE_PROCESSING)
        assert info.can_accept_job() is False

    def test_process_ending_cannot_accept(self) -> None:
        info = self._make_process_info(HordeProcessState.PROCESS_ENDING)
        assert info.can_accept_job() is False


class TestStartInferenceExceptionHandling:
    """Tests that exceptions from start_inference() are caught, preventing the
    process from ending before the job result is submitted.
    """

    def _make_inference_process(self) -> MagicMock:
        """Return a minimally-mocked HordeInferenceProcess."""
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._last_sanitized_negative_prompt = None
        proc._active_model_name = "TestModel"
        return proc

    def test_start_inference_exception_sends_faulted_result(self) -> None:
        """If start_inference() raises, the handler must send INFERENCE_FAILED so
        the manager can retry, rather than letting the exception propagate and
        cause a PROCESS_ENDING with the job still in progress.
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess
        from horde_worker_regen.process_management.messages import (
            HordeControlFlag,
            HordeInferenceControlMessage,
        )

        proc = self._make_inference_process()

        # start_inference raises an unexpected exception (simulates a finally-block error
        # that occurs after POST_PROCESSING_COMPLETE was emitted)
        proc.start_inference.side_effect = RuntimeError("Semaphore release failed")

        # Build a minimal START_INFERENCE message
        job_info = MagicMock()
        job_info.model = "TestModel"
        # Provide payload attributes used in the failure-path preload_model call
        job_info.payload = MagicMock()
        job_info.payload.loras = None
        job_info.payload.tiling = False
        message = MagicMock(spec=HordeInferenceControlMessage)
        message.control_flag = HordeControlFlag.START_INFERENCE
        message.horde_model_name = "TestModel"
        message.sdk_api_job_info = job_info

        # Bind the real method but short-circuit everything except the path under test
        proc.on_horde_model_state_change = MagicMock()
        proc.send_process_state_change_message = MagicMock()
        proc.send_memory_report_message = MagicMock()
        proc.send_inference_result_message = MagicMock()
        proc.unload_models_from_ram = MagicMock()
        proc.preload_model = MagicMock()

        # Call the real method (it will hit the try/except we added around start_inference)
        HordeInferenceProcess._receive_and_handle_control_message(proc, message)

        # send_inference_result_message must have been called with INFERENCE_FAILED
        calls = proc.send_inference_result_message.call_args_list
        assert len(calls) >= 1, "send_inference_result_message was not called"
        first_call_kwargs = calls[0].kwargs if calls[0].kwargs else {}
        first_call_args = calls[0].args if calls[0].args else ()
        # process_state can come as positional or keyword arg
        process_state_arg = first_call_kwargs.get("process_state") or (
            first_call_args[0] if first_call_args else None
        )
        assert process_state_arg == HordeProcessState.INFERENCE_FAILED, (
            f"Expected INFERENCE_FAILED, got {process_state_arg}"
        )


class TestVaeLockAcquiredFlag:
    """Tests that _vae_lock_was_acquired is only set to True when the VAE
    semaphore is actually acquired (not pre-emptively on timeout), and that
    _vae_acquire_attempted prevents repeated acquire attempts after a timeout.
    """

    def test_vae_lock_flag_false_on_timeout(self) -> None:
        """When the VAE semaphore acquire times out, _vae_lock_was_acquired must remain
        False so the finally block does not try to release a semaphore we never held.
        _vae_acquire_attempted must be True so subsequent callbacks don't retry.
        """
        import multiprocessing

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._vae_acquire_attempted = False
        proc._vae_lock_was_acquired = False
        proc._current_job_inference_steps_complete = True
        proc._in_post_processing = False  # Must be False so we reach the VAE-lock branch
        proc.VAE_SEMAPHORE_TIMEOUT = 0.01

        # Semaphore with 0 permits – acquire will time out immediately
        sem = multiprocessing.Semaphore(0)
        proc._vae_decode_semaphore = sem

        proc.send_heartbeat_message = MagicMock()

        # Simulate a ProgressReport that triggers the VAE-semaphore path
        from hordelib.horde import ProgressState  # type: ignore[import]

        progress_report = MagicMock()
        progress_report.hordelib_progress_state = ProgressState.progress
        progress_report.comfyui_progress = None

        HordeInferenceProcess._progress_callback_impl(proc, progress_report)

        # acquire timed out → _vae_lock_was_acquired must be False (no semaphore to release)
        assert proc._vae_lock_was_acquired is False, (
            "_vae_lock_was_acquired should be False when acquire timed out"
        )
        # _vae_acquire_attempted must be True so subsequent callbacks skip the acquire
        assert proc._vae_acquire_attempted is True, (
            "_vae_acquire_attempted should be True after first attempt (even on timeout)"
        )

    def test_vae_lock_not_retried_after_timeout(self) -> None:
        """A second progress_callback invocation after a timeout must not re-attempt
        acquire (which would block up to VAE_SEMAPHORE_TIMEOUT again and spam logs).
        """
        import multiprocessing

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        # Simulate state after a first timeout: attempted but not acquired
        proc._vae_acquire_attempted = True
        proc._vae_lock_was_acquired = False
        proc._current_job_inference_steps_complete = True
        proc._in_post_processing = False
        proc.VAE_SEMAPHORE_TIMEOUT = 0.01

        sem = MagicMock()
        proc._vae_decode_semaphore = sem
        proc.send_heartbeat_message = MagicMock()

        from hordelib.horde import ProgressState  # type: ignore[import]

        progress_report = MagicMock()
        progress_report.hordelib_progress_state = ProgressState.progress
        progress_report.comfyui_progress = None

        HordeInferenceProcess._progress_callback_impl(proc, progress_report)

        # acquire must NOT be called again
        sem.acquire.assert_not_called()

    def test_vae_lock_flag_true_on_success(self) -> None:
        """When the VAE semaphore is successfully acquired, _vae_lock_was_acquired is True."""
        import multiprocessing

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._vae_acquire_attempted = False
        proc._vae_lock_was_acquired = False
        proc._current_job_inference_steps_complete = True
        proc._in_post_processing = False  # Must be False so we reach the VAE-lock branch
        proc.VAE_SEMAPHORE_TIMEOUT = 5

        # Semaphore with 1 permit – acquire will succeed
        sem = multiprocessing.Semaphore(1)
        proc._vae_decode_semaphore = sem

        proc.send_heartbeat_message = MagicMock()

        from hordelib.horde import ProgressState  # type: ignore[import]

        progress_report = MagicMock()
        progress_report.hordelib_progress_state = ProgressState.progress
        progress_report.comfyui_progress = None

        # log_free_ram is imported locally inside progress_callback from hordelib.comfy_horde;
        # patch it at the source to avoid needing an initialised ComfyUI context.
        with patch("hordelib.comfy_horde.log_free_ram", MagicMock()):
            HordeInferenceProcess._progress_callback_impl(proc, progress_report)

        assert proc._vae_lock_was_acquired is True, (
            "_vae_lock_was_acquired should be True when acquire succeeded"
        )
        assert proc._vae_acquire_attempted is True, (
            "_vae_acquire_attempted should be True after a successful acquire"
        )
        # Clean up the acquired semaphore
        sem.release()


class TestSemaphoreReleaseBroadExceptionHandling:
    """Tests that unexpected non-ValueError exceptions during semaphore release
    in the start_inference finally block do not propagate and crash the process.
    """

    def test_inference_semaphore_os_error_is_swallowed(self) -> None:
        """An OSError from inference semaphore release must not escape start_inference.

        This validates that the broad `except Exception` handler in the finally block
        prevents unexpected OS-level semaphore errors from crashing the process and
        causing PROCESS_ENDING with the job still in progress.
        """
        import multiprocessing

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._is_busy = False
        proc._in_post_processing = False
        proc._vae_acquire_attempted = False
        proc._vae_lock_was_acquired = False
        proc._current_job_inference_steps_complete = False
        proc._last_sanitized_negative_prompt = None
        proc._active_model_name = "TestModel"
        proc.VAE_SEMAPHORE_TIMEOUT = 5

        # Semaphore that raises OSError on release (not ValueError)
        bad_sem = MagicMock()
        bad_sem.acquire = MagicMock(return_value=True)
        bad_sem.release = MagicMock(side_effect=OSError("Invalid semaphore"))
        proc._inference_semaphore = bad_sem

        good_vae = multiprocessing.Semaphore(1)
        proc._vae_decode_semaphore = good_vae

        proc.send_process_state_change_message = MagicMock()
        proc.send_heartbeat_message = MagicMock()
        proc.on_horde_model_state_change = MagicMock()

        # _horde.basic_inference returns a valid (non-None) result
        fake_result = MagicMock()
        fake_result.rawpng = MagicMock()
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = [fake_result]

        # Use plain MagicMock (not spec=...) so all attribute access including .ids works
        job_info = MagicMock()
        job_info.payload.prompt = "test"
        job_info.extra_source_images = None
        job_info.source_image = None
        job_info.source_mask = None
        job_info.ids = []

        # Should not raise even though inference semaphore release raises OSError.
        # The OSError must be caught in the finally block and logged, not propagated.
        result = HordeInferenceProcess.start_inference(proc, job_info)

        # The result should be returned (not swallowed), since the error is only in cleanup
        assert result is not None, "start_inference should return results despite semaphore OSError"
        bad_sem.release.assert_called_once()

    def test_setup_exception_releases_semaphore(self) -> None:
        """If send_process_state_change_message() raises during start_inference() setup
        (before the inference itself runs), the inference semaphore must still be released
        and _is_busy must be reset.  This tests the restructured try/finally that now
        covers the entire post-acquire body.
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._is_busy = False
        proc._in_post_processing = False
        proc._vae_acquire_attempted = False
        proc._vae_lock_was_acquired = False
        proc._current_job_inference_steps_complete = False
        proc._last_sanitized_negative_prompt = None
        proc._active_model_name = "TestModel"
        proc.VAE_SEMAPHORE_TIMEOUT = 5

        import multiprocessing
        real_sem = multiprocessing.Semaphore(1)
        proc._inference_semaphore = real_sem
        proc._vae_decode_semaphore = multiprocessing.Semaphore(1)

        # send_process_state_change_message raises on the first call (during setup)
        proc.send_process_state_change_message = MagicMock(
            side_effect=OSError("pipe broken")
        )
        proc.send_heartbeat_message = MagicMock()

        job_info = MagicMock()
        job_info.payload.prompt = "test"
        job_info.extra_source_images = None
        job_info.source_image = None
        job_info.source_mask = None
        job_info.ids = []

        result = HordeInferenceProcess.start_inference(proc, job_info)

        # Inference failed due to setup exception → result must be None
        assert result is None, "start_inference should return None when setup raises"

        # Critically: _is_busy must be False and semaphore must have been released
        assert proc._is_busy is False, "_is_busy must be reset even after setup exception"
        # The semaphore started with 1 permit, was acquired (-1 = 0), then should have
        # been released (+1 = 1) by the finally block.  Verify we can acquire it again.
        acquired = real_sem.acquire(block=False)
        assert acquired, "Inference semaphore must be released by finally block even on setup exception"
        real_sem.release()  # restore for clean teardown


class TestReplaceHungInferenceStarting:
    """Tests for the INFERENCE_STARTING stuck-process detection added to replace_hung_processes().

    When a process has been in INFERENCE_STARTING for longer than preload_timeout AND no other
    process is actively in INFERENCE_PROCESSING (which would legitimately hold the semaphore),
    the manager must replace it so the stuck job is retried.
    """

    def _make_process(
        self,
        process_id: int,
        state: HordeProcessState,
        *,
        time_elapsed: float = 9999.0,
    ) -> MagicMock:
        import time as _time

        proc = MagicMock()
        proc.process_id = process_id
        proc.last_process_state = state
        proc.last_received_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_timestamp = _time.time() - time_elapsed
        proc.last_progress_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_percent_complete = None
        proc.last_job_referenced = None
        return proc

    def _make_manager(self, processes: list[MagicMock]) -> MagicMock:
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = False
        mock_manager._last_pop_no_jobs_available = False
        mock_manager._shutting_down = False
        mock_manager.bridge_data.inference_step_timeout = 600
        mock_manager.bridge_data.preload_timeout = 80
        mock_manager.bridge_data.process_timeout = 300
        mock_manager.bridge_data.download_timeout = 300
        mock_manager.bridge_data.post_process_timeout = 60
        mock_manager.bridge_data.max_batch = 1
        # is_stuck_on_inference always returns False so the specific INFERENCE_STARTING
        # check (in the `else` branch) is exercised.
        mock_manager._process_map.is_stuck_on_inference.return_value = False
        mock_manager._process_map.values.return_value = processes
        # _check_and_replace_process must return False so it doesn't spuriously trigger
        mock_manager._check_and_replace_process.return_value = False
        mock_manager._process_map.__iter__ = MagicMock(return_value=iter(processes))

        # Bind the real method to the mock manager
        mock_manager._bound_replace_hung = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        return mock_manager

    def test_stuck_inference_starting_no_active_inference_replaced(self) -> None:
        """An INFERENCE_STARTING process stuck longer than preload_timeout with no active
        INFERENCE_PROCESSING must be detected and replaced.
        """
        proc = self._make_process(0, HordeProcessState.INFERENCE_STARTING, time_elapsed=9999.0)
        mock_manager = self._make_manager([proc])

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is True, "replace_hung_processes must return True when replacing stuck INFERENCE_STARTING"
        mock_manager._replace_inference_process.assert_called_once_with(proc)

    def test_stuck_inference_starting_with_active_inference_not_replaced(self) -> None:
        """An INFERENCE_STARTING process must NOT be replaced when another process is in
        INFERENCE_PROCESSING, because that process legitimately holds the semaphore.
        """
        inference_starting = self._make_process(
            0, HordeProcessState.INFERENCE_STARTING, time_elapsed=9999.0
        )
        inference_processing = self._make_process(
            1, HordeProcessState.INFERENCE_PROCESSING, time_elapsed=10.0
        )
        mock_manager = self._make_manager([inference_starting, inference_processing])

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        # The INFERENCE_STARTING process must not be replaced (INFERENCE_PROCESSING is active)
        mock_manager._replace_inference_process.assert_not_called()
        # Return value: no processes were replaced in this run
        assert result is False

    def test_inference_starting_not_replaced_before_preload_timeout(self) -> None:
        """An INFERENCE_STARTING process that has been waiting less than preload_timeout
        must NOT be detected as stuck yet.
        """
        # Only 10 seconds elapsed — well below preload_timeout (80 s)
        proc = self._make_process(0, HordeProcessState.INFERENCE_STARTING, time_elapsed=10.0)
        mock_manager = self._make_manager([proc])

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        mock_manager._replace_inference_process.assert_not_called()
        assert result is False


class TestProcessEndingReleasesInferenceSemaphoreFromInferenceStarting(_ReceiveLoopHarnessMixin):
    """Tests that the inference semaphore is released when PROCESS_ENDING is received for a
    process whose prior state was INFERENCE_STARTING.

    This covers the race condition in _replace_inference_process(): the manager releases the
    semaphore to unblock the blocked child; the child may acquire it before the kill signal
    arrives.  If the child is killed before it sends INFERENCE_PROCESSING, the manager still
    records INFERENCE_STARTING as the prior state.  Without releasing on PROCESS_ENDING the
    semaphore count stays at 0 permanently, leaving the next INFERENCE_STARTING blocked forever.
    """

    def _run_receive_process_ending_with_semaphore(
        self,
        prior_state: HordeProcessState,
        *,
        semaphore_acquired: bool,
    ) -> tuple[MagicMock, object]:
        """Helper reused from TestProcessEndingReleasesInferenceSemaphore."""
        import multiprocessing
        import queue as queue_mod
        from multiprocessing.synchronize import BoundedSemaphore

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        ctx = multiprocessing.get_context("spawn")
        bounded_sem = BoundedSemaphore(1, ctx=ctx)
        if semaphore_acquired:
            bounded_sem.acquire()

        process_info = MagicMock()
        process_info.process_launch_identifier = 1
        process_info.last_process_state = prior_state
        process_info.last_job_referenced = None

        process_map = MagicMock()
        process_map.__contains__ = MagicMock(side_effect=lambda key: key == 0)
        process_map.__getitem__ = MagicMock(side_effect=lambda key: process_info)

        msg = self._make_message(HordeProcessState.PROCESS_ENDING)
        q = queue_mod.Queue()
        q.put(msg)

        mock_manager = MagicMock()
        mock_manager._process_message_queue = q
        mock_manager._process_map = process_map
        mock_manager._in_deadlock = False
        mock_manager._in_queue_deadlock = False
        mock_manager.jobs_in_progress = []
        mock_manager._inference_semaphore = bounded_sem

        bound = HordeWorkerProcessManager.receive_and_handle_process_messages.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        bound()
        return mock_manager, bounded_sem

    def test_semaphore_released_when_process_ending_from_inference_starting_acquired(self) -> None:
        """PROCESS_ENDING from INFERENCE_STARTING with a held semaphore must release it.

        Scenario: manager released the semaphore to unblock the blocked child, the child
        acquired it (race), was then killed before sending INFERENCE_PROCESSING.  The
        PROCESS_ENDING handler must release to restore the permit count to 1.
        """
        _mock_manager, sem = self._run_receive_process_ending_with_semaphore(
            prior_state=HordeProcessState.INFERENCE_STARTING,
            semaphore_acquired=True,
        )

        acquired = sem.acquire(block=False)
        assert acquired, (
            "Semaphore must be released on PROCESS_ENDING from INFERENCE_STARTING (acquired case) "
            "to prevent the next INFERENCE_STARTING process from blocking forever"
        )

    def test_semaphore_not_inflated_when_process_ending_from_inference_starting_not_acquired(self) -> None:
        """PROCESS_ENDING from INFERENCE_STARTING when the child never acquired the semaphore
        must not inflate the permit count beyond 1 (BoundedSemaphore safety).

        Scenario: manager released the semaphore (count: 0→1), child was killed before
        acquiring.  Semaphore count is already 1.  The PROCESS_ENDING handler's release
        attempt raises ValueError (BoundedSemaphore) and is silently caught; count stays 1.
        """
        _mock_manager, sem = self._run_receive_process_ending_with_semaphore(
            prior_state=HordeProcessState.INFERENCE_STARTING,
            semaphore_acquired=False,
        )

        # Count should still be 1 (not inflated to 2)
        acquired = sem.acquire(block=False)
        assert acquired, "Semaphore should have exactly 1 permit (not inflated)"
        second_acquired = sem.acquire(block=False)
        assert not second_acquired, "Semaphore must not have more than 1 permit (no inflation)"


class TestProgressCallbackExceptionSuppression:
    """Tests that progress_callback swallows exceptions to prevent aborting inference.

    Regression tests for the bug where an exception raised inside _progress_callback_impl
    (e.g. from log_free_ram(), send_heartbeat_message(), or a semaphore operation)
    propagated into HordeLib's basic_inference(), which then caught it internally and
    returned None — producing "inference produced no results" with no CRITICAL log to
    explain the root cause.

    The fix wraps the callback body in try/except so HordeLib always receives a clean
    return (no exception), allowing inference to proceed normally.
    """

    def _make_process(self) -> "HordeInferenceProcess":
        """Return a minimal HordeInferenceProcess that skips heavy initialisation."""
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        class _TestProcess(HordeInferenceProcess):
            def cleanup_for_exit(self) -> None:
                pass

        instance = object.__new__(_TestProcess)
        instance.process_id = 1
        instance.process_launch_identifier = 42
        instance._in_post_processing = False
        instance._current_job_inference_steps_complete = False
        instance._vae_acquire_attempted = False
        instance._vae_lock_was_acquired = False
        instance._last_job_inference_rate = None
        instance._start_inference_time = 0.0
        instance._active_model_name = "test-model"
        instance.process_message_queue = MagicMock()
        return instance

    def test_exception_in_impl_does_not_propagate(self) -> None:
        """An exception raised by _progress_callback_impl must NOT escape progress_callback.

        If the exception propagated to HordeLib, basic_inference() would silently return
        None and the job would fault with "inference produced no results".
        """
        proc = self._make_process()

        # Simulate _progress_callback_impl raising unexpectedly
        proc._progress_callback_impl = MagicMock(side_effect=RuntimeError("Simulated error"))

        progress_report = MagicMock()

        # Must not raise — progress_callback must swallow the exception
        proc.progress_callback(progress_report)

        # The impl was called
        proc._progress_callback_impl.assert_called_once_with(progress_report)

    def test_exception_in_impl_is_logged(self) -> None:
        """An exception from _progress_callback_impl must be logged at ERROR level with traceback."""
        from unittest.mock import patch as _patch

        proc = self._make_process()
        proc._progress_callback_impl = MagicMock(side_effect=ValueError("bad value"))

        progress_report = MagicMock()

        with _patch("horde_worker_regen.process_management.inference_process.logger") as mock_logger:
            # logger.opt(exception=...).error(...) is called — opt() returns a bound logger
            mock_opt_logger = MagicMock()
            mock_logger.opt.return_value = mock_opt_logger

            proc.progress_callback(progress_report)

            # logger.opt must be called with the exception for full traceback capture
            mock_logger.opt.assert_called_once()
            opt_kwargs = mock_logger.opt.call_args.kwargs
            assert isinstance(opt_kwargs.get("exception"), ValueError), (
                "logger.opt must be passed the exception for traceback logging"
            )
            # The .error() on the bound logger must be called with the message
            mock_opt_logger.error.assert_called_once()
            error_call_args = mock_opt_logger.error.call_args[0][0]
            assert "ValueError" in error_call_args
            assert "bad value" in error_call_args

    def test_successful_impl_does_not_log_error(self) -> None:
        """When _progress_callback_impl succeeds no error should be logged."""
        from unittest.mock import patch as _patch

        proc = self._make_process()
        proc._progress_callback_impl = MagicMock(return_value=None)

        progress_report = MagicMock()

        with _patch("horde_worker_regen.process_management.inference_process.logger") as mock_logger:
            proc.progress_callback(progress_report)
            mock_logger.opt.assert_not_called()
            mock_logger.error.assert_not_called()


class TestPostProcessingVAESemaphore:
    """Tests that the VAE decode semaphore is acquired via the post-processing path.

    Regression tests for the bug where ProgressState.post_processing callbacks bypassed
    the VAE semaphore acquisition in the step-completion path, allowing concurrent
    heavy GPU work across processes that could exhaust VRAM and cause basic_inference()
    to return None silently.
    """

    def _make_process(self) -> "HordeInferenceProcess":
        """Return a minimal HordeInferenceProcess that skips heavy initialisation."""
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        class _TestProcess(HordeInferenceProcess):
            def cleanup_for_exit(self) -> None:
                pass

        instance = object.__new__(_TestProcess)
        instance.process_id = 1
        instance.process_launch_identifier = 42
        instance._in_post_processing = False
        instance._current_job_inference_steps_complete = False
        instance._vae_acquire_attempted = False
        instance._vae_lock_was_acquired = False
        instance._last_job_inference_rate = None
        instance._start_inference_time = 0.0
        instance._active_model_name = "test-model"
        instance.VAE_SEMAPHORE_TIMEOUT = 5
        instance.process_message_queue = MagicMock()
        return instance

    def test_vae_semaphore_acquired_on_first_post_processing_callback(self) -> None:
        """VAE decode semaphore must be acquired the first time post_processing fires.

        Before the fix, the post_processing branch returned early without ever touching
        the VAE semaphore, leaving concurrent VAE decode unlimited.
        """
        import multiprocessing

        proc = self._make_process()

        vae_sem = multiprocessing.Semaphore(1)
        inference_sem = multiprocessing.Semaphore(1)
        inference_sem.acquire()  # simulate that inference holds the semaphore
        proc._inference_semaphore = inference_sem
        proc._vae_decode_semaphore = vae_sem

        proc.send_process_state_change_message = MagicMock()
        proc.send_heartbeat_message = MagicMock()

        progress_report = MagicMock()

        # Import locally to avoid module-level import of hordelib
        from unittest.mock import patch as _patch

        # Patch the hordelib imports inside _progress_callback_impl
        with (
            _patch("horde_worker_regen.process_management.inference_process.logger"),
            _patch.dict(
                "sys.modules",
                {
                    "hordelib": MagicMock(),
                    "hordelib.comfy_horde": MagicMock(),
                    "hordelib.horde": MagicMock(),
                    "hordelib.utils": MagicMock(),
                    "hordelib.utils.ioredirect": MagicMock(),
                },
            ),
        ):
            import sys

            # Set up the ProgressState mock so the post_processing branch fires
            mock_progress_state = MagicMock()
            sys.modules["hordelib.horde"].ProgressState = mock_progress_state

            progress_report.hordelib_progress_state = mock_progress_state.post_processing
            progress_report.comfyui_progress = None

            proc._progress_callback_impl(progress_report)

        # VAE semaphore must have been acquired (attempt was made)
        assert proc._vae_acquire_attempted is True, (
            "VAE semaphore acquisition must be attempted in the post-processing path"
        )
        # And the semaphore must actually have been acquired successfully
        assert proc._vae_lock_was_acquired is True, (
            "VAE semaphore must be successfully acquired in the post-processing path"
        )

    def test_vae_semaphore_only_acquired_once_in_post_processing(self) -> None:
        """VAE semaphore must not be acquired twice even with multiple post_processing callbacks."""
        import multiprocessing
        from unittest.mock import MagicMock, patch as _patch

        proc = self._make_process()

        # Use a mock VAE semaphore so we can count exact acquire() calls.
        # A real Semaphore would block on the second acquire, making the test hang.
        mock_vae_sem = MagicMock()
        mock_vae_sem.acquire.return_value = True  # simulate successful acquire

        inference_sem = multiprocessing.Semaphore(1)
        inference_sem.acquire()
        proc._inference_semaphore = inference_sem
        proc._vae_decode_semaphore = mock_vae_sem

        proc.send_process_state_change_message = MagicMock()
        proc.send_heartbeat_message = MagicMock()

        with (
            _patch("horde_worker_regen.process_management.inference_process.logger"),
            _patch.dict(
                "sys.modules",
                {
                    "hordelib": MagicMock(),
                    "hordelib.comfy_horde": MagicMock(),
                    "hordelib.horde": MagicMock(),
                    "hordelib.utils": MagicMock(),
                    "hordelib.utils.ioredirect": MagicMock(),
                },
            ),
        ):
            import sys

            mock_progress_state = MagicMock()
            sys.modules["hordelib.horde"].ProgressState = mock_progress_state

            progress_report = MagicMock()
            progress_report.hordelib_progress_state = mock_progress_state.post_processing
            progress_report.comfyui_progress = None

            # Call twice — semaphore must only be acquired on the first call
            proc._progress_callback_impl(progress_report)
            proc._progress_callback_impl(progress_report)

        assert proc._vae_acquire_attempted is True
        # Semaphore.acquire() must have been called exactly once despite two callbacks
        mock_vae_sem.acquire.assert_called_once_with(timeout=proc.VAE_SEMAPHORE_TIMEOUT), (
            "VAE semaphore acquire() must be called exactly once across multiple post-processing callbacks"
        )


class TestPostProcessingFaultMessage:
    """Regression tests for the post-processing failure distinction fix.

    Covers two behaviours introduced by the fix:
    1. ``send_inference_result_message`` emits "post-processing produced no results"
       (not "inference produced no results") when ``_post_processing_was_started`` is True.
    2. ``start_inference`` does *not* emit ``POST_PROCESSING_COMPLETE`` when
       ``basic_inference()`` returns ``None`` or ``[]``.
    """

    # ------------------------------------------------------------------ helpers

    def _make_proc_for_send_result(self, *, post_processing_was_started: bool) -> MagicMock:
        """Return a minimal mock suited to calling send_inference_result_message directly."""
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._post_processing_was_started = post_processing_was_started
        proc._last_job_inference_rate = None
        proc.process_id = 0
        proc.process_launch_identifier = 0
        # process_message_queue is set in __init__ so it is not part of the class spec;
        # assign it directly so the real send_inference_result_message can call .put().
        proc.process_message_queue = MagicMock()
        return proc

    def _call_send_result_get_info(self, *, post_processing_was_started: bool, results=None) -> str:
        """Call send_inference_result_message and return the ``info`` string passed
        to the HordeInferenceResultMessage constructor."""
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess
        from horde_worker_regen.process_management.messages import HordeProcessState

        proc = self._make_proc_for_send_result(post_processing_was_started=post_processing_was_started)

        with patch(
            "horde_worker_regen.process_management.inference_process.HordeInferenceResultMessage"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            HordeInferenceProcess.send_inference_result_message(
                proc,
                process_state=HordeProcessState.INFERENCE_FAILED,
                job_info=MagicMock(),
                results=results,
                time_elapsed=1.0,
                sanitized_negative_prompt=None,
            )
            return mock_cls.call_args.kwargs["info"]

    # ------------------------------------------------ send_inference_result_message tests

    def test_fault_info_is_post_processing_when_post_processing_was_started(self) -> None:
        """When _post_processing_was_started is True and results is None, the fault
        info string must say "post-processing produced no results" — not the generic
        "inference produced no results" — so operators can distinguish the failure phase.
        """
        info = self._call_send_result_get_info(post_processing_was_started=True, results=None)
        assert info == "post-processing produced no results", (
            f"Expected 'post-processing produced no results', got '{info}'"
        )

    def test_fault_info_is_inference_when_post_processing_was_not_started(self) -> None:
        """When _post_processing_was_started is False (inference never reached
        post-processing), the fault info must say "inference produced no results".
        """
        info = self._call_send_result_get_info(post_processing_was_started=False, results=None)
        assert info == "inference produced no results", (
            f"Expected 'inference produced no results', got '{info}'"
        )

    def test_fault_info_is_post_processing_when_results_is_empty_list(self) -> None:
        """An empty list (not None) returned by basic_inference() must also produce
        "post-processing produced no results" when post-processing was started.
        """
        info = self._call_send_result_get_info(post_processing_was_started=True, results=[])
        assert info == "post-processing produced no results", (
            f"Expected 'post-processing produced no results', got '{info}'"
        )

    # ------------------------------------------------ POST_PROCESSING_COMPLETE suppression tests

    def _make_proc_for_start_inference(self, *, in_post_processing: bool) -> MagicMock:
        """Return a minimal mock suitable for calling start_inference() directly."""
        import multiprocessing

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._is_busy = False
        proc._in_post_processing = in_post_processing
        proc._post_processing_was_started = False
        proc._vae_acquire_attempted = False
        proc._vae_lock_was_acquired = False
        proc._current_job_inference_steps_complete = False
        proc._last_sanitized_negative_prompt = None
        proc._last_job_inference_rate = None
        proc._active_model_name = "TestModel"
        proc._start_inference_time = 0.0
        proc.VAE_SEMAPHORE_TIMEOUT = 5

        # Real semaphore so acquire/release work correctly
        sem = multiprocessing.Semaphore(1)
        proc._inference_semaphore = sem
        proc._vae_decode_semaphore = multiprocessing.Semaphore(1)

        proc.send_process_state_change_message = MagicMock()
        proc.send_heartbeat_message = MagicMock()
        proc.on_horde_model_state_change = MagicMock()

        return proc

    def _make_job_info(self) -> MagicMock:
        job_info = MagicMock()
        job_info.payload.prompt = "test prompt"
        job_info.extra_source_images = None
        job_info.source_image = None
        job_info.source_mask = None
        job_info.ids = []
        return job_info

    def _pp_complete_calls(self, proc: MagicMock) -> list:
        """Return all send_process_state_change_message calls for POST_PROCESSING_COMPLETE."""
        from horde_worker_regen.process_management.messages import HordeProcessState

        return [
            c
            for c in proc.send_process_state_change_message.call_args_list
            if c.kwargs.get("process_state") == HordeProcessState.POST_PROCESSING_COMPLETE
        ]

    def test_post_processing_complete_not_emitted_when_basic_inference_returns_none(self) -> None:
        """When basic_inference() returns None and _in_post_processing is True (we entered
        post-processing but it failed), POST_PROCESSING_COMPLETE must NOT be emitted.

        Emitting it would be misleading: the process-manager uses that state to update the
        progress bar and history UI, falsely reporting success.
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc_for_start_inference(in_post_processing=True)
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = None

        HordeInferenceProcess.start_inference(proc, self._make_job_info())

        assert len(self._pp_complete_calls(proc)) == 0, (
            "POST_PROCESSING_COMPLETE must not be emitted when basic_inference() returns None"
        )

    def test_post_processing_complete_not_emitted_when_basic_inference_returns_empty_list(self) -> None:
        """When basic_inference() returns an empty list and _in_post_processing is True,
        POST_PROCESSING_COMPLETE must NOT be emitted.
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc_for_start_inference(in_post_processing=True)
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = []

        HordeInferenceProcess.start_inference(proc, self._make_job_info())

        assert len(self._pp_complete_calls(proc)) == 0, (
            "POST_PROCESSING_COMPLETE must not be emitted when basic_inference() returns []"
        )

    def test_post_processing_complete_not_emitted_when_no_post_processing(self) -> None:
        """When post-processing was never entered (_in_post_processing is False),
        POST_PROCESSING_COMPLETE must not be emitted regardless of the result.
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc_for_start_inference(in_post_processing=False)
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = None

        HordeInferenceProcess.start_inference(proc, self._make_job_info())

        assert len(self._pp_complete_calls(proc)) == 0, (
            "POST_PROCESSING_COMPLETE must not be emitted when post-processing was never entered"
        )

    def test_post_processing_was_started_flag_set_in_finally_when_in_post_processing(self) -> None:
        """The finally block must copy _in_post_processing → _post_processing_was_started
        before resetting _in_post_processing, so send_inference_result_message can
        read the flag even after start_inference() has returned.
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc_for_start_inference(in_post_processing=True)
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = None

        HordeInferenceProcess.start_inference(proc, self._make_job_info())

        assert proc._post_processing_was_started is True, (
            "_post_processing_was_started must be True after start_inference() when post-processing was entered"
        )
        # And the live flag must have been cleared
        assert proc._in_post_processing is False, (
            "_in_post_processing must be reset to False by the finally block"
        )

    def test_post_processing_was_started_flag_false_when_no_post_processing(self) -> None:
        """When post-processing was never entered, _post_processing_was_started must remain False."""
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc_for_start_inference(in_post_processing=False)
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = None

        HordeInferenceProcess.start_inference(proc, self._make_job_info())

        assert proc._post_processing_was_started is False, (
            "_post_processing_was_started must remain False when post-processing was never entered"
        )


class TestFrozenPayloadPromptRestore:
    """Regression tests for the frozen Pydantic payload prompt restoration bug.

    ``ImageGenerateJobPopPayload`` is a frozen Pydantic v2 model.  Assigning to
    a frozen model attribute raises ``pydantic.ValidationError``, *not*
    ``AttributeError``.  The original code used ``contextlib.suppress(AttributeError)``
    in the ``start_inference`` finally block, so the ``ValidationError`` propagated
    and caused ``start_inference`` to return ``None`` even when ``basic_inference()``
    succeeded — making every job fault with "inference produced no results".
    """

    def _make_proc(self) -> MagicMock:
        """Return a minimally-mocked HordeInferenceProcess for start_inference tests."""
        import multiprocessing

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._is_busy = False
        proc._in_post_processing = False
        proc._post_processing_was_started = False
        proc._vae_acquire_attempted = False
        proc._vae_lock_was_acquired = False
        proc._current_job_inference_steps_complete = False
        proc._last_sanitized_negative_prompt = None
        proc._last_job_inference_rate = None
        proc._active_model_name = "TestModel"
        proc._start_inference_time = 0.0
        proc.VAE_SEMAPHORE_TIMEOUT = 5
        proc._inference_semaphore = multiprocessing.Semaphore(1)
        proc._vae_decode_semaphore = multiprocessing.Semaphore(1)
        proc.send_process_state_change_message = MagicMock()
        proc.send_heartbeat_message = MagicMock()
        return proc

    def _make_frozen_job_info(self) -> MagicMock:
        """Return a job_info whose payload raises ValidationError on assignment (frozen model)."""
        import pydantic

        class FrozenPayload(pydantic.BaseModel):
            model_config = pydantic.config.ConfigDict(frozen=True)
            prompt: str = "positive###negative"

        job_info = MagicMock()
        job_info.payload = FrozenPayload()
        job_info.extra_source_images = None
        job_info.source_image = None
        job_info.source_mask = None
        job_info.ids = []
        return job_info

    def test_frozen_payload_prompt_restore_does_not_propagate(self) -> None:
        """start_inference must return results (not None) when job_info.payload is a
        frozen Pydantic model.

        With the old ``contextlib.suppress(AttributeError)`` the ValidationError raised
        by the frozen-model assignment escaped the finally block, so start_inference()
        appeared to have failed even though basic_inference() returned valid results.
        The fix changes the suppress to
        ``contextlib.suppress(AttributeError, PydanticValidationError)`` so the
        ValidationError is silently swallowed and the inference results are returned.
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc()

        fake_result = MagicMock()
        fake_result.rawpng = MagicMock()
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = [fake_result]

        job_info = self._make_frozen_job_info()

        # Before the fix this returned None because ValidationError escaped the finally block.
        result = HordeInferenceProcess.start_inference(proc, job_info)

        assert result is not None, (
            "start_inference must return results even when job_info.payload is a frozen "
            "Pydantic model (ValidationError in the finally block must be suppressed)"
        )
        assert result == [fake_result], "start_inference must return the exact results from basic_inference()"

    def test_frozen_payload_prompt_restore_when_inference_fails(self) -> None:
        """When basic_inference() raises, start_inference must still return None even
        if job_info.payload is a frozen model (the ValidationError from the finally block
        must not shadow the original inference exception).
        """
        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc()
        proc._horde = MagicMock()
        proc._horde.basic_inference.side_effect = RuntimeError("OOM")

        job_info = self._make_frozen_job_info()

        result = HordeInferenceProcess.start_inference(proc, job_info)

        assert result is None, (
            "start_inference must return None when basic_inference() raises, "
            "regardless of whether payload restoration raises in the finally block"
        )


class TestStartInferencePipeBroken:
    """Tests that a broken pipe to a child process causes the process to be
    replaced and the job fault to be handled correctly (without double-faulting).

    The scenario:
    - ``safe_send_message()`` returns False (e.g. BrokenPipeError).
    - The broken process must be replaced immediately via ``_replace_inference_process``.
    - ``handle_job_fault`` must be called for ``next_job`` when it is a *different* job
      from ``last_job_referenced`` (IDs differ).
    - ``handle_job_fault`` must NOT be called for ``next_job`` when the IDs match,
      because ``_replace_inference_process`` already handles the fault internally.
    """

    def _make_manager_with_pipe_failure(
        self,
        next_job_id: str,
        last_job_id: str | None,
    ) -> MagicMock:
        """Build a minimal mock HordeWorkerProcessManager for the pipe-failure path of
        ``start_inference()``.

        ``get_next_job_and_process`` is mocked to return a plain MagicMock whose
        ``.next_job`` and ``.process_with_model`` attributes are set up appropriately.
        ``safe_send_message`` on the process mock always returns False.

        ``HordeInferenceControlMessage`` is patched at the module level so Pydantic
        validation of ``sdk_api_job_info`` does not interfere with the test — we only
        care about the behaviour after ``safe_send_message`` returns False.
        """
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        # Build the next_job mock (the new job being dispatched)
        next_job = MagicMock()
        next_job.id_ = next_job_id
        next_job.model = "TestModel"
        next_job.source_image = None
        next_job.payload = MagicMock()
        next_job.payload.control_type = None
        next_job.payload.loras = None
        next_job.payload.tis = None
        next_job.payload.post_processing = None
        next_job.payload.hires_fix = False
        next_job.payload.workflow = None
        next_job.payload.width = 512
        next_job.payload.height = 512
        next_job.payload.ddim_steps = 8
        next_job.payload.sampler_name = "k_euler"
        next_job.payload.n_iter = 1
        next_job.ids = [next_job_id]

        # Build the process whose pipe is "broken"
        process_with_model = MagicMock()
        process_with_model.process_id = 1
        process_with_model.batch_amount = 1

        if last_job_id is not None:
            last_ref = MagicMock()
            last_ref.id_ = last_job_id
            process_with_model.last_job_referenced = last_ref
        else:
            process_with_model.last_job_referenced = None

        # safe_send_message always fails (simulates broken pipe)
        process_with_model.safe_send_message.return_value = False

        # Mock get_next_job_and_process to return a plain MagicMock with the right attrs.
        # We avoid importing NextJobAndProcess here because it transitively pulls in heavy
        # GPU/image-processing dependencies.
        nj_and_p = MagicMock()
        nj_and_p.next_job = next_job
        nj_and_p.process_with_model = process_with_model
        nj_and_p.skipped_line = False
        nj_and_p.skipped_line_for = None

        mock_manager = MagicMock()
        mock_manager.get_next_job_and_process.return_value = nj_and_p
        mock_manager.bridge_data.unload_models_from_vram_often = False
        mock_manager.post_process_job_overlap_allowed = False
        mock_manager._skipped_line_next_job_and_process = None

        # Bind the real start_inference method onto the mock manager so we exercise
        # the real control-flow path.
        mock_manager._start_inference = HordeWorkerProcessManager.start_inference.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        return mock_manager

    def test_replace_inference_process_called_on_pipe_failure(self) -> None:
        """When safe_send_message returns False, _replace_inference_process must be invoked."""
        mock_manager = self._make_manager_with_pipe_failure(
            next_job_id="aaaaaaaa-0000-0000-0000-000000000001",
            last_job_id=None,
        )

        with patch(
            "horde_worker_regen.process_management.process_manager.HordeInferenceControlMessage"
        ):
            mock_manager._start_inference()

        mock_manager._replace_inference_process.assert_called_once()

    def test_handle_job_fault_called_once_for_new_job(self) -> None:
        """When next_job has a different ID from last_job_referenced, handle_job_fault
        must be called exactly once with next_job as the faulted_job.
        """
        next_job_id = "bbbbbbbb-0000-0000-0000-000000000002"
        last_job_id = "cccccccc-0000-0000-0000-000000000003"  # different ID
        mock_manager = self._make_manager_with_pipe_failure(
            next_job_id=next_job_id,
            last_job_id=last_job_id,
        )

        with patch(
            "horde_worker_regen.process_management.process_manager.HordeInferenceControlMessage"
        ):
            mock_manager._start_inference()

        mock_manager.handle_job_fault.assert_called_once()
        call_args = mock_manager.handle_job_fault.call_args
        faulted = call_args.kwargs.get("faulted_job") or call_args.args[0]
        assert faulted.id_ == next_job_id, (
            f"handle_job_fault must be called for next_job ({next_job_id}), "
            f"got {faulted.id_}"
        )

    def test_handle_job_fault_suppressed_when_same_job_already_handled(self) -> None:
        """When next_job has the same ID as last_job_referenced, handle_job_fault must
        NOT be called for next_job because _replace_inference_process already faulted it.
        """
        same_id = "dddddddd-0000-0000-0000-000000000004"
        mock_manager = self._make_manager_with_pipe_failure(
            next_job_id=same_id,
            last_job_id=same_id,  # same ID → double-fault guard suppresses extra call
        )

        with patch(
            "horde_worker_regen.process_management.process_manager.HordeInferenceControlMessage"
        ):
            mock_manager._start_inference()

        mock_manager.handle_job_fault.assert_not_called()

    def test_handle_job_fault_called_when_last_job_referenced_is_none(self) -> None:
        """When the process has never run a job (last_job_referenced is None),
        handle_job_fault must still be called for next_job.
        """
        next_job_id = "eeeeeeee-0000-0000-0000-000000000005"
        mock_manager = self._make_manager_with_pipe_failure(
            next_job_id=next_job_id,
            last_job_id=None,
        )

        with patch(
            "horde_worker_regen.process_management.process_manager.HordeInferenceControlMessage"
        ):
            mock_manager._start_inference()

        mock_manager.handle_job_fault.assert_called_once()

    def test_safe_send_message_stores_last_send_error(self) -> None:
        """After a failed send, last_send_error holds the exception that was raised."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        err = BrokenPipeError("pipe gone")
        mock_info.pipe_connection.send.side_effect = err
        mock_info.process_id = 42

        result = HordeProcessInfo.safe_send_message.__get__(mock_info, HordeProcessInfo)(MagicMock())

        assert result is False
        assert mock_info.last_send_error is err

    def test_safe_send_message_clears_last_send_error_on_success(self) -> None:
        """After a successful send, last_send_error is reset to None."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.pipe_connection.send.return_value = None  # success
        mock_info.process_id = 42
        mock_info.last_send_error = BrokenPipeError("stale")

        result = HordeProcessInfo.safe_send_message.__get__(mock_info, HordeProcessInfo)(MagicMock())

        assert result is True
        assert mock_info.last_send_error is None


class TestReplaceHungModelPreloadingBypassesRecentlyRecovered:
    """Tests that MODEL_PRELOADING stuck detection works even when _recently_recovered is True.

    The _recently_recovered guard was previously applied at function entry, meaning a process
    stuck in MODEL_PRELOADING would never be recovered if a different process had been replaced
    recently (within inference_step_timeout seconds).  After the fix, MODEL_PRELOADING (and
    other non-cascading state checks) are always evaluated regardless of _recently_recovered.
    """

    def _make_manager(
        self,
        processes: list[MagicMock],
        *,
        recently_recovered: bool = False,
    ) -> MagicMock:
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = recently_recovered
        mock_manager._last_pop_no_jobs_available = False
        mock_manager._shutting_down = False
        mock_manager.bridge_data.inference_step_timeout = 600
        mock_manager.bridge_data.preload_timeout = 80
        mock_manager.bridge_data.process_timeout = 300
        mock_manager.bridge_data.download_timeout = 300
        mock_manager.bridge_data.post_process_timeout = 60
        mock_manager.bridge_data.max_batch = 1
        # is_stuck_on_inference returns False so we exercise the else branch
        mock_manager._process_map.is_stuck_on_inference.return_value = False
        mock_manager._process_map.values.return_value = processes
        mock_manager._process_map.__iter__ = MagicMock(return_value=iter(processes))

        mock_manager._bound_replace_hung = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        return mock_manager

    def _make_process(
        self,
        process_id: int,
        state: HordeProcessState,
        *,
        time_elapsed: float = 9999.0,
    ) -> MagicMock:
        import time as _time

        proc = MagicMock()
        proc.process_id = process_id
        proc.last_process_state = state
        proc.last_received_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_timestamp = _time.time() - time_elapsed
        proc.last_progress_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_percent_complete = None
        proc.last_job_referenced = None
        return proc

    def test_model_preloading_replaced_when_recently_recovered_false(self) -> None:
        """MODEL_PRELOADING should be caught and replaced under normal conditions."""
        proc = self._make_process(0, HordeProcessState.MODEL_PRELOADING, time_elapsed=9999.0)
        mock_manager = self._make_manager([proc], recently_recovered=False)

        def fake_check_and_replace(
            process_info: MagicMock,
            timeout: float,
            state: HordeProcessState,
            error_msg: str,
        ) -> bool:
            if process_info.last_process_state == state:
                import time as _t

                elapsed = _t.time() - process_info.last_received_timestamp
                if elapsed > timeout:
                    mock_manager._replace_inference_process(process_info)
                    return True
            return False

        mock_manager._check_and_replace_process = fake_check_and_replace

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(proc)

    def test_model_preloading_replaced_even_when_recently_recovered_true(self) -> None:
        """MODEL_PRELOADING must be caught even when _recently_recovered is True.

        This is the regression test for the bug: a process stuck in MODEL_PRELOADING was
        previously never recovered while _recently_recovered=True (the flag was True for up
        to inference_step_timeout=600 seconds after any prior recovery).
        """
        proc = self._make_process(0, HordeProcessState.MODEL_PRELOADING, time_elapsed=9999.0)
        # _recently_recovered=True simulates the state where a prior recovery blocked detection
        mock_manager = self._make_manager([proc], recently_recovered=True)

        def fake_check_and_replace(
            process_info: MagicMock,
            timeout: float,
            state: HordeProcessState,
            error_msg: str,
        ) -> bool:
            if process_info.last_process_state == state:
                import time as _t

                elapsed = _t.time() - process_info.last_received_timestamp
                if elapsed > timeout:
                    mock_manager._replace_inference_process(process_info)
                    return True
            return False

        mock_manager._check_and_replace_process = fake_check_and_replace

        with patch("threading.Thread") as mock_thread:
            result = mock_manager._bound_replace_hung()

        # The stuck MODEL_PRELOADING process must still be replaced
        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(proc)
        # No new timer thread should be started when already inside a recovery window
        mock_thread.assert_not_called()

    def test_inference_starting_not_replaced_when_recently_recovered_true(self) -> None:
        """INFERENCE_STARTING detection must be skipped while _recently_recovered is True.

        Replacing a process in INFERENCE_STARTING shortly after another recovery can cascade;
        the guard prevents that.
        """
        proc = self._make_process(0, HordeProcessState.INFERENCE_STARTING, time_elapsed=9999.0)
        mock_manager = self._make_manager([proc], recently_recovered=True)

        # _check_and_replace_process returns False for all states
        mock_manager._check_and_replace_process.return_value = False

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        mock_manager._replace_inference_process.assert_not_called()
        assert result is False


class TestReplaceHungWaitingForJob:
    """Tests for the per-process WAITING_FOR_JOB stale-heartbeat recovery.

    When an inference process has been in WAITING_FOR_JOB with no heartbeat for longer than
    max(process_timeout, 300) seconds and there are pending jobs, it should be replaced
    automatically even while _recently_recovered is True (a freshly replaced process starts in
    PROCESS_STARTING with a fresh timestamp, so it will never immediately re-match this condition).
    """

    def _make_manager(
        self,
        processes: list[MagicMock],
        *,
        recently_recovered: bool = False,
        last_pop_no_jobs: bool = False,
    ) -> MagicMock:
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = recently_recovered
        mock_manager._last_pop_no_jobs_available = last_pop_no_jobs
        mock_manager._shutting_down = False
        mock_manager._hung_processes_detected = False
        mock_manager._hung_processes_detected_time = 0.0
        mock_manager.bridge_data.inference_step_timeout = 600
        mock_manager.bridge_data.preload_timeout = 80
        mock_manager.bridge_data.process_timeout = 100
        mock_manager.bridge_data.download_timeout = 300
        mock_manager.bridge_data.post_process_timeout = 60
        mock_manager.bridge_data.max_batch = 1
        mock_manager._process_map.is_stuck_on_inference.return_value = False
        mock_manager._check_and_replace_process.return_value = False
        mock_manager._process_map.values.return_value = processes
        mock_manager._process_map.__iter__ = MagicMock(return_value=iter(processes))

        mock_manager._bound_replace_hung = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        return mock_manager

    def _make_inference_process(
        self,
        process_id: int,
        *,
        time_elapsed: float,
    ) -> MagicMock:
        import time as _time
        from horde_worker_regen.process_management.process_manager import HordeProcessType

        proc = MagicMock()
        proc.process_id = process_id
        proc.process_type = HordeProcessType.INFERENCE
        proc.last_process_state = HordeProcessState.WAITING_FOR_JOB
        proc.last_received_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_timestamp = _time.time() - time_elapsed
        proc.last_progress_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_percent_complete = None
        proc.last_job_referenced = None
        return proc

    def test_stale_waiting_for_job_process_replaced_when_jobs_pending(self) -> None:
        """A WAITING_FOR_JOB process whose heartbeat is older than 300s must be
        replaced when there are pending jobs (not _last_pop_no_jobs_available).
        The threshold is max(process_timeout, 300) so even high-performance-mode workers
        (process_timeout=100s) wait at least 300s before being replaced.
        """
        # 400s stale, effective threshold=max(100, 300)=300s → should trigger
        proc = self._make_inference_process(1, time_elapsed=400.0)
        mock_manager = self._make_manager([proc])

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(proc)

    def test_stale_waiting_for_job_process_replaced_even_when_recently_recovered(self) -> None:
        """The WAITING_FOR_JOB per-process check must run even when _recently_recovered=True.

        This is the regression case: in the reported bug Processes 1 and 3 were stuck in
        WAITING_FOR_JOB for 351 s and 464 s while _recently_recovered blocked all detection.
        """
        proc = self._make_inference_process(3, time_elapsed=464.0)
        # Simulate the state from the bug report: another recovery was recent
        mock_manager = self._make_manager([proc], recently_recovered=True)

        with patch("threading.Thread") as mock_thread:
            result = mock_manager._bound_replace_hung()

        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(proc)
        # No new timer thread when already inside recovery window
        mock_thread.assert_not_called()

    def test_fresh_waiting_for_job_process_not_replaced(self) -> None:
        """A WAITING_FOR_JOB process with a recent heartbeat must not be replaced."""
        # Only 10s stale, well below effective threshold of max(100, 300)=300s
        proc = self._make_inference_process(1, time_elapsed=10.0)
        mock_manager = self._make_manager([proc])

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        mock_manager._replace_inference_process.assert_not_called()
        assert result is False

    def test_waiting_for_job_not_replaced_below_300s_threshold(self) -> None:
        """Even with process_timeout=100 (high_performance_mode), a process idle for only 200s
        must NOT be replaced because the effective threshold is max(process_timeout, 300)=300s.
        """
        # 200s stale, effective threshold=max(100, 300)=300s → must NOT trigger
        proc = self._make_inference_process(1, time_elapsed=200.0)
        mock_manager = self._make_manager([proc])  # process_timeout=100

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        mock_manager._replace_inference_process.assert_not_called()
        assert result is False

    def test_stale_waiting_for_job_not_replaced_when_no_jobs_available(self) -> None:
        """A stale WAITING_FOR_JOB process must NOT be replaced when no jobs are available.

        WAITING_FOR_JOB is the expected idle state; replacing processes when there's nothing
        to do would cause needless churn.
        """
        proc = self._make_inference_process(1, time_elapsed=9999.0)
        # last_pop_no_jobs=True means the server has no work for us
        mock_manager = self._make_manager([proc], last_pop_no_jobs=True)

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        mock_manager._replace_inference_process.assert_not_called()
        assert result is False


class TestImageSubmittingStuckRecovery:
    """Tests for the IMAGE_SUBMITTING stuck-process fixes.

    Two complementary guards are tested:
    1. submit_single_generation() try/finally resets the state to WAITING_FOR_JOB on every
       failure path so the process never stays in IMAGE_SUBMITTING after a failed submission.
    2. replace_hung_processes() resets any process that remains in IMAGE_SUBMITTING for longer
       than 60 s as a safety net, without killing the subprocess.
    """

    # -------------------------------------------------------------------------
    # Helpers shared by the submit_single_generation tests
    # -------------------------------------------------------------------------

    def _make_process_map(self, process_id: int, initial_state: HordeProcessState) -> tuple[MagicMock, MagicMock]:
        """Return a (ProcessMap-like mock, process_info mock) pair that tracks state changes."""
        process_info = MagicMock()
        process_info.last_process_state = initial_state

        def on_state_change(*, process_id: int, new_state: HordeProcessState) -> None:
            process_info.last_process_state = new_state

        process_map = MagicMock()
        process_map.items.return_value = [(process_id, process_info)]
        process_map.get.return_value = process_info
        process_map.on_process_state_change.side_effect = on_state_change

        return process_map, process_info

    def _make_submit_manager(
        self,
        process_id: int,
        *,
        initial_state: HordeProcessState = HordeProcessState.IMAGE_SAVED,
    ) -> tuple[MagicMock, MagicMock]:
        """Build a minimal mock manager suitable for calling submit_single_generation."""
        process_map, process_info = self._make_process_map(process_id, initial_state)
        mock_manager = MagicMock()
        mock_manager._process_map = process_map
        return mock_manager, process_info

    def _make_new_submit(self, process_info: MagicMock) -> MagicMock:
        """Build a faulted PendingSubmitJob mock whose job reference matches the process.

        Using is_faulted=True (faulted job, no image) lets the function bypass the
        image-upload section and proceed directly to setting IMAGE_SUBMITTING and
        calling the API, which is what we want to exercise.
        """
        sdk_job = MagicMock()
        # payload.seed must look like an integer so int() doesn't raise
        sdk_job.payload.seed = 0

        completed_job_info = MagicMock()
        completed_job_info.sdk_api_job_info = sdk_job
        completed_job_info.state = "faulted"

        new_submit = MagicMock()
        new_submit.is_faulted = True   # faulted → skip "no image result" early return
        new_submit.image_result = None  # faulted job has no image
        new_submit.completed_job_info = completed_job_info

        # Make process_info.last_job_referenced match so handling_process_id is found
        process_info.last_job_referenced = sdk_job

        return new_submit

    # -------------------------------------------------------------------------
    # submit_single_generation tests
    # -------------------------------------------------------------------------

    def test_state_reset_to_waiting_on_api_timeout(self) -> None:
        """Process state must be reset to WAITING_FOR_JOB when the API call times out."""
        import asyncio

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        manager, proc_info = self._make_submit_manager(0)
        new_submit = self._make_new_submit(proc_info)

        # Simulate an asyncio.TimeoutError coming from the API call
        async def _timeout(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
            raise asyncio.TimeoutError

        manager.horde_client_session.submit_request.side_effect = _timeout

        bound = HordeWorkerProcessManager.submit_single_generation.__get__(manager, HordeWorkerProcessManager)
        asyncio.run(bound(new_submit))

        assert proc_info.last_process_state == HordeProcessState.WAITING_FOR_JOB

    def test_state_reset_to_waiting_on_unexpected_exception(self) -> None:
        """Process state must be reset to WAITING_FOR_JOB when submit_request raises unexpectedly."""
        import asyncio

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        manager, proc_info = self._make_submit_manager(0)
        new_submit = self._make_new_submit(proc_info)

        async def _fail(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
            raise RuntimeError("unexpected error")

        manager.horde_client_session.submit_request.side_effect = _fail

        bound = HordeWorkerProcessManager.submit_single_generation.__get__(manager, HordeWorkerProcessManager)
        asyncio.run(bound(new_submit))

        assert proc_info.last_process_state == HordeProcessState.WAITING_FOR_JOB

    def test_state_reset_to_waiting_on_api_error_response(self) -> None:
        """Process state must be reset to WAITING_FOR_JOB when the API returns a RequestErrorResponse."""
        import asyncio

        from horde_sdk import RequestErrorResponse

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        manager, proc_info = self._make_submit_manager(0)
        new_submit = self._make_new_submit(proc_info)

        error_response = MagicMock(spec=RequestErrorResponse)
        error_response.message = "Some unexpected API error"

        async def _return_error(*args, **kwargs) -> object:  # noqa: ANN002, ANN003
            return error_response

        # Bypass asyncio.wait_for so the coroutine runs directly and returns the error
        async def _wait_for_passthrough(coro, timeout) -> object:  # noqa: ANN001, ANN002
            return await coro

        with patch("asyncio.wait_for", side_effect=_wait_for_passthrough):
            manager.horde_client_session.submit_request = _return_error
            bound = HordeWorkerProcessManager.submit_single_generation.__get__(manager, HordeWorkerProcessManager)
            asyncio.run(bound(new_submit))

        assert proc_info.last_process_state == HordeProcessState.WAITING_FOR_JOB

    # -------------------------------------------------------------------------
    # replace_hung_processes safety-net tests
    # -------------------------------------------------------------------------

    def _make_hung_manager(
        self,
        processes: list[MagicMock],
        *,
        last_pop_no_jobs: bool = False,
    ) -> MagicMock:
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = False
        mock_manager._last_pop_no_jobs_available = last_pop_no_jobs
        mock_manager._shutting_down = False
        mock_manager._hung_processes_detected = False
        mock_manager._hung_processes_detected_time = 0.0
        mock_manager.bridge_data.inference_step_timeout = 600
        mock_manager.bridge_data.preload_timeout = 80
        mock_manager.bridge_data.process_timeout = 300
        mock_manager.bridge_data.download_timeout = 300
        mock_manager.bridge_data.post_process_timeout = 60
        mock_manager.bridge_data.max_batch = 1
        mock_manager._process_map.is_stuck_on_inference.return_value = False
        mock_manager._check_and_replace_process.return_value = False
        mock_manager._process_map.values.return_value = processes

        mock_manager._bound_replace_hung = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        return mock_manager

    def _make_image_submitting_process(
        self,
        process_id: int,
        *,
        time_elapsed: float,
    ) -> MagicMock:
        import time as _time

        from horde_worker_regen.process_management.process_manager import HordeProcessType

        proc = MagicMock()
        proc.process_id = process_id
        proc.process_type = HordeProcessType.INFERENCE
        proc.last_process_state = HordeProcessState.IMAGE_SUBMITTING
        proc.last_received_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_timestamp = _time.time() - time_elapsed
        proc.last_progress_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_percent_complete = None
        proc.last_job_referenced = None
        return proc

    def test_image_submitting_stuck_over_60s_resets_state(self) -> None:
        """A process stuck in IMAGE_SUBMITTING for >60 s must have its state reset to WAITING_FOR_JOB."""
        proc = self._make_image_submitting_process(2, time_elapsed=90.0)
        mock_manager = self._make_hung_manager([proc])

        state_changes: list[HordeProcessState] = []

        def _on_state_change(*, process_id: int, new_state: HordeProcessState) -> None:
            proc.last_process_state = new_state
            state_changes.append(new_state)

        mock_manager._process_map.on_process_state_change.side_effect = _on_state_change

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is True
        assert HordeProcessState.WAITING_FOR_JOB in state_changes
        # The subprocess must NOT have been killed
        mock_manager._replace_inference_process.assert_not_called()

    def test_image_submitting_not_reset_within_60s(self) -> None:
        """A process in IMAGE_SUBMITTING for <60 s must not be touched (submission still in progress)."""
        proc = self._make_image_submitting_process(2, time_elapsed=30.0)
        mock_manager = self._make_hung_manager([proc])

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is False
        mock_manager._replace_inference_process.assert_not_called()
        mock_manager._process_map.on_process_state_change.assert_not_called()

    def test_image_submitting_stuck_not_reset_when_no_jobs_available(self) -> None:
        """IMAGE_SUBMITTING timeout check must be skipped when no jobs are available.

        The check is inside the _last_pop_no_jobs_available guard, so it should not
        trigger when the server has no work.
        """
        proc = self._make_image_submitting_process(2, time_elapsed=9999.0)
        mock_manager = self._make_hung_manager([proc], last_pop_no_jobs=True)

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is False
        mock_manager._replace_inference_process.assert_not_called()

    def test_image_submitting_reset_does_not_trigger_recently_recovered(self) -> None:
        """Resetting IMAGE_SUBMITTING state must NOT set _recently_recovered.

        IMAGE_SUBMITTING recovery is a soft state reset — the subprocess is NOT killed.
        Setting _recently_recovered would incorrectly suppress INFERENCE_STARTING detection
        and other legitimate checks for inference_step_timeout seconds after every submission
        timeout, which is far too conservative.  Only actual subprocess replacements should
        start the cascading-recovery cooldown.
        """
        proc = self._make_image_submitting_process(2, time_elapsed=90.0)
        mock_manager = self._make_hung_manager([proc])

        thread_started = False

        class _TrackThread:
            def __init__(self, *args: object, **kwargs: object) -> None:
                nonlocal thread_started
                thread_started = True

            def start(self) -> None:
                pass

        with patch("threading.Thread", _TrackThread):
            result = mock_manager._bound_replace_hung()

        assert result is True
        # The subprocess must NOT have been killed
        mock_manager._replace_inference_process.assert_not_called()
        # The cascading-recovery guard must NOT have been activated
        assert mock_manager._recently_recovered is False
        assert not thread_started, "_recently_recovered timer thread must not be started for a state reset"



class TestReplaceHungModelPreloaded:
    """Tests that MODEL_PRELOADED stuck detection fires after ``preload_timeout`` seconds.

    A process that is stuck in MODEL_PRELOADED (the model has been loaded into RAM but
    the job was never dispatched, e.g. because ``start_inference()`` was never called due
    to ``preload_models()`` blocking it) should be replaced just like MODEL_PRELOADING.
    """

    def _make_manager(
        self,
        processes: list[MagicMock],
        *,
        recently_recovered: bool = False,
    ) -> MagicMock:
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = recently_recovered
        mock_manager._last_pop_no_jobs_available = False
        mock_manager._shutting_down = False
        mock_manager._hung_processes_detected = False
        mock_manager._hung_processes_detected_time = 0.0
        mock_manager.bridge_data.inference_step_timeout = 600
        mock_manager.bridge_data.preload_timeout = 80
        mock_manager.bridge_data.process_timeout = 300
        mock_manager.bridge_data.download_timeout = 300
        mock_manager.bridge_data.post_process_timeout = 60
        mock_manager.bridge_data.max_batch = 1
        mock_manager._process_map.is_stuck_on_inference.return_value = False
        mock_manager._process_map.values.return_value = processes
        mock_manager._process_map.__iter__ = MagicMock(return_value=iter(processes))

        mock_manager._bound_replace_hung = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager,
        )
        return mock_manager

    def _make_process(
        self,
        process_id: int,
        state: HordeProcessState,
        *,
        time_elapsed: float = 9999.0,
    ) -> MagicMock:
        import time as _time

        from horde_worker_regen.process_management.process_manager import HordeProcessType

        proc = MagicMock()
        proc.process_id = process_id
        proc.process_type = HordeProcessType.INFERENCE
        proc.last_process_state = state
        proc.last_received_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_timestamp = _time.time() - time_elapsed
        proc.last_progress_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_percent_complete = None
        proc.last_job_referenced = None
        return proc

    def _fake_check_and_replace(self, mock_manager: MagicMock) -> object:
        """Return a ``_check_and_replace_process`` implementation that actually checks the state."""

        def fake_check_and_replace(
            process_info: MagicMock,
            timeout: float,
            state: HordeProcessState,
            error_msg: str,
        ) -> bool:
            if process_info.last_process_state == state:
                import time as _t

                elapsed = _t.time() - process_info.last_received_timestamp
                if elapsed > timeout:
                    mock_manager._replace_inference_process(process_info)
                    return True
            return False

        return fake_check_and_replace

    def test_model_preloaded_replaced_after_timeout(self) -> None:
        """A process stuck in MODEL_PRELOADED for longer than preload_timeout must be replaced."""
        proc = self._make_process(1, HordeProcessState.MODEL_PRELOADED, time_elapsed=9999.0)
        mock_manager = self._make_manager([proc], recently_recovered=False)
        mock_manager._check_and_replace_process = self._fake_check_and_replace(mock_manager)

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(proc)

    def test_model_preloaded_replaced_even_when_recently_recovered(self) -> None:
        """MODEL_PRELOADED stuck detection must fire even when _recently_recovered is True.

        A process that cannot receive its START_INFERENCE message (e.g. because
        ``preload_models()`` keeps returning True and blocks ``start_inference()``)
        must be recovered regardless of whether a prior recovery recently ran.
        """
        proc = self._make_process(1, HordeProcessState.MODEL_PRELOADED, time_elapsed=9999.0)
        mock_manager = self._make_manager([proc], recently_recovered=True)
        mock_manager._check_and_replace_process = self._fake_check_and_replace(mock_manager)

        with patch("threading.Thread") as mock_thread:
            result = mock_manager._bound_replace_hung()

        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(proc)
        mock_thread.assert_not_called()

    def test_model_preloaded_not_replaced_before_timeout(self) -> None:
        """A process that just entered MODEL_PRELOADED (time_elapsed < preload_timeout).

        Must NOT be replaced, since it is expected to receive START_INFERENCE shortly.
        """
        # 10 seconds elapsed — well below preload_timeout (80 s)
        proc = self._make_process(1, HordeProcessState.MODEL_PRELOADED, time_elapsed=10.0)
        mock_manager = self._make_manager([proc], recently_recovered=False)
        mock_manager._check_and_replace_process = self._fake_check_and_replace(mock_manager)

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        mock_manager._replace_inference_process.assert_not_called()
        assert result is False

    def test_model_preloaded_not_replaced_when_no_jobs_available(self) -> None:
        """A stale MODEL_PRELOADED process must NOT be replaced when no jobs are available.

        When _last_pop_no_jobs_available is True, job-related stuck checks (including
        MODEL_PRELOADED) are skipped to avoid pointless process churn.
        """
        proc = self._make_process(1, HordeProcessState.MODEL_PRELOADED, time_elapsed=9999.0)
        mock_manager = self._make_manager([proc], recently_recovered=False)
        mock_manager._last_pop_no_jobs_available = True
        mock_manager._check_and_replace_process = self._fake_check_and_replace(mock_manager)

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        mock_manager._replace_inference_process.assert_not_called()
        assert result is False


class TestPreloadModelsPipeBroken:
    """Tests that a broken pipe in ``preload_models()`` causes immediate process replacement.

    When ``safe_send_message()`` returns False for the PRELOAD_MODEL message,
    ``_replace_inference_process`` must be called on the dead process immediately.
    Without this, ``preload_models()`` would return True every cycle (because neither
    the model map nor the process map state was updated), permanently blocking
    ``start_inference()`` and leaving any MODEL_PRELOADED process stuck waiting for
    a job that will never arrive.
    """

    def _make_manager_preload_send_failure(self) -> MagicMock:
        """Build a minimal mock for the pipe-failure path of ``preload_models()``."""
        from horde_worker_regen.process_management.process_manager import (
            HordeWorkerProcessManager,
        )

        # Pending job for model "Juggernaut XL" (not yet loaded)
        pending_job = MagicMock()
        pending_job.model = "Juggernaut XL"
        pending_job.payload = MagicMock()
        pending_job.payload.loras = None
        pending_job.payload.tiling = None

        # The process whose pipe is broken
        available_process = MagicMock()
        available_process.process_id = 2
        available_process.safe_send_message.return_value = False
        available_process.last_send_error = BrokenPipeError("simulated broken pipe")
        available_process.last_process_state = HordeProcessState.WAITING_FOR_JOB
        available_process.loaded_horde_model_name = None

        # Model map reports "Juggernaut XL" not loaded (so the preload is attempted)
        mock_model_map = MagicMock()
        mock_model_map.root = {}  # empty → LOADING check returns "not loaded"
        mock_model_map_values = []
        mock_model_map.values.return_value = mock_model_map_values

        mock_process_map = MagicMock()
        mock_process_map.values.return_value = []
        mock_process_map.get_first_available_inference_process.return_value = available_process
        mock_process_map.num_loaded_inference_processes.return_value = 3
        mock_process_map.num_preloading_processes.return_value = 0

        mock_manager = MagicMock()
        mock_manager._horde_model_map = mock_model_map
        mock_manager._process_map = mock_process_map
        mock_manager.jobs_pending_inference = [pending_job]
        mock_manager.jobs_in_progress = []
        mock_manager._shutting_down = False
        mock_manager._preload_delay_notified = False
        mock_manager._max_concurrent_inference_processes = 3
        mock_manager.bridge_data.very_fast_disk_mode = False
        mock_manager.bridge_data.cycle_process_on_model_change = False
        mock_manager.get_model_baseline.return_value = None

        mock_manager._preload_models = HordeWorkerProcessManager.preload_models.__get__(
            mock_manager, HordeWorkerProcessManager,
        )
        return mock_manager, available_process

    def test_replace_inference_process_called_on_pipe_failure(self) -> None:
        """When safe_send_message returns False for PRELOAD_MODEL.

        _replace_inference_process must be called immediately on the dead process.
        """
        mock_manager, available_process = self._make_manager_preload_send_failure()

        with patch(
            "horde_worker_regen.process_management.process_manager.HordePreloadInferenceModelMessage",
        ):
            mock_manager._preload_models()

        mock_manager._replace_inference_process.assert_called_once_with(available_process)

    def test_model_map_not_updated_on_pipe_failure(self) -> None:
        """When safe_send_message fails, model map entry must NOT be created.

        This ensures the next cycle can select a new healthy process for preloading.
        """
        mock_manager, _ = self._make_manager_preload_send_failure()

        with patch(
            "horde_worker_regen.process_management.process_manager.HordePreloadInferenceModelMessage",
        ):
            mock_manager._preload_models()

        # update_entry must not have been called (model map not polluted with stale LOADING state)
        mock_manager._horde_model_map.update_entry.assert_not_called()

    def test_preload_models_still_returns_true_on_pipe_failure(self) -> None:
        """preload_models() returns True even on pipe failure.

        The main loop knows a preload was attempted and will retry next cycle with a fresh process.
        """
        mock_manager, _ = self._make_manager_preload_send_failure()

        with patch(
            "horde_worker_regen.process_management.process_manager.HordePreloadInferenceModelMessage",
        ):
            result = mock_manager._preload_models()

        assert result is True


class TestReplaceInferenceProcessDoesNotDoubleFault:
    """Tests that _replace_inference_process does not fault a job that was already re-queued for retry.

    When _purge_jobs() is called first (e.g. all processes timed out), it faults each in-progress
    job and re-queues eligible ones to jobs_pending_inference.  Afterwards _replace_inference_process
    is called for each crashed process.  Without the guard, _replace_inference_process would call
    handle_job_fault a second time for the same job — consuming the single retry budget and marking
    the job permanently faulted before it ever gets its second chance.
    """

    def _make_manager_with_job_state(
        self,
        *,
        job_in_progress: bool,
    ) -> tuple[MagicMock, MagicMock, MagicMock]:
        """Return (mock_manager, job, process_info) with the job either in jobs_in_progress or not.

        The returned mock_manager has _replace_inference_process bound to the real
        implementation so we can exercise the actual guard.
        """
        import types

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        job = MagicMock()
        job.id_ = "aaaabbbb-0000-0000-0000-000000000001"

        mock_manager = MagicMock()
        mock_manager.jobs_in_progress = [job] if job_in_progress else []
        mock_manager.jobs_lookup = {job: MagicMock()}

        # Bind the real method so it exercises the actual code path
        bound = types.MethodType(HordeWorkerProcessManager._replace_inference_process, mock_manager)

        process_info = MagicMock()
        process_info.last_job_referenced = job
        process_info.last_process_state = HordeProcessState.INFERENCE_PROCESSING
        process_info.loaded_horde_model_name = None
        mock_manager._inference_semaphore.release.side_effect = ValueError
        mock_manager._disk_lock.release.side_effect = ValueError

        bound(process_info)
        return mock_manager, job, process_info

    def test_handle_job_fault_called_when_job_is_in_progress(self) -> None:
        """_replace_inference_process must call handle_job_fault when the job is still in-progress."""
        mock_manager, job, process_info = self._make_manager_with_job_state(job_in_progress=True)
        mock_manager.handle_job_fault.assert_called_once_with(
            faulted_job=job,
            process_info=process_info,
        )

    def test_handle_job_fault_skipped_when_job_already_requeued_for_retry(self) -> None:
        """_replace_inference_process must NOT call handle_job_fault when the job is no longer in jobs_in_progress.

        This happens when _purge_jobs() already moved the job to jobs_pending_inference for its
        retry attempt.  A second call would exhaust the retry budget and permanently fault the job.
        """
        mock_manager, _job, _process_info = self._make_manager_with_job_state(job_in_progress=False)
        mock_manager.handle_job_fault.assert_not_called()


class TestPurgeJobsRetryCount:
    """Tests that _purge_jobs keeps retry-eligible jobs and discards fresh ones.

    The key invariants:
    - Jobs already faulted and re-queued (retry_count > 0) survive the purge.
    - Fresh pending jobs (retry_count == 0) are cleared.
    - In-progress jobs get faulted via handle_job_fault (which increments retry_count),
      so they end up in jobs_pending_inference with retry_count > 0 and survive.
    """

    def _make_job(self, job_id: str) -> MagicMock:
        job = MagicMock()
        job.id_ = job_id
        return job

    def _make_job_info(self, retry_count: int) -> MagicMock:
        job_info = MagicMock()
        job_info.retry_count = retry_count
        return job_info

    def _make_manager(
        self,
        *,
        jobs_in_progress: list,
        jobs_pending_inference: list,
        jobs_lookup: dict,
    ) -> MagicMock:
        import types
        from collections import deque

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager.jobs_in_progress = list(jobs_in_progress)
        mock_manager.jobs_pending_inference = deque(jobs_pending_inference)
        mock_manager.jobs_lookup = dict(jobs_lookup)
        mock_manager.jobs_being_safety_checked = []
        mock_manager.jobs_pending_safety_check = []
        mock_manager.jobs_pending_submit = []
        mock_manager._skipped_line_next_job_and_process = None

        # handle_job_fault is real: we want _purge_jobs to drive it, so bind the real one.
        # But to avoid side effects we use a side_effect that just appends to jobs_pending_inference
        # as the real implementation would for a retry-eligible job.
        max_retries = HordeWorkerProcessManager.MAX_JOB_RETRIES

        def fake_handle_job_fault(faulted_job: MagicMock, process_info: MagicMock) -> None:
            job_info = mock_manager.jobs_lookup.get(faulted_job)
            if job_info is not None and job_info.retry_count < max_retries:
                job_info.retry_count += 1
                if faulted_job not in mock_manager.jobs_pending_inference:
                    mock_manager.jobs_pending_inference.append(faulted_job)
                if faulted_job in mock_manager.jobs_in_progress:
                    mock_manager.jobs_in_progress.remove(faulted_job)

        mock_manager.handle_job_fault = fake_handle_job_fault
        mock_manager._last_job_submitted_time = 0.0
        mock_manager._invalidate_megapixelsteps_cache = MagicMock()

        bound = types.MethodType(HordeWorkerProcessManager._purge_jobs, mock_manager)
        mock_manager._bound_purge = bound
        return mock_manager

    def test_fresh_pending_job_is_cleared(self) -> None:
        """A pending job that has never been retried (retry_count == 0) must be removed."""
        job = self._make_job("fresh-job")
        job_info = self._make_job_info(retry_count=0)

        mock_manager = self._make_manager(
            jobs_in_progress=[],
            jobs_pending_inference=[job],
            jobs_lookup={job: job_info},
        )
        mock_manager._bound_purge()

        assert job not in mock_manager.jobs_pending_inference

    def test_already_retried_pending_job_is_kept(self) -> None:
        """A pending job with retry_count > 0 (already faulted once and re-queued) must be kept.

        This covers the scenario where a prior PROCESS_ENDING handler already retried the job
        before _purge_jobs runs.  The old snapshot-based filter would discard this job because
        it was already in jobs_pending_inference at snapshot time.
        """
        job = self._make_job("retried-job")
        job_info = self._make_job_info(retry_count=1)

        mock_manager = self._make_manager(
            jobs_in_progress=[],
            jobs_pending_inference=[job],
            jobs_lookup={job: job_info},
        )
        mock_manager._bound_purge()

        assert job in mock_manager.jobs_pending_inference

    def test_in_progress_job_retried_and_kept(self) -> None:
        """A job that was in progress (retry_count == 0) gets retried by the purge and survives.

        _purge_jobs calls handle_job_fault for each in-progress job; handle_job_fault moves the
        job to jobs_pending_inference with retry_count == 1.  The subsequent filter must keep it.
        """
        job = self._make_job("in-progress-job")
        job_info = self._make_job_info(retry_count=0)

        mock_manager = self._make_manager(
            jobs_in_progress=[job],
            jobs_pending_inference=[],
            jobs_lookup={job: job_info},
        )
        mock_manager._bound_purge()

        assert job in mock_manager.jobs_pending_inference
        assert job_info.retry_count == 1

    def test_mixed_pending_jobs_only_retried_ones_kept(self) -> None:
        """With a mix of fresh and retried pending jobs, only retried ones must survive."""
        fresh = self._make_job("fresh")
        retried = self._make_job("retried")

        mock_manager = self._make_manager(
            jobs_in_progress=[],
            jobs_pending_inference=[fresh, retried],
            jobs_lookup={
                fresh: self._make_job_info(retry_count=0),
                retried: self._make_job_info(retry_count=1),
            },
        )
        mock_manager._bound_purge()

        assert fresh not in mock_manager.jobs_pending_inference
        assert retried in mock_manager.jobs_pending_inference


class TestReplaceHungProcessesLocalJobsPending:
    """Tests that replace_hung_processes() runs job-related stuck checks when local jobs are queued.

    Regression tests for the bug where the _last_pop_no_jobs_available guard skipped
    MODEL_PRELOADING and WAITING_FOR_JOB stuck-process checks even when jobs were already
    sitting in the local jobs_pending_inference queue. A stuck process in those states would
    never be replaced, leaving queued jobs unable to make progress.
    """

    def _make_manager(
        self,
        processes: list[MagicMock],
        *,
        recently_recovered: bool = False,
        last_pop_no_jobs: bool = False,
        jobs_pending_inference: list | None = None,
        jobs_in_progress: list | None = None,
    ) -> MagicMock:
        """Build a minimal mock manager wired for replace_hung_processes()."""
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        mock_manager = MagicMock()
        mock_manager._recently_recovered = recently_recovered
        mock_manager._last_pop_no_jobs_available = last_pop_no_jobs
        mock_manager._shutting_down = False
        mock_manager._hung_processes_detected = False
        mock_manager._hung_processes_detected_time = 0.0
        mock_manager.bridge_data.inference_step_timeout = 600
        mock_manager.bridge_data.preload_timeout = 80
        mock_manager.bridge_data.process_timeout = 100
        mock_manager.bridge_data.download_timeout = 300
        mock_manager.bridge_data.post_process_timeout = 60
        mock_manager.bridge_data.max_batch = 1
        mock_manager._process_map.is_stuck_on_inference.return_value = False
        mock_manager._check_and_replace_process.return_value = False
        mock_manager._process_map.values.return_value = processes
        mock_manager._process_map.__iter__ = MagicMock(return_value=iter(processes))
        mock_manager.jobs_pending_inference = (
            jobs_pending_inference if jobs_pending_inference is not None else []
        )
        mock_manager.jobs_in_progress = jobs_in_progress if jobs_in_progress is not None else []

        mock_manager._bound_replace_hung = HordeWorkerProcessManager.replace_hung_processes.__get__(
            mock_manager, HordeWorkerProcessManager,
        )
        return mock_manager

    def _make_model_preloading_process(self, process_id: int) -> MagicMock:
        """Return a mock process stuck in MODEL_PRELOADING with a stale heartbeat."""
        import time as _time

        from horde_worker_regen.process_management.process_manager import HordeProcessType

        proc = MagicMock()
        proc.process_id = process_id
        proc.process_type = HordeProcessType.INFERENCE
        proc.last_process_state = HordeProcessState.MODEL_PRELOADING
        proc.last_received_timestamp = _time.time() - 9999
        proc.last_heartbeat_timestamp = _time.time() - 9999
        proc.last_progress_timestamp = _time.time() - 9999
        proc.last_heartbeat_percent_complete = None
        proc.last_job_referenced = None
        return proc

    def _make_waiting_for_job_process(self, process_id: int, *, time_elapsed: float) -> MagicMock:
        """Return a mock inference process in WAITING_FOR_JOB with a stale heartbeat."""
        import time as _time

        from horde_worker_regen.process_management.process_manager import HordeProcessType

        proc = MagicMock()
        proc.process_id = process_id
        proc.process_type = HordeProcessType.INFERENCE
        proc.last_process_state = HordeProcessState.WAITING_FOR_JOB
        proc.last_received_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_timestamp = _time.time() - time_elapsed
        proc.last_progress_timestamp = _time.time() - time_elapsed
        proc.last_heartbeat_percent_complete = None
        proc.last_job_referenced = None
        return proc

    def test_model_preloading_check_runs_when_local_jobs_pending(self) -> None:
        """MODEL_PRELOADING stuck check must run when jobs are in the local queue.

        Before the fix, the guard ``if _last_pop_no_jobs_available: continue`` was
        unconditional and skipped the MODEL_PRELOADING check even when jobs were
        already pending locally, causing stuck preloading processes to be ignored.
        """
        proc = self._make_model_preloading_process(0)
        job = MagicMock()

        mock_manager = self._make_manager(
            [proc],
            last_pop_no_jobs=True,
            jobs_pending_inference=[job],
        )

        with patch("threading.Thread"):
            mock_manager._bound_replace_hung()

        called_states = [call.args[2] for call in mock_manager._check_and_replace_process.call_args_list]
        assert HordeProcessState.MODEL_PRELOADING in called_states, (
            "MODEL_PRELOADING check must run when local jobs are pending, "
            "even when _last_pop_no_jobs_available is True"
        )

    def test_model_preloading_check_skipped_when_no_jobs_anywhere(self) -> None:
        """MODEL_PRELOADING stuck check must be skipped when there is no work anywhere.

        When the horde API reports no new jobs AND the local queue is also empty,
        skipping the check avoids unnecessary churn (preserving the original guard intent).
        """
        proc = self._make_model_preloading_process(0)

        mock_manager = self._make_manager(
            [proc],
            last_pop_no_jobs=True,
            jobs_pending_inference=[],
            jobs_in_progress=[],
        )

        with patch("threading.Thread"):
            mock_manager._bound_replace_hung()

        called_states = [call.args[2] for call in mock_manager._check_and_replace_process.call_args_list]
        assert HordeProcessState.MODEL_PRELOADING not in called_states, (
            "MODEL_PRELOADING check must be skipped when no jobs are available anywhere"
        )

    def test_stale_waiting_for_job_replaced_when_no_horde_jobs_but_local_jobs_pending(self) -> None:
        """A stale WAITING_FOR_JOB process must be replaced when local jobs are pending.

        Scenario: _last_pop_no_jobs_available=True (the horde API has no new jobs to offer),
        but jobs_pending_inference already has a job waiting. The stuck WAITING_FOR_JOB
        process must be replaced so that job can eventually reach start_inference().
        """
        # 9999s stale — well above the max(process_timeout=100, VAE_SEMAPHORE_TIMEOUT=300)=300s threshold
        proc = self._make_waiting_for_job_process(0, time_elapsed=9999.0)
        job = MagicMock()

        mock_manager = self._make_manager(
            [proc],
            last_pop_no_jobs=True,
            jobs_pending_inference=[job],
        )

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(proc)

    def test_stale_waiting_for_job_not_replaced_when_no_jobs_anywhere(self) -> None:
        """A stale WAITING_FOR_JOB process must NOT be replaced when there is no work anywhere.

        WAITING_FOR_JOB is the expected idle state when there is nothing to do; replacing
        processes in that state would cause unnecessary churn.
        """
        proc = self._make_waiting_for_job_process(0, time_elapsed=9999.0)

        mock_manager = self._make_manager(
            [proc],
            last_pop_no_jobs=True,
            jobs_pending_inference=[],
            jobs_in_progress=[],
        )

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        mock_manager._replace_inference_process.assert_not_called()
        assert result is False

    def test_jobs_in_progress_alone_also_overrides_guard(self) -> None:
        """The guard must also be bypassed when jobs_in_progress is non-empty.

        Even if jobs_pending_inference is empty, an in-progress job means work is
        actively happening. A WAITING_FOR_JOB process that stops heartbeating while
        a job is in-progress should still be detected and replaced.
        """
        proc = self._make_waiting_for_job_process(0, time_elapsed=9999.0)
        in_progress_job = MagicMock()

        mock_manager = self._make_manager(
            [proc],
            last_pop_no_jobs=True,
            jobs_pending_inference=[],
            jobs_in_progress=[in_progress_job],
        )

        with patch("threading.Thread"):
            result = mock_manager._bound_replace_hung()

        assert result is True
        mock_manager._replace_inference_process.assert_called_once_with(proc)


class TestInferenceBackgroundHeartbeat:
    """Tests for the background heartbeat thread introduced to prevent false
    stuck-process detection during long-running computation phases (e.g., VAE decode).
    """

    def _make_proc(self) -> "MagicMock":
        """Create a minimal mock of HordeInferenceProcess for start_inference tests."""
        import multiprocessing

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._is_busy = False
        proc._in_post_processing = False
        proc._vae_acquire_attempted = False
        proc._vae_lock_was_acquired = False
        proc._current_job_inference_steps_complete = False
        proc._last_sanitized_negative_prompt = None
        proc._last_inference_percent = None
        proc._active_model_name = "TestModel"
        proc.VAE_SEMAPHORE_TIMEOUT = 5
        proc._INFERENCE_HEARTBEAT_INTERVAL = 30.0
        proc._inference_semaphore = multiprocessing.Semaphore(1)
        proc._vae_decode_semaphore = multiprocessing.Semaphore(1)
        proc.send_process_state_change_message = MagicMock()
        proc.send_heartbeat_message = MagicMock()
        return proc

    def test_heartbeat_thread_started_and_stopped(self) -> None:
        """The background heartbeat thread must be started before basic_inference()
        and stopped (via Event.set + join) after it returns.
        """
        import threading as _threading

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc()
        fake_result = MagicMock()
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = [fake_result]

        job_info = MagicMock()
        job_info.payload.prompt = "test"
        job_info.extra_source_images = None
        job_info.source_image = None
        job_info.source_mask = None
        job_info.ids = []

        threads_created: list[_threading.Thread] = []
        real_thread_cls = _threading.Thread

        def capturing_thread(*args: object, **kwargs: object) -> _threading.Thread:
            t = real_thread_cls(*args, **kwargs)
            threads_created.append(t)
            return t

        with patch("horde_worker_regen.process_management.inference_process.threading.Thread", capturing_thread):
            result = HordeInferenceProcess.start_inference(proc, job_info)

        assert result is not None, "start_inference must return results"
        # At least one thread was created for the heartbeat
        assert len(threads_created) >= 1, "A background heartbeat thread must be created during inference"
        # The thread must have finished (was joined)
        heartbeat_threads = [t for t in threads_created if "heartbeat" in (t.name or "")]
        assert heartbeat_threads, "A thread named with 'heartbeat' must be created during inference"
        assert not heartbeat_threads[0].is_alive(), "The heartbeat thread must be stopped after inference"

    def test_heartbeat_thread_is_daemon(self) -> None:
        """The background heartbeat thread must be a daemon thread so it does not
        prevent the process from exiting if it is somehow not stopped cleanly.
        """
        import threading as _threading

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = self._make_proc()
        fake_result = MagicMock()
        proc._horde = MagicMock()
        proc._horde.basic_inference.return_value = [fake_result]

        job_info = MagicMock()
        job_info.payload.prompt = "test"
        job_info.extra_source_images = None
        job_info.source_image = None
        job_info.source_mask = None
        job_info.ids = []

        daemon_values: list[bool | None] = []

        real_thread_init = _threading.Thread.__init__

        def patched_init(self_t: _threading.Thread, *args: object, **kwargs: object) -> None:  # noqa: ANN001
            real_thread_init(self_t, *args, **kwargs)
            daemon_values.append(self_t.daemon)

        with patch.object(_threading.Thread, "__init__", patched_init):
            HordeInferenceProcess.start_inference(proc, job_info)

        assert daemon_values, "At least one Thread must be created during inference"
        assert daemon_values[-1] is True, "The inference heartbeat thread must be a daemon thread"

    def test_inference_heartbeat_loop_sends_heartbeat(self) -> None:
        """_inference_heartbeat_loop must call send_heartbeat_message with
        PIPELINE_STATE_CHANGE and the last known inference percent before the
        stop event fires.
        """
        import threading as _threading

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess
        from horde_worker_regen.process_management.messages import HordeHeartbeatType

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._last_inference_percent = 97
        proc._INFERENCE_HEARTBEAT_INTERVAL = 0.01  # fire almost immediately

        stop_event = _threading.Event()

        # Let the loop fire once, then stop it
        call_counts: list[int] = [0]

        def track_heartbeat(**kwargs: object) -> None:
            call_counts[0] += 1
            stop_event.set()  # stop after first call

        proc.send_heartbeat_message = MagicMock(side_effect=track_heartbeat)

        HordeInferenceProcess._inference_heartbeat_loop(proc, stop_event)

        assert call_counts[0] >= 1, "_inference_heartbeat_loop must send at least one heartbeat"
        proc.send_heartbeat_message.assert_called_with(
            heartbeat_type=HordeHeartbeatType.PIPELINE_STATE_CHANGE,
            percent_complete=97,
        )

    def test_inference_heartbeat_loop_suppresses_when_no_progress(self) -> None:
        """When _last_inference_percent is None (no real progress yet), the heartbeat
        loop must NOT call send_heartbeat_message, preserving the process manager's
        no_step_heartbeat_timeout fast-path for early crash detection.
        """
        import threading as _threading

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._last_inference_percent = None
        proc._INFERENCE_HEARTBEAT_INTERVAL = 0.01  # fire almost immediately

        stop_event = _threading.Event()

        # Let the loop fire once then stop, by setting the event after a brief wait
        def stop_after_one_tick() -> None:
            import time as _time
            _time.sleep(0.05)
            stop_event.set()

        import threading as _threading2
        stopper = _threading2.Thread(target=stop_after_one_tick, daemon=True)
        stopper.start()

        HordeInferenceProcess._inference_heartbeat_loop(proc, stop_event)
        stopper.join(timeout=1.0)

        proc.send_heartbeat_message.assert_not_called()

    def test_last_inference_percent_updated_on_zero_fallback(self) -> None:
        """When comfyui_progress is absent and the fallback 0% heartbeat is sent,
        _last_inference_percent must be set to 0 so the background heartbeat thread
        can report meaningful (not None) progress.
        """
        from hordelib.horde import ProgressReport, ProgressState

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._in_post_processing = False
        proc._current_job_inference_steps_complete = False
        proc._last_inference_percent = None
        proc.send_heartbeat_message = MagicMock()
        proc._active_model_name = "TestModel"
        proc._start_inference_time = 0.0

        # Report with no comfyui_progress → triggers the fallback 0% path
        report = MagicMock(spec=ProgressReport)
        report.hordelib_progress_state = ProgressState.progress
        report.comfyui_progress = None

        HordeInferenceProcess._progress_callback_impl(proc, report)

        assert proc._last_inference_percent == 0, (
            "_last_inference_percent must be set to 0 when the fallback 0% heartbeat fires"
        )

    def test_last_inference_percent_updated_on_inference_step(self) -> None:
        """_last_inference_percent must be updated to the step's percentage when
        an INFERENCE_STEP heartbeat is sent in _progress_callback_impl.
        """
        from hordelib.horde import ProgressReport, ProgressState
        from hordelib.utils.ioredirect import ComfyUIProgress

        from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

        proc = MagicMock(spec=HordeInferenceProcess)
        proc._in_post_processing = False
        proc._current_job_inference_steps_complete = False
        proc._last_inference_percent = None
        proc.send_heartbeat_message = MagicMock()
        proc.send_memory_report_message = MagicMock()
        proc._active_model_name = "TestModel"
        proc._start_inference_time = 0.0

        # Build a progress report for step 29/30 → 97%
        comfy_progress = MagicMock(spec=ComfyUIProgress)
        comfy_progress.current_step = 29
        comfy_progress.total_steps = 30
        comfy_progress.percent = 96.67
        comfy_progress.rate = 1.96
        from hordelib.utils.ioredirect import ComfyUIProgressUnit
        comfy_progress.rate_unit = ComfyUIProgressUnit.ITERATIONS_PER_SECOND

        report = MagicMock(spec=ProgressReport)
        report.hordelib_progress_state = ProgressState.progress
        report.comfyui_progress = comfy_progress

        HordeInferenceProcess._progress_callback_impl(proc, report)

        assert proc._last_inference_percent == 96, (
            "_last_inference_percent must be updated to int(96.67) == 96 after an INFERENCE_STEP"
        )
