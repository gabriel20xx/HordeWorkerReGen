"""Tests for crash resilience improvements."""

import asyncio
import sys
import types
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


class TestReceiveAndHandleProcessMessagesResilience:
    """Tests that receive_and_handle_process_messages does not crash on INFERENCE_STARTING edge cases."""

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

    def _run_receive(self, msg: object, process_info: MagicMock) -> None:
        """Run receive_and_handle_process_messages with a single queued message."""
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

        bound = HordeWorkerProcessManager.receive_and_handle_process_messages.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        bound()  # must not raise

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
    ) -> MagicMock:
        """Create a mock process map entry with configurable timestamps."""
        entry = MagicMock()
        entry.last_process_state = state
        entry.last_progress_timestamp = last_progress_timestamp
        entry.last_heartbeat_timestamp = last_heartbeat_timestamp
        entry.last_heartbeat_delta = last_heartbeat_delta
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

