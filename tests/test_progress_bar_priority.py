"""Tests for progress bar priority and time-without-jobs tracking in update_webui_status.

The progress bar should remain active (at 100%) for a job until the generation is fully
submitted to the API, before resetting to 0% for the next generation.  Even when a new
inference job has been dispatched and is at 0%, the webui must still show the submitting
job at 100% because jobs_pending_submit is checked first.

The time_without_jobs counter must start accumulating from program launch and must count
continuously between job-pop cycles by computing a live in-flight delta on top of the
accumulated total.
"""

from unittest.mock import MagicMock, patch

from horde_worker_regen.process_management.messages import HordeProcessState


def _make_mock_job(job_id: str = "a1b2c3d4", model: str = "test_model") -> MagicMock:
    """Return a minimal mock ImageGenerateJobPopResponse."""
    job = MagicMock()
    job.id_.root = f"{job_id}-1234-5678-abcd-ef0123456789"
    job.model = model
    job.payload.n_iter = 1
    job.payload.ddim_steps = 30
    job.payload.width = 512
    job.payload.height = 512
    job.payload.sampler_name = "euler_a"
    job.payload.loras = None
    return job


def _make_mock_job_info(job: MagicMock) -> MagicMock:
    """Return a minimal mock HordeJobInfo wrapping *job*."""
    job_info = MagicMock()
    job_info.sdk_api_job_info = job
    return job_info


def _make_mock_process(
    job: MagicMock,
    state: HordeProcessState = HordeProcessState.INFERENCE_STARTING,
    percent_complete: int | None = 0,
) -> MagicMock:
    """Return a minimal mock ``HordeProcessInfo``."""
    process = MagicMock()
    process.last_job_referenced = job
    process.last_process_state = state
    process.last_heartbeat_percent_complete = percent_complete
    process.process_id = 0
    process.process_type.name = "INFERENCE"
    process.loaded_horde_model_name = job.model
    process.batch_amount = 1
    process.ram_usage_bytes = 0
    process.vram_usage_bytes = 0
    return process


def _invoke_update_webui_status(
    jobs_pending_submit: list,
    jobs_being_safety_checked: list,
    jobs_pending_safety_check: list,
    jobs_in_progress: list,
    jobs_lookup: dict | None = None,
    process_list: list | None = None,
) -> dict | None:
    """Call update_webui_status on a minimal mock manager and return the
    current_job dict that was passed to webui.update_status."""
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    mock_manager = MagicMock()

    # Attributes checked in the priority elif chain
    mock_manager.jobs_pending_submit = jobs_pending_submit
    mock_manager.jobs_being_safety_checked = jobs_being_safety_checked
    mock_manager.jobs_pending_safety_check = jobs_pending_safety_check
    mock_manager.jobs_in_progress = jobs_in_progress
    mock_manager.jobs_lookup = jobs_lookup or {}
    mock_manager.jobs_pending_inference = []

    # Bind class constants/sets
    mock_manager._WEBUI_POST_INFERENCE_STATES = HordeWorkerProcessManager._WEBUI_POST_INFERENCE_STATES

    # Bind _calculate_granular_progress so the jobs_in_progress branch can compute
    # the non-zero floor for INFERENCE_STARTING / early INFERENCE_PROCESSING.
    mock_manager._calculate_granular_progress = (
        HordeWorkerProcessManager._calculate_granular_progress.__get__(
            mock_manager, HordeWorkerProcessManager
        )
    )

    # Bind lora serialiser so the elif body doesn't fail
    mock_manager._serialize_loras_for_webui.return_value = None

    # Process map – supports multiple iterations (used for current_job, process list,
    # models_loaded, ram and vram sums)
    proc_list = process_list or []
    mock_manager._process_map.values.return_value = proc_list

    # Device map – empty so VRAM calculation is skipped
    mock_manager._device_map.root = {}

    # Simple counter / scalar attributes accessed at the end of the method
    mock_manager.kudos_events = []
    mock_manager.user_info = None
    mock_manager._time_spent_no_jobs_available = 0.0
    mock_manager._last_pop_no_jobs_available_time = 0.0

    # The webui must be non-None so the method does not return immediately
    mock_manager.webui = MagicMock()

    # Bind and call the real method, patching out psutil (avoids 0.1s cpu_percent
    # sleep) and torch (avoids CUDA probing / environment-dependent imports).
    stub_psutil = MagicMock()
    stub_psutil.cpu_percent.return_value = 0.0
    stub_psutil.cpu_count.return_value = 1
    with (
        patch("horde_worker_regen.process_management.process_manager.psutil", stub_psutil),
        patch.dict("sys.modules", {"torch": MagicMock()}),
    ):
        method = HordeWorkerProcessManager.update_webui_status.__get__(mock_manager, HordeWorkerProcessManager)
        method()

    # Extract the current_job kwarg passed to webui.update_status
    assert mock_manager.webui.update_status.called, "webui.update_status was not called"
    kwargs = mock_manager.webui.update_status.call_args.kwargs
    return kwargs.get("current_job")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pending_submit_shown_over_inference_job() -> None:
    """When a job is pending submission AND a new inference job is at 0%,
    the webui must show the submitting job at 100%, not the new job at 0%."""
    job1 = _make_mock_job("a1a1a1a1")
    job2 = _make_mock_job("b2b2b2b2")

    job1_info = _make_mock_job_info(job1)

    # job2 is in inference at 0%; job1 is waiting for API submission at 100%
    inference_process = _make_mock_process(job2, HordeProcessState.INFERENCE_STARTING, percent_complete=0)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[job1_info],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[job2],
        jobs_lookup={job2: MagicMock()},
        process_list=[inference_process],
    )

    assert current_job is not None, "Expected a current_job but got None"
    assert current_job["progress"] == 100, (
        f"Expected progress=100 for pending-submit job, got {current_job['progress']}"
    )
    # The id prefix should come from job1 (the submitting job), not job2
    assert "a1a1" in current_job["id"], (
        f"Expected job1's id in current_job, got {current_job['id']!r}"
    )


def test_no_pending_submit_shows_inference_job() -> None:
    """When there is no pending-submit job, the inference job is shown.

    At INFERENCE_STARTING with 0% raw progress the granular floor of 1% is applied
    so the progress bar never jumps to 0% at the very start of a new generation.
    """
    job2 = _make_mock_job("b2b2b2b2")
    inference_process = _make_mock_process(job2, HordeProcessState.INFERENCE_STARTING, percent_complete=0)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[job2],
        jobs_lookup={job2: MagicMock()},
        process_list=[inference_process],
    )

    assert current_job is not None, "Expected a current_job but got None"
    # The granular-progress floor maps INFERENCE_STARTING (0%) → 1% to prevent the
    # 100% → 0% → 100% jump when a previous job just finished and the new job begins.
    assert current_job["progress"] == 1, (
        f"Expected progress=1 (granular floor) for fresh inference job, got {current_job['progress']}"
    )
    assert "b2b2" in current_job["id"], f"Expected job2's id, got {current_job['id']!r}"


def test_safety_check_shown_over_inference_job() -> None:
    """When a job is being safety-checked AND a new inference job is at 0%,
    the webui must show the safety-check job at 100%."""
    job1 = _make_mock_job("a1a1a1a1")  # in safety check
    job2 = _make_mock_job("b2b2b2b2")  # in inference

    job1_info = _make_mock_job_info(job1)

    safety_process = _make_mock_process(job1, HordeProcessState.SAFETY_EVALUATING, percent_complete=None)
    inference_process = _make_mock_process(job2, HordeProcessState.INFERENCE_STARTING, percent_complete=0)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[job1_info],
        jobs_pending_safety_check=[],
        jobs_in_progress=[job2],
        jobs_lookup={job2: MagicMock()},
        process_list=[safety_process, inference_process],
    )

    assert current_job is not None
    assert current_job["progress"] == 100, (
        f"Expected progress=100 for safety-check job, got {current_job['progress']}"
    )
    assert "a1a1" in current_job["id"], f"Expected job1's id, got {current_job['id']!r}"


def test_pending_safety_shown_over_inference_job() -> None:
    """When a job is pending safety check AND a new inference job is at 0%,
    the webui must show the pending-safety job at 100%."""
    job1 = _make_mock_job("a1a1a1a1")
    job2 = _make_mock_job("b2b2b2b2")

    job1_info = _make_mock_job_info(job1)
    inference_process = _make_mock_process(job2, HordeProcessState.INFERENCE_STARTING, percent_complete=0)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[job1_info],
        jobs_in_progress=[job2],
        jobs_lookup={job2: MagicMock()},
        process_list=[inference_process],
    )

    assert current_job is not None
    assert current_job["progress"] == 100, (
        f"Expected progress=100 for pending-safety job, got {current_job['progress']}"
    )
    assert "a1a1" in current_job["id"], f"Expected job1's id, got {current_job['id']!r}"


def test_pending_submit_takes_priority_over_safety_check() -> None:
    """jobs_pending_submit has the highest priority: shown even when a job is
    also in safety check."""
    job1 = _make_mock_job("a1a1a1a1")  # in pending_submit
    job2 = _make_mock_job("b2b2b2b2")  # in safety check

    job1_info = _make_mock_job_info(job1)
    job2_info = _make_mock_job_info(job2)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[job1_info],
        jobs_being_safety_checked=[job2_info],
        jobs_pending_safety_check=[],
        jobs_in_progress=[],
        process_list=[],
    )

    assert current_job is not None
    assert current_job["progress"] == 100
    assert "a1a1" in current_job["id"], f"Expected job1's id, got {current_job['id']!r}"


def test_inference_progress_shown_when_pipeline_is_clear() -> None:
    """When no jobs are in the post-inference pipeline, inference progress is shown."""
    job = _make_mock_job("activejob")
    process = _make_mock_process(job, HordeProcessState.INFERENCE_PROCESSING, percent_complete=65)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[job],
        jobs_lookup={job: MagicMock()},
        process_list=[process],
    )

    assert current_job is not None
    assert current_job["progress"] == 65, (
        f"Expected progress=65 for mid-inference job, got {current_job['progress']}"
    )


def test_no_zero_percent_flash_at_inference_start() -> None:
    """Progress bar must never show 0% when a new inference job is at its very beginning.

    The 100% → 0% → 100% pattern occurs when a previous job just finished submission
    (progress=100%) and the next job is dispatched but has not yet completed even one
    diffusion step (raw percent_complete=0).  The granular-progress floor of 1% for
    INFERENCE_STARTING prevents this jump to 0%.
    """
    job = _make_mock_job("newjob1")
    # Simulate the very start of inference: INFERENCE_STARTING with 0% raw progress.
    process = _make_mock_process(job, HordeProcessState.INFERENCE_STARTING, percent_complete=0)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[job],
        jobs_lookup={job: MagicMock()},
        process_list=[process],
    )

    assert current_job is not None
    assert current_job["progress"] > 0, (
        f"Progress must be > 0% at INFERENCE_STARTING to avoid 100%→0%→100% flash, "
        f"got {current_job['progress']}%"
    )
    assert current_job["progress"] == 1, (
        f"Expected granular floor of 1% for INFERENCE_STARTING(0%), got {current_job['progress']}%"
    )


def test_no_zero_percent_flash_at_early_inference_processing() -> None:
    """Progress bar must never show 0% during the very first steps of INFERENCE_PROCESSING.

    Even after the state transitions from INFERENCE_STARTING to INFERENCE_PROCESSING,
    the first few progress callbacks may still report 0% (step 0 of N).  The granular
    floor of 1% must hold until the raw step-based percentage rises above it.
    """
    job = _make_mock_job("newjob2")
    # Simulate INFERENCE_PROCESSING at step 0 (first callback hasn't progressed yet).
    process = _make_mock_process(job, HordeProcessState.INFERENCE_PROCESSING, percent_complete=0)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[job],
        jobs_lookup={job: MagicMock()},
        process_list=[process],
    )

    assert current_job is not None
    assert current_job["progress"] > 0, (
        f"Progress must be > 0% at INFERENCE_PROCESSING(0%) to avoid flash, "
        f"got {current_job['progress']}%"
    )
    assert current_job["progress"] == 1, (
        f"Expected granular floor of 1% for INFERENCE_PROCESSING(0%), got {current_job['progress']}%"
    )


def test_raw_progress_used_for_mid_inference() -> None:
    """When raw inference progress is above the granular floor, the raw value wins.

    For inference > ~1% the raw step-based progress is higher than the granular mapping
    (max(1, raw*0.7)), so the actual step percentage is shown to give users accurate feedback.
    """
    job = _make_mock_job("midjob")
    process = _make_mock_process(job, HordeProcessState.INFERENCE_PROCESSING, percent_complete=65)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[job],
        jobs_lookup={job: MagicMock()},
        process_list=[process],
    )

    assert current_job is not None
    # At 65% raw: granular = max(1, int(65*0.7)) = max(1, 45) = 45; max(45, 65) = 65
    assert current_job["progress"] == 65, (
        f"Expected raw progress=65 for mid-inference job, got {current_job['progress']}%"
    )


# ---------------------------------------------------------------------------
# time_without_jobs helpers & tests
# ---------------------------------------------------------------------------


def _invoke_update_webui_status_for_time_without_jobs(
    time_spent_no_jobs_available: float,
    last_pop_no_jobs_available_time: float,
    fake_now: float,
) -> float:
    """Call ``update_webui_status`` with controlled time values and return the
    ``time_without_jobs`` kwarg that was passed to ``webui.update_status``."""
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    mock_manager = MagicMock()

    # Idle-time attributes under test
    mock_manager._time_spent_no_jobs_available = time_spent_no_jobs_available
    mock_manager._last_pop_no_jobs_available_time = last_pop_no_jobs_available_time

    # Minimal attributes required by the rest of update_webui_status
    mock_manager.jobs_pending_submit = []
    mock_manager.jobs_being_safety_checked = []
    mock_manager.jobs_pending_safety_check = []
    mock_manager.jobs_in_progress = []
    mock_manager.jobs_lookup = {}
    mock_manager.jobs_pending_inference = []
    mock_manager._WEBUI_POST_INFERENCE_STATES = HordeWorkerProcessManager._WEBUI_POST_INFERENCE_STATES
    mock_manager._calculate_granular_progress = (
        HordeWorkerProcessManager._calculate_granular_progress.__get__(mock_manager, HordeWorkerProcessManager)
    )
    mock_manager._serialize_loras_for_webui.return_value = None
    mock_manager._process_map.values.return_value = []
    mock_manager._device_map.root = {}
    mock_manager.kudos_events = []
    mock_manager.user_info = None
    mock_manager.webui = MagicMock()

    stub_psutil = MagicMock()
    stub_psutil.cpu_percent.return_value = 0.0
    stub_psutil.cpu_count.return_value = 1

    with (
        patch("horde_worker_regen.process_management.process_manager.psutil", stub_psutil),
        patch.dict("sys.modules", {"torch": MagicMock()}),
        patch("horde_worker_regen.process_management.process_manager.time.time", return_value=fake_now),
    ):
        method = HordeWorkerProcessManager.update_webui_status.__get__(mock_manager, HordeWorkerProcessManager)
        method()

    assert mock_manager.webui.update_status.called, "webui.update_status was not called"
    return mock_manager.webui.update_status.call_args.kwargs["time_without_jobs"]


def test_time_without_jobs_counts_from_anchor() -> None:
    """time_without_jobs must add the live delta to the accumulated total.

    When _last_pop_no_jobs_available_time is non-zero (idle period in progress),
    the displayed value should be the accumulated total plus the time elapsed since
    the anchor timestamp.
    """
    accumulated = 30.0  # 30 s already accumulated from previous idle cycles
    anchor = 1000.0  # timestamp when this idle period began
    fake_now = 1045.0  # 45 s later

    result = _invoke_update_webui_status_for_time_without_jobs(
        time_spent_no_jobs_available=accumulated,
        last_pop_no_jobs_available_time=anchor,
        fake_now=fake_now,
    )

    expected = accumulated + (fake_now - anchor)  # 30 + 45 = 75
    assert result == expected, f"Expected time_without_jobs={expected}, got {result}"


def test_time_without_jobs_zero_when_job_is_active() -> None:
    """time_without_jobs must not include an in-flight delta while a job is running.

    When a job is successfully popped _last_pop_no_jobs_available_time is reset to
    0.0.  The dynamic addition must be suppressed so that the counter stays frozen
    at the accumulated total (which is itself reset to 0 by convention, but the
    guard must prevent any addition regardless).
    """
    # Simulate state immediately after a successful job pop: anchor is 0.0.
    result = _invoke_update_webui_status_for_time_without_jobs(
        time_spent_no_jobs_available=0.0,
        last_pop_no_jobs_available_time=0.0,
        fake_now=9999.0,
    )

    assert result == 0.0, f"Expected time_without_jobs=0.0 while job is active, got {result}"


def test_time_without_jobs_starts_from_program_launch() -> None:
    """time_without_jobs begins accumulating from session start, before any pop.

    At init, _last_pop_no_jobs_available_time is set to session_start_time so the
    counter is non-zero as soon as the first webui update fires, even before any
    "no jobs available" pop response has been received.
    """
    session_start = 500.0  # session_start_time
    fake_now = 515.0  # 15 s after session start, webui fires for the first time

    result = _invoke_update_webui_status_for_time_without_jobs(
        time_spent_no_jobs_available=0.0,  # no pops yet, accumulated is zero
        last_pop_no_jobs_available_time=session_start,
        fake_now=fake_now,
    )

    expected = fake_now - session_start  # 15 s
    assert result == expected, f"Expected time_without_jobs={expected} from session start, got {result}"
