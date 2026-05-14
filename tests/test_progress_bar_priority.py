"""Tests for progress bar priority and time-without-jobs tracking in update_webui_status.

The progress bar should remain active (at 100%) for a job until the generation is fully
submitted to the API, before resetting to 0% for the next generation.  Even when a new
inference job has been dispatched and is at 0%, the webui must still show the submitting
job at 100% because jobs_pending_submit is checked first.

The time_without_jobs counter must start accumulating from program launch and must count
continuously between job-pop cycles by computing a live in-flight delta on top of the
accumulated total.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    jobs_pending_inference: list | None = None,
    return_full_kwargs: bool = False,
) -> dict | None:
    """Call update_webui_status on a minimal mock manager and return the
    current_job dict that was passed to webui.update_status.

    When *return_full_kwargs* is True, returns the complete kwargs dict passed to
    webui.update_status instead of just current_job (useful for asserting on
    job_queue and other fields).
    """
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    mock_manager = MagicMock()

    # Attributes checked in the priority elif chain
    mock_manager.jobs_pending_submit = jobs_pending_submit
    mock_manager.jobs_being_safety_checked = jobs_being_safety_checked
    mock_manager.jobs_pending_safety_check = jobs_pending_safety_check
    mock_manager.jobs_in_progress = jobs_in_progress
    mock_manager.jobs_lookup = jobs_lookup or {}
    mock_manager.jobs_pending_inference = jobs_pending_inference if jobs_pending_inference is not None else []

    # Bind class constants/sets
    mock_manager._WEBUI_POST_INFERENCE_STATES = HordeWorkerProcessManager._WEBUI_POST_INFERENCE_STATES

    # Bind _calculate_granular_progress so the jobs_in_progress branch can compute
    # the non-zero floor for INFERENCE_STARTING / early INFERENCE_PROCESSING.
    mock_manager._calculate_granular_progress = (
        HordeWorkerProcessManager._calculate_granular_progress.__get__(
            mock_manager, HordeWorkerProcessManager
        )
    )

    # Bind _build_current_job_dict so it returns a real dict rather than a MagicMock.
    mock_manager._build_current_job_dict = (
        HordeWorkerProcessManager._build_current_job_dict.__get__(
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
    if return_full_kwargs:
        return kwargs
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


def test_model_preloading_shown_when_no_jobs_in_progress() -> None:
    """When no jobs are in any active queue and a process is in MODEL_PRELOADING,
    the WebUI current-job panel must show that job instead of 'No job in progress'.

    This covers the scenario described in the issue:
      - One process is in MODEL_PRELOADING
      - All other processes are WAITING_FOR_JOB
    The current-job container should display the preloading process/job.
    """
    job = _make_mock_job("preload1")
    process = _make_mock_process(job, HordeProcessState.MODEL_PRELOADING, percent_complete=None)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[],
        process_list=[process],
    )

    assert current_job is not None, (
        "Expected a current_job dict while MODEL_PRELOADING, but got None (UI would show 'No job in progress')"
    )
    assert current_job["state"] == "MODEL_PRELOADING", (
        f"Expected state='MODEL_PRELOADING', got {current_job['state']!r}"
    )
    # _calculate_granular_progress maps MODEL_PRELOADING → 10%
    assert current_job["progress"] == 10, (
        f"Expected progress=10 for MODEL_PRELOADING, got {current_job['progress']}"
    )
    assert "preload" in current_job["id"], (
        f"Expected job id to contain 'preload', got {current_job['id']!r}"
    )


def test_model_preloaded_shown_when_no_jobs_in_progress() -> None:
    """MODEL_PRELOADED (model finished loading, waiting for START_INFERENCE) is
    also surfaced as the current job so the UI stays active through that phase."""
    job = _make_mock_job("preload2")
    process = _make_mock_process(job, HordeProcessState.MODEL_PRELOADED, percent_complete=None)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[],
        process_list=[process],
    )

    assert current_job is not None, (
        "Expected a current_job dict while MODEL_PRELOADED, but got None"
    )
    assert current_job["state"] == "MODEL_PRELOADED", (
        f"Expected state='MODEL_PRELOADED', got {current_job['state']!r}"
    )
    # _calculate_granular_progress maps MODEL_PRELOADED → 20%
    assert current_job["progress"] == 20, (
        f"Expected progress=20 for MODEL_PRELOADED, got {current_job['progress']}"
    )


def test_waiting_for_job_not_shown_as_current_job() -> None:
    """A process in WAITING_FOR_JOB must not be surfaced as the current job.

    If all processes are idle (WAITING_FOR_JOB) and no job queues are active,
    the UI must show 'No job in progress' (current_job=None).
    """
    job = _make_mock_job("idle1")
    process = _make_mock_process(job, HordeProcessState.WAITING_FOR_JOB, percent_complete=None)

    current_job = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[],
        process_list=[process],
    )

    assert current_job is None, (
        f"Expected current_job=None for idle WAITING_FOR_JOB process, got {current_job!r}"
    )


def test_model_preloading_job_not_duplicated_in_queue() -> None:
    """A job shown as current_job while MODEL_PRELOADING must not also appear in job_queue.

    When a process is in MODEL_PRELOADING the job is displayed in the current-job
    panel.  The same job lives in jobs_pending_inference but is not yet in
    jobs_in_progress, so without the fix it would also appear in the queue list –
    showing the same job twice in the UI.
    """
    job = _make_mock_job("preload1")
    process = _make_mock_process(job, HordeProcessState.MODEL_PRELOADING, percent_complete=None)

    kwargs = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[],
        jobs_pending_inference=[job],  # job is pending inference but not yet in progress
        process_list=[process],
        return_full_kwargs=True,
    )

    current_job = kwargs.get("current_job")
    job_queue = kwargs.get("job_queue", [])

    assert current_job is not None, "Expected current_job to be set for MODEL_PRELOADING"
    assert current_job["state"] == "MODEL_PRELOADING", (
        f"Expected state='MODEL_PRELOADING', got {current_job['state']!r}"
    )
    assert len(job_queue) == 0, (
        f"Expected job_queue to be empty (job already shown as current_job), "
        f"but got {job_queue!r}"
    )


def test_model_preloaded_job_not_duplicated_in_queue() -> None:
    """A job shown as current_job while MODEL_PRELOADED must not also appear in job_queue."""
    job = _make_mock_job("preload2")
    process = _make_mock_process(job, HordeProcessState.MODEL_PRELOADED, percent_complete=None)

    kwargs = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[],
        jobs_pending_inference=[job],
        process_list=[process],
        return_full_kwargs=True,
    )

    current_job = kwargs.get("current_job")
    job_queue = kwargs.get("job_queue", [])

    assert current_job is not None, "Expected current_job to be set for MODEL_PRELOADED"
    assert current_job["state"] == "MODEL_PRELOADED"
    assert len(job_queue) == 0, (
        f"Expected job_queue to be empty (job already shown as current_job), "
        f"but got {job_queue!r}"
    )


def test_model_preloading_other_queued_jobs_still_shown() -> None:
    """When a job is in MODEL_PRELOADING as current_job, other pending jobs must still appear in queue."""
    job_preloading = _make_mock_job("preload1")
    job_queued = _make_mock_job("queued1")
    process = _make_mock_process(job_preloading, HordeProcessState.MODEL_PRELOADING, percent_complete=None)

    kwargs = _invoke_update_webui_status(
        jobs_pending_submit=[],
        jobs_being_safety_checked=[],
        jobs_pending_safety_check=[],
        jobs_in_progress=[],
        jobs_pending_inference=[job_preloading, job_queued],
        process_list=[process],
        return_full_kwargs=True,
    )

    current_job = kwargs.get("current_job")
    job_queue = kwargs.get("job_queue", [])

    assert current_job is not None, "Expected current_job for MODEL_PRELOADING process"
    preloading_id = str(job_preloading.id_.root)[:8]
    assert current_job["id"] == preloading_id, (
        f"current_job should show the preloading job (id={preloading_id!r}), got {current_job['id']!r}"
    )
    assert len(job_queue) == 1, (
        f"Expected exactly 1 job in queue (the non-preloading job), got {job_queue!r}"
    )
    queued_id = str(job_queued.id_.root)[:8]
    assert job_queue[0]["id"] == queued_id, (
        f"Expected the queued job (id={queued_id!r}) in job_queue, got {job_queue[0]!r}"
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
    mock_manager._build_current_job_dict = (
        HordeWorkerProcessManager._build_current_job_dict.__get__(mock_manager, HordeWorkerProcessManager)
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


def test_time_without_jobs_frozen_when_job_is_active() -> None:
    """time_without_jobs must not include an in-flight delta while a job is running.

    When a job is successfully popped, any elapsed idle time since the last anchor
    is flushed into ``_time_spent_no_jobs_available`` before
    ``_last_pop_no_jobs_available_time`` is reset to 0.0.  During the job, the
    dynamic addition must be suppressed so that the counter stays frozen at the
    accumulated total (no new idle time is accrued while a job is in progress).
    """
    # Simulate state after a successful job pop: anchor is 0.0, but accumulated
    # idle time has already been flushed into _time_spent_no_jobs_available.
    accumulated_idle = 42.0
    result = _invoke_update_webui_status_for_time_without_jobs(
        time_spent_no_jobs_available=accumulated_idle,
        last_pop_no_jobs_available_time=0.0,
        fake_now=9999.0,
    )

    assert result == accumulated_idle, (
        f"Expected time_without_jobs={accumulated_idle} (frozen at accumulated total) while job is active, got {result}"
    )


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


def test_time_without_jobs_does_not_reset_when_job_is_popped() -> None:
    """time_without_jobs must not drop when a job is successfully popped.

    Before the fix, when a job was popped ``_last_pop_no_jobs_available_time`` was
    reset to 0.0 *without* first flushing the elapsed idle time into
    ``_time_spent_no_jobs_available``.  This caused the WebUI counter to drop from a
    growing value (e.g. 15 s of idle time since session start) to 0.

    The fix ensures that any elapsed idle time since the last anchor is accumulated
    before the anchor is reset, so the counter is always monotonically increasing.

    This test simulates the before-pop and after-pop WebUI states to verify there is
    no drop in the displayed counter.
    """
    # Before the job is popped: 15 s have elapsed since session start (anchor=T_start).
    session_start = 500.0
    fake_now = 515.0  # 15 s later

    before_pop = _invoke_update_webui_status_for_time_without_jobs(
        time_spent_no_jobs_available=0.0,
        last_pop_no_jobs_available_time=session_start,
        fake_now=fake_now,
    )
    # Should be 15 s
    assert before_pop == 15.0, f"Expected 15.0 before pop, got {before_pop}"

    # After the fix, when a job is popped the idle time is flushed first:
    #   _time_spent += fake_now - session_start  =>  0 + 15 = 15
    #   _last_pop_time = 0.0
    # The WebUI now shows just the accumulated total (no live delta), which equals 15 s.
    after_pop = _invoke_update_webui_status_for_time_without_jobs(
        time_spent_no_jobs_available=15.0,  # flushed by the fix
        last_pop_no_jobs_available_time=0.0,
        fake_now=fake_now,
    )

    assert after_pop >= before_pop, (
        f"time_without_jobs must not drop when a job is popped: before={before_pop}, after={after_pop}"
    )


def test_api_job_pop_flushes_idle_time_before_reset() -> None:
    """api_job_pop must flush elapsed idle time before resetting the anchor on a successful pop.

    This directly exercises the ``api_job_pop`` code path rather than simulating the
    post-pop state by hand, so that a regression in the flush logic is reliably caught.

    Setup: the worker has been idle for 20 s (anchor = T-20, accumulated = 0).
    Action: ``api_job_pop`` is called and the mocked API returns a valid job response.
    Assertion: after the call ``_time_spent_no_jobs_available`` is >= 20 s and
    ``_last_pop_no_jobs_available_time`` is 0.0.
    """
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    # Build a mock response that looks like a successful job pop
    mock_response = MagicMock()
    mock_response.id_ = "test-job-id-1234"
    mock_response.model = "test_model"
    mock_response.messages = None
    mock_response.skipped.model_dump.return_value = {}
    mock_response.skipped.model_extra = None
    mock_response.payload.loras = None
    mock_response.payload.post_processing = None
    mock_response.payload.seed = 42
    mock_response.payload.n_iter = 1
    mock_response.payload.denoising_strength = None
    mock_response.source_image = None

    mock_manager = MagicMock()

    # Idle-time state: 20 s of idle time is in-flight (not yet flushed)
    fake_anchor = 1000.0
    fake_now = 1020.0  # 20 s later
    mock_manager._time_spent_no_jobs_available = 0.0
    mock_manager._last_pop_no_jobs_available_time = fake_anchor

    # Guard conditions that must NOT cause an early return
    mock_manager._shutting_down = False
    mock_manager.horde_client_session = MagicMock()
    mock_manager._too_many_consecutive_failed_jobs = False
    mock_manager._consecutive_failed_jobs = 0
    mock_manager._consecutive_pop_failures = 0
    mock_manager._consecutive_pop_failure_warn_threshold = 5
    mock_manager._job_pop_frequency = 0.0
    mock_manager._error_job_pop_frequency = 30.0
    mock_manager._default_job_pop_frequency = 4.0
    mock_manager._last_pop_maintenance_mode = False
    mock_manager._replaced_due_to_maintenance = False
    mock_manager.bridge_data.queue_size = 5
    mock_manager.bridge_data.max_threads = 1
    mock_manager.jobs_pending_inference = []
    mock_manager.jobs_pending_submit = []
    mock_manager._process_map.get_first_available_safety_process.return_value = MagicMock()
    mock_manager._process_map.get_first_available_inference_process.return_value = MagicMock()
    mock_manager.bridge_data.image_models_to_load = ["test_model"]
    mock_manager.should_wait_for_pending_megapixelsteps.return_value = False
    mock_manager._triggered_max_pending_megapixelsteps = False
    mock_manager._last_job_pop_time = 0.0
    mock_manager.bridge_data.horde_model_stickiness = 0
    mock_manager.bridge_data.custom_models = None
    mock_manager.bridge_data.api_key = "0" * 22  # must be 22 characters
    mock_manager.bridge_data.dreamer_worker_name = "test_worker"
    mock_manager.bridge_data.blacklist = []
    mock_manager.bridge_data.nsfw = False
    mock_manager.max_concurrent_inference_processes = 1
    mock_manager.bridge_data.max_power = 8
    mock_manager.bridge_data.require_upfront_kudos = False
    mock_manager.bridge_data.allow_img2img = True
    mock_manager.bridge_data.allow_inpainting = True
    mock_manager.bridge_data.allow_unsafe_ip = False
    mock_manager.bridge_data.allow_post_processing = True
    mock_manager.bridge_data.allow_controlnet = True
    mock_manager.bridge_data.allow_sdxl_controlnet = False
    mock_manager.bridge_data.extra_slow_worker = False
    mock_manager.bridge_data.limit_max_steps = False
    mock_manager.bridge_data.allow_lora = True
    mock_manager.bridge_data.max_batch = 1
    mock_manager.max_inference_processes = 1

    # Inference-failure cooldown: no models in cooldown for this test
    mock_manager._inference_failures = {}
    mock_manager._INFERENCE_FAILURE_THRESHOLD = HordeWorkerProcessManager._INFERENCE_FAILURE_THRESHOLD
    mock_manager._INFERENCE_FAILURE_WINDOW = HordeWorkerProcessManager._INFERENCE_FAILURE_WINDOW
    mock_manager._INFERENCE_FAILURE_COOLDOWN = HordeWorkerProcessManager._INFERENCE_FAILURE_COOLDOWN
    mock_manager._last_warned_inference_cooldown_models = frozenset()
    mock_manager._last_warned_inference_cooldown_at = 0.0
    import types as _types
    mock_manager._prune_preload_stuck_failures = _types.MethodType(
        HordeWorkerProcessManager._prune_preload_stuck_failures,
        mock_manager,
    )
    mock_manager._is_model_in_inference_cooldown = _types.MethodType(
        HordeWorkerProcessManager._is_model_in_inference_cooldown,
        mock_manager,
    )

    # Mock the HTTP call and post-pop helpers
    mock_manager.horde_client_session.submit_request = AsyncMock(return_value=mock_response)
    mock_manager._get_source_images = AsyncMock(return_value=mock_response)
    mock_manager._jobs_pending_inference_lock = asyncio.Lock()
    mock_manager._job_pop_timestamps_lock = asyncio.Lock()
    mock_manager.job_faults = {}
    mock_manager.jobs_lookup = {}
    mock_manager.job_pop_timestamps = {}
    mock_manager.total_num_jobs_queued = 0

    with (
        patch("horde_worker_regen.process_management.process_manager.time.time", return_value=fake_now),
        patch("horde_worker_regen.process_management.process_manager.HordeJobInfo", MagicMock()),
    ):
        bound = HordeWorkerProcessManager.api_job_pop.__get__(mock_manager, HordeWorkerProcessManager)
        asyncio.run(bound())

    # The flush must have accumulated the 20 s of idle time and reset the anchor
    assert mock_manager._time_spent_no_jobs_available >= 20.0, (
        f"Expected _time_spent_no_jobs_available >= 20.0 after pop, "
        f"got {mock_manager._time_spent_no_jobs_available}"
    )
    assert mock_manager._last_pop_no_jobs_available_time == 0.0, (
        f"Expected _last_pop_no_jobs_available_time == 0.0 after pop, "
        f"got {mock_manager._last_pop_no_jobs_available_time}"
    )


def test_idle_timer_restarts_immediately_when_last_job_leaves_queue() -> None:
    """time_without_jobs counter must resume as soon as the last job leaves jobs_pending_inference.

    Before the fix, after a successful job pop ``_last_pop_no_jobs_available_time`` was reset
    to 0.0.  When the job finished (removed from ``jobs_pending_inference``) the anchor stayed
    at 0.0, so the WebUI counter remained frozen until the *next* job-pop cycle returned "no
    jobs available" — a gap of up to ``_job_pop_frequency`` seconds.

    The fix sets ``_last_pop_no_jobs_available_time = time.time()`` the moment the queue
    empties, so the live delta starts accumulating immediately.

    This test drives ``handle_job_fault`` with a permanently-faulted job (retry_count already
    at MAX_JOB_RETRIES) so that the job is removed from the queue, and verifies that
    ``_last_pop_no_jobs_available_time`` becomes non-zero right after the last job is removed.
    """
    from collections import deque
    from unittest.mock import patch

    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    # Build a minimal fake job
    fake_job = MagicMock()
    fake_job.id_ = MagicMock()
    fake_job.id_.root = "aaaabbbb-cccc-dddd-eeee-000011112222"
    fake_job.model = "test_model"
    fake_job.payload.loras = None
    fake_job.payload.workflow = None

    # job_info with retry_count already exhausted so handle_job_fault goes to the permanent-fault path
    job_info = MagicMock()
    job_info.retry_count = HordeWorkerProcessManager.MAX_JOB_RETRIES  # retry exhausted

    # Build a minimal mock manager
    mock_manager = MagicMock()
    mock_manager.MAX_JOB_RETRIES = HordeWorkerProcessManager.MAX_JOB_RETRIES

    # Idle-timer state: anchor was reset to 0.0 when the job was successfully popped
    fake_now = 2000.0
    mock_manager._last_pop_no_jobs_available_time = 0.0
    mock_manager._time_spent_no_jobs_available = 19.0

    # The job is the only one in the queue
    mock_manager.jobs_pending_inference = deque([fake_job])
    mock_manager.jobs_in_progress = []
    mock_manager.jobs_lookup = MagicMock()
    mock_manager.jobs_lookup.get = lambda k, d=None: {fake_job: job_info}.get(k, d)

    mock_manager._skipped_line_next_job_and_process = None
    mock_manager._faulted_jobs_history = []
    mock_manager._max_faulted_jobs_history = 10
    mock_manager._num_jobs_faulted = 0
    mock_manager._failed_models = {}

    # Bind the real helper so the idle-timer restart logic actually runs
    mock_manager._restart_idle_timer_if_queue_empty = (
        HordeWorkerProcessManager._restart_idle_timer_if_queue_empty.__get__(
            mock_manager, HordeWorkerProcessManager
        )
    )

    with patch("horde_worker_regen.process_management.process_manager.time.time", return_value=fake_now):
        method = HordeWorkerProcessManager.handle_job_fault.__get__(mock_manager, HordeWorkerProcessManager)
        method(faulted_job=fake_job)

    # After the last job leaves the queue, the anchor must be non-zero so that
    # update_webui_status can add a live delta and the counter keeps incrementing.
    assert mock_manager._last_pop_no_jobs_available_time == fake_now, (
        "Expected _last_pop_no_jobs_available_time to be set to current time immediately after "
        f"the last job left jobs_pending_inference, got {mock_manager._last_pop_no_jobs_available_time}"
    )

    # The accumulated total must not have decreased
    assert mock_manager._time_spent_no_jobs_available >= 19.0, (
        f"Accumulated idle time must not decrease, got {mock_manager._time_spent_no_jobs_available}"
    )


def test_idle_timer_restarts_when_last_job_removed_before_handle_job_fault() -> None:
    """Idle timer must restart even when the job was removed from the queue *before*
    ``handle_job_fault`` is called with ``job_info is None`` (the metadata-missing path).

    This covers the ``_fault_cooldown_model_jobs`` scenario: the job is stripped from
    ``jobs_pending_inference`` externally before ``handle_job_fault`` is invoked.  Without
    the fix in the ``job_info is None`` branch, the anchor remains ``0.0`` and the WebUI
    counter stays frozen.
    """
    from unittest.mock import patch

    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    fake_job = MagicMock()
    fake_job.id_ = MagicMock()
    fake_job.id_.root = "bbbbcccc-dddd-eeee-ffff-111122223333"
    fake_job.model = "test_model"
    fake_job.payload.loras = None
    fake_job.payload.workflow = None

    mock_manager = MagicMock()
    mock_manager.MAX_JOB_RETRIES = HordeWorkerProcessManager.MAX_JOB_RETRIES

    fake_now = 3000.0
    mock_manager._last_pop_no_jobs_available_time = 0.0
    mock_manager._time_spent_no_jobs_available = 7.0

    # The job has ALREADY been removed from the queue (simulating _fault_cooldown_model_jobs)
    from collections import deque

    mock_manager.jobs_pending_inference = deque()  # already empty
    mock_manager.jobs_in_progress = []
    # job is NOT in jobs_lookup (metadata-missing path)
    mock_manager.jobs_lookup = MagicMock()
    mock_manager.jobs_lookup.get = lambda k, d=None: None

    mock_manager._faulted_jobs_history = []
    mock_manager._max_faulted_jobs_history = 10

    mock_manager._restart_idle_timer_if_queue_empty = (
        HordeWorkerProcessManager._restart_idle_timer_if_queue_empty.__get__(
            mock_manager, HordeWorkerProcessManager
        )
    )

    with patch("horde_worker_regen.process_management.process_manager.time.time", return_value=fake_now):
        method = HordeWorkerProcessManager.handle_job_fault.__get__(mock_manager, HordeWorkerProcessManager)
        method(faulted_job=fake_job)

    assert mock_manager._last_pop_no_jobs_available_time == fake_now, (
        "Expected idle-timer anchor to be restarted in the job_info-is-None path of handle_job_fault, "
        f"got {mock_manager._last_pop_no_jobs_available_time}"
    )
    assert mock_manager._time_spent_no_jobs_available >= 7.0, (
        f"Accumulated idle time must not decrease, got {mock_manager._time_spent_no_jobs_available}"
    )


def test_set_job_pops_paused_freezes_idle_timer() -> None:
    """Pausing job pops must flush the in-flight delta and reset the anchor.

    When ``set_job_pops_paused(True)`` is called while the idle timer is running
    (anchor > 0), the elapsed time since the anchor must be accumulated into
    ``_time_spent_no_jobs_available`` and ``_last_pop_no_jobs_available_time``
    must be reset to 0.0 so that further calls to ``update_webui_status`` or
    ``_restart_idle_timer_if_queue_empty`` do not keep counting paused time.
    """
    import types as _types
    from collections import deque

    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    accumulated = 10.0
    anchor = 500.0
    fake_now = 530.0  # 30 s since the anchor

    mock_manager = MagicMock()
    mock_manager._job_pops_paused = False
    mock_manager._last_pop_no_jobs_available_time = anchor
    mock_manager._time_spent_no_jobs_available = accumulated
    # _restart_idle_timer_if_queue_empty is not called on pause, but wire it up
    # as the real method just in case to avoid silent MagicMock swallowing bugs.
    mock_manager._restart_idle_timer_if_queue_empty = _types.MethodType(
        HordeWorkerProcessManager._restart_idle_timer_if_queue_empty,
        mock_manager,
    )
    mock_manager.jobs_pending_inference = deque()

    with patch("horde_worker_regen.process_management.process_manager.time.time", return_value=fake_now):
        method = HordeWorkerProcessManager.set_job_pops_paused.__get__(mock_manager, HordeWorkerProcessManager)
        method(True)

    assert mock_manager._last_pop_no_jobs_available_time == 0.0, (
        f"Expected anchor reset to 0.0 after pause, got {mock_manager._last_pop_no_jobs_available_time}"
    )
    expected_accumulated = accumulated + (fake_now - anchor)  # 10 + 30 = 40
    assert mock_manager._time_spent_no_jobs_available == expected_accumulated, (
        f"Expected _time_spent_no_jobs_available={expected_accumulated} after pause, "
        f"got {mock_manager._time_spent_no_jobs_available}"
    )


def test_set_job_pops_resumed_restarts_idle_timer_when_queue_empty() -> None:
    """Resuming job pops must restart the idle anchor immediately when the queue is empty.

    After ``set_job_pops_paused(False)``, ``_last_pop_no_jobs_available_time`` must
    become non-zero straight away (rather than waiting up to ``_job_pop_frequency``
    seconds for the next no-jobs response to set a new anchor).
    """
    import types as _types
    from collections import deque

    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    fake_now = 700.0

    mock_manager = MagicMock()
    mock_manager._job_pops_paused = True
    mock_manager._last_pop_no_jobs_available_time = 0.0  # frozen while paused
    mock_manager._time_spent_no_jobs_available = 25.0
    mock_manager.jobs_pending_inference = deque()  # queue is empty

    # Bind the real helper so the idle-timer restart logic executes.
    mock_manager._restart_idle_timer_if_queue_empty = _types.MethodType(
        HordeWorkerProcessManager._restart_idle_timer_if_queue_empty,
        mock_manager,
    )

    with patch("horde_worker_regen.process_management.process_manager.time.time", return_value=fake_now):
        method = HordeWorkerProcessManager.set_job_pops_paused.__get__(mock_manager, HordeWorkerProcessManager)
        method(False)

    assert mock_manager._last_pop_no_jobs_available_time == fake_now, (
        "Expected idle anchor to be restarted to current time on resume with empty queue, "
        f"got {mock_manager._last_pop_no_jobs_available_time}"
    )


def test_idle_timer_does_not_restart_while_paused() -> None:
    """_restart_idle_timer_if_queue_empty must not restart the anchor while paused.

    Even if the queue is empty, the idle timer must not resume accumulating time
    while job pops are paused, so that paused time is excluded from
    ``time_without_jobs``.
    """
    import types as _types
    from collections import deque

    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    fake_now = 800.0

    mock_manager = MagicMock()
    mock_manager._job_pops_paused = True
    mock_manager._last_pop_no_jobs_available_time = 0.0
    mock_manager.jobs_pending_inference = deque()  # empty queue

    with patch("horde_worker_regen.process_management.process_manager.time.time", return_value=fake_now):
        method = HordeWorkerProcessManager._restart_idle_timer_if_queue_empty.__get__(
            mock_manager, HordeWorkerProcessManager
        )
        method()

    assert mock_manager._last_pop_no_jobs_available_time == 0.0, (
        "Expected anchor to remain 0.0 while paused, "
        f"got {mock_manager._last_pop_no_jobs_available_time}"
    )


class TestApiJobPopQueueGate:
    """Unit tests for the queue-size gate in api_job_pop.

    The gate must:
    - Stop popping when the number of not-yet-started jobs >= queue_size
    - Also stop when total pending jobs >= max_inference_processes (max_threads + queue_size)
    - Allow popping while there is still room in the prefetch queue AND total process capacity
    """

    def _make_manager(
        self,
        queue_size: int,
        max_concurrent: int,
        jobs_pending: int,
        jobs_in_progress: int,
    ) -> MagicMock:
        """Return a mock manager wired with only the attributes the queue gate touches.

        Sets horde_client_session to a sentinel MagicMock so callers can detect whether
        the gate fired (sentinel untouched) or was passed (sentinel accessed).
        """
        mock_manager = MagicMock()
        mock_manager._shutting_down = False
        mock_manager._too_many_consecutive_failed_jobs = False
        mock_manager._consecutive_failed_jobs = 0

        mock_manager.bridge_data.queue_size = queue_size
        mock_manager.max_concurrent_inference_processes = max_concurrent
        mock_manager.max_inference_processes = max_concurrent + queue_size

        # Build minimal job lists - in_progress jobs are a prefix of pending_jobs
        # so that len() checks reflect reality.
        pending_jobs = [MagicMock() for _ in range(jobs_pending)]
        in_progress_jobs = pending_jobs[:jobs_in_progress]

        mock_manager.jobs_pending_inference = pending_jobs
        mock_manager.jobs_in_progress = in_progress_jobs

        # Sentinel: if the gate fires early, horde_client_session is never accessed
        # by the code after the gate.  The "if self.horde_client_session is None"
        # check lives *after* the gate, so we use a plain MagicMock here and switch
        # it to None in tests that want the pop to proceed past the gate.
        mock_manager.horde_client_session = MagicMock(name="sentinel")

        return mock_manager

    @staticmethod
    def _run(mock_manager: MagicMock) -> None:
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        import asyncio

        bound = HordeWorkerProcessManager.api_job_pop.__get__(mock_manager, HordeWorkerProcessManager)
        asyncio.run(bound())

    def test_gate_stops_when_queued_exceeds_queue_size(self) -> None:
        """Pop gate returns early when jobs_queued >= queue_size."""
        # 2 pending, 0 in-progress → 2 queued; queue_size=1 → gate must fire
        mock_manager = self._make_manager(queue_size=1, max_concurrent=4, jobs_pending=2, jobs_in_progress=0)
        sentinel = mock_manager.horde_client_session

        self._run(mock_manager)

        # Gate returned before reaching "if self.horde_client_session is None"
        sentinel.assert_not_called()

    def test_gate_stops_when_pending_meets_max_inference(self) -> None:
        """Pop gate returns early when total pending jobs >= max_inference_processes (max_threads + queue_size)."""
        # 5 pending, 5 in-progress → 0 queued; queue_size=3 → first condition passes.
        # max_inference_processes = max_concurrent(2) + queue_size(3) = 5; total pending=5 → second condition fires.
        mock_manager = self._make_manager(queue_size=3, max_concurrent=2, jobs_pending=5, jobs_in_progress=5)
        sentinel = mock_manager.horde_client_session

        self._run(mock_manager)

        sentinel.assert_not_called()

    def test_gate_allows_pop_when_room_in_both_queue_and_threads(self) -> None:
        """Pop gate does NOT return early when queue and thread capacity both have room."""
        # 1 active job → 0 queued; queue_size=2, max_concurrent=2 → gate must NOT fire
        # Set horde_client_session=None so api_job_pop returns immediately after the gate
        # without needing further mocks for the rest of the function.
        mock_manager = self._make_manager(queue_size=2, max_concurrent=2, jobs_pending=1, jobs_in_progress=1)
        mock_manager.horde_client_session = None

        # Should reach "if self.horde_client_session is None: return" without raising
        self._run(mock_manager)

    def test_queue_size_zero_stops_immediately(self) -> None:
        """queue_size=0 means no pre-fetching; gate fires even with no queued jobs."""
        # 0 pending → jobs_queued=0 >= queue_size=0 → gate fires
        mock_manager = self._make_manager(queue_size=0, max_concurrent=2, jobs_pending=0, jobs_in_progress=0)
        sentinel = mock_manager.horde_client_session

        self._run(mock_manager)

        sentinel.assert_not_called()

    def test_active_jobs_do_not_consume_queue_size_slots(self) -> None:
        """Active (in-progress) jobs must NOT reduce available queue_size slots."""
        # 1 active (in-progress) job; queue_size=1, max_concurrent=2
        # jobs_queued = max(0, 1 - 1) = 0 < queue_size=1 → gate must NOT fire on queue check
        # len(jobs_pending_inference)=1 < max_concurrent=2 → gate must NOT fire on thread check
        # Set horde_client_session=None so api_job_pop returns immediately after the gate.
        mock_manager = self._make_manager(queue_size=1, max_concurrent=2, jobs_pending=1, jobs_in_progress=1)
        mock_manager.horde_client_session = None

        # Should not return from the gate; reaching here means gate correctly let the pop through
        self._run(mock_manager)


class TestApiJobPopPerModelFilterRemoved:
    """Integration tests verifying that the per-model job filter has been removed.

    Previously, any model that already had >= 2 pending jobs was excluded from the
    pop request. This meant a single-model setup with queue_size > 1 could never fill
    the queue past 2 jobs. With the filter removed, the only capacity gate is the total
    pending count vs. max_inference_processes (max_threads + queue_size).
    """

    @staticmethod
    def _make_no_jobs_response() -> MagicMock:
        """Return a mock API response indicating no job is currently available."""
        r = MagicMock()
        r.id_ = None
        r.messages = None
        r.skipped = MagicMock()
        r.skipped.model_dump.return_value = {}
        r.skipped.model_extra = None
        return r

    def _make_manager(
        self,
        model_name: str,
        models_to_load: list[str],
        jobs_pending: int,
        jobs_in_progress: int,
        queue_size: int,
        max_concurrent: int,
    ) -> MagicMock:
        """Build a fully-wired mock manager that passes all gates and reaches the API call.

        All jobs are assigned to *model_name*. The API response is pre-configured as
        "no job available" (id_ = None) so no further job-processing mocks are needed.
        """
        mock_manager = MagicMock()
        mock_manager._shutting_down = False
        mock_manager._too_many_consecutive_failed_jobs = False
        mock_manager._consecutive_failed_jobs = 0
        mock_manager._consecutive_pop_failures = 0
        mock_manager._consecutive_pop_failure_warn_threshold = 5
        mock_manager._last_pop_maintenance_mode = False
        mock_manager._replaced_due_to_maintenance = False

        mock_manager.bridge_data.queue_size = queue_size
        mock_manager.max_concurrent_inference_processes = max_concurrent
        mock_manager.max_inference_processes = max_concurrent + queue_size

        # Build jobs – all sharing the same model name so the old filter would have triggered.
        pending_jobs = [MagicMock() for _ in range(jobs_pending)]
        for job in pending_jobs:
            job.model = model_name
        # jobs_in_progress is intentionally a subset of jobs_pending_inference: in the real
        # manager, in-progress jobs remain in the pending list while being actively processed.
        mock_manager.jobs_pending_inference = pending_jobs
        mock_manager.jobs_in_progress = pending_jobs[:jobs_in_progress]

        # Intermediate guards
        mock_manager._process_map.get_first_available_safety_process.return_value = MagicMock()
        mock_manager._process_map.get_first_available_inference_process.return_value = MagicMock()
        mock_manager.bridge_data.image_models_to_load = models_to_load
        mock_manager.should_wait_for_pending_megapixelsteps.return_value = False
        mock_manager._triggered_max_pending_megapixelsteps = False
        mock_manager._last_job_pop_time = 0.0
        mock_manager._job_pop_frequency = 0.0
        mock_manager._error_job_pop_frequency = 30.0
        mock_manager._default_job_pop_frequency = 4.0
        mock_manager._process_map.values.return_value = []
        mock_manager.bridge_data.horde_model_stickiness = 0
        mock_manager.bridge_data.custom_models = None

        # Inference-failure cooldown: no models in cooldown for this test
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager
        import types as _types

        mock_manager._inference_failures = {}
        mock_manager._INFERENCE_FAILURE_THRESHOLD = HordeWorkerProcessManager._INFERENCE_FAILURE_THRESHOLD
        mock_manager._INFERENCE_FAILURE_WINDOW = HordeWorkerProcessManager._INFERENCE_FAILURE_WINDOW
        mock_manager._INFERENCE_FAILURE_COOLDOWN = HordeWorkerProcessManager._INFERENCE_FAILURE_COOLDOWN
        mock_manager._last_warned_inference_cooldown_models = frozenset()
        mock_manager._last_warned_inference_cooldown_at = 0.0
        mock_manager._prune_preload_stuck_failures = _types.MethodType(
            HordeWorkerProcessManager._prune_preload_stuck_failures,
            mock_manager,
        )
        mock_manager._is_model_in_inference_cooldown = _types.MethodType(
            HordeWorkerProcessManager._is_model_in_inference_cooldown,
            mock_manager,
        )

        # Idle-timer state
        mock_manager._last_pop_no_jobs_available = False
        mock_manager._last_pop_no_jobs_available_time = 0.0
        mock_manager._time_spent_no_jobs_available = 0.0

        # API request attributes
        mock_manager.bridge_data.api_key = "0" * 22
        mock_manager.bridge_data.dreamer_worker_name = "test_worker"
        mock_manager.bridge_data.blacklist = []
        mock_manager.bridge_data.nsfw = False
        mock_manager.bridge_data.max_power = 8
        mock_manager.bridge_data.require_upfront_kudos = False
        mock_manager.bridge_data.allow_img2img = True
        mock_manager.bridge_data.allow_inpainting = True
        mock_manager.bridge_data.allow_unsafe_ip = False
        mock_manager.bridge_data.allow_post_processing = True
        mock_manager.bridge_data.allow_controlnet = True
        mock_manager.bridge_data.allow_sdxl_controlnet = False
        mock_manager.bridge_data.extra_slow_worker = False
        mock_manager.bridge_data.limit_max_steps = False
        mock_manager.bridge_data.allow_lora = True
        mock_manager.bridge_data.max_batch = 1

        mock_manager.horde_client_session.submit_request = AsyncMock(
            return_value=self._make_no_jobs_response(),
        )

        return mock_manager

    @staticmethod
    def _run(mock_manager: MagicMock) -> None:
        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        bound = HordeWorkerProcessManager.api_job_pop.__get__(mock_manager, HordeWorkerProcessManager)
        asyncio.run(bound())

    def test_single_model_two_pending_still_pops(self) -> None:
        """A single model with 2 pending jobs must not be excluded from the pop request.

        The old per-model filter used ``count >= 2``, which removed the only model from
        the request set once two jobs were already pending. This caused the queue to
        silently stall at 2 jobs regardless of queue_size.  With the filter removed, the
        API pop must still be attempted.
        """
        mock_manager = self._make_manager(
            model_name="stable_diffusion",
            models_to_load=["stable_diffusion"],
            jobs_pending=2,
            jobs_in_progress=2,
            queue_size=3,
            max_concurrent=1,
        )

        self._run(mock_manager)

        mock_manager.horde_client_session.submit_request.assert_called_once()
        pop_request = mock_manager.horde_client_session.submit_request.call_args[0][0]
        assert "stable_diffusion" in pop_request.models

    def test_single_model_queue_fills_to_capacity(self) -> None:
        """The queue can hold max_inference_processes - 1 pending jobs with a single model.

        queue_size=3, max_concurrent=1 → max_inference_processes=4.
        3 pending (1 in-progress + 2 pre-fetched) is within capacity; the API must be called.
        """
        mock_manager = self._make_manager(
            model_name="stable_diffusion",
            models_to_load=["stable_diffusion"],
            jobs_pending=3,
            jobs_in_progress=1,
            queue_size=3,
            max_concurrent=1,
        )

        self._run(mock_manager)

        mock_manager.horde_client_session.submit_request.assert_called_once()
        pop_request = mock_manager.horde_client_session.submit_request.call_args[0][0]
        assert "stable_diffusion" in pop_request.models


def test_update_webui_status_passes_total_ram_mb_and_container_cpu_percent() -> None:
    """update_webui_status must pass total_ram_mb, system_ram_usage_mb, and container_cpu_percent.

    Regression guard: ensures the process manager correctly computes all RAM metrics and
    container CPU from the cached psutil.Process instance, and passes them through to
    the WebUI layer.
    """
    from horde_worker_regen.process_management.process_manager import BYTES_TO_MEGABYTES, HordeWorkerProcessManager

    mock_manager = MagicMock()

    # Minimal attributes required by update_webui_status
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
    mock_manager._build_current_job_dict = (
        HordeWorkerProcessManager._build_current_job_dict.__get__(mock_manager, HordeWorkerProcessManager)
    )
    mock_manager._serialize_loras_for_webui.return_value = None
    mock_manager._process_map.values.return_value = []
    mock_manager._device_map.root = {}
    mock_manager.kudos_events = []
    mock_manager.user_info = None
    mock_manager._time_spent_no_jobs_available = 0.0
    mock_manager._last_pop_no_jobs_available_time = 0.0
    mock_manager.webui = MagicMock()

    # Set up known RAM and container CPU values to verify they are passed through.
    total_ram_bytes = 32 * 1024 * 1024 * 1024  # 32 GB
    mock_manager.total_ram_bytes = total_ram_bytes
    expected_total_ram_mb = total_ram_bytes / BYTES_TO_MEGABYTES  # 32768.0

    # Simulate the cached process tree returning 70% raw CPU on a 4-core machine.
    # 40% from the main process + 20% + 10% from two child processes.
    mock_proc = MagicMock()
    mock_proc.cpu_percent.return_value = 40.0
    child_proc_1 = MagicMock()
    child_proc_1.pid = 1001
    child_proc_1.cpu_percent.return_value = 20.0
    child_proc_2 = MagicMock()
    child_proc_2.pid = 1002
    child_proc_2.cpu_percent.return_value = 10.0
    mock_proc.children.return_value = [child_proc_1, child_proc_2]
    mock_proc.pid = 1000
    mock_manager._main_process = mock_proc
    mock_manager._container_cpu_processes = {mock_proc.pid: mock_proc}

    stub_psutil = MagicMock()
    stub_psutil.cpu_percent.return_value = 0.0
    stub_psutil.cpu_count.return_value = 4  # 4 logical cores
    # Simulate virtual_memory().used: 24 GB in use system-wide
    system_used_bytes = 24 * 1024 * 1024 * 1024
    stub_psutil.virtual_memory.return_value.used = system_used_bytes
    expected_system_ram_mb = system_used_bytes / BYTES_TO_MEGABYTES  # 24576.0

    with (
        patch("horde_worker_regen.process_management.process_manager.psutil", stub_psutil),
        patch.dict("sys.modules", {"torch": MagicMock()}),
    ):
        method = HordeWorkerProcessManager.update_webui_status.__get__(mock_manager, HordeWorkerProcessManager)
        method()

    assert mock_manager.webui.update_status.called, "webui.update_status was not called"
    kwargs = mock_manager.webui.update_status.call_args.kwargs
    mock_proc.children.assert_called_once_with(recursive=True)

    # total_ram_mb must equal total_ram_bytes converted to MB.
    assert kwargs["total_ram_mb"] == expected_total_ram_mb, (
        f"Expected total_ram_mb={expected_total_ram_mb}, got {kwargs['total_ram_mb']}"
    )

    # system_ram_usage_mb must equal virtual_memory().used converted to MB.
    assert kwargs["system_ram_usage_mb"] == expected_system_ram_mb, (
        f"Expected system_ram_usage_mb={expected_system_ram_mb}, got {kwargs['system_ram_usage_mb']}"
    )

    # container_cpu_percent must equal raw_cpu / cpu_cores = (40 + 20 + 10) / 4 = 17.5.
    expected_container_cpu = round((40.0 + 20.0 + 10.0) / 4, 1)
    assert kwargs["container_cpu_percent"] == expected_container_cpu, (
        f"Expected container_cpu_percent={expected_container_cpu}, got {kwargs['container_cpu_percent']}"
    )

    # worker_gpu_percent must be present (derived from process map gpu_usage_percent fields).
    assert "worker_gpu_percent" in kwargs, "worker_gpu_percent was not passed to webui.update_status"

    # system_vram_usage_mb must be present (computed from torch.cuda.mem_get_info across devices).
    assert "system_vram_usage_mb" in kwargs, "system_vram_usage_mb was not passed to webui.update_status"


def _make_minimal_manager_for_update_webui_status_metrics() -> MagicMock:
    """Create a minimal manager mock suitable for update_webui_status metric assertions."""
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    mock_manager = MagicMock()
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
    mock_manager._build_current_job_dict = (
        HordeWorkerProcessManager._build_current_job_dict.__get__(mock_manager, HordeWorkerProcessManager)
    )
    mock_manager._serialize_loras_for_webui.return_value = None
    mock_manager._process_map.values.return_value = []
    mock_manager._device_map.root = {}
    mock_manager.kudos_events = []
    mock_manager.user_info = None
    mock_manager._time_spent_no_jobs_available = 0.0
    mock_manager._last_pop_no_jobs_available_time = 0.0
    mock_manager.total_ram_bytes = 0
    mock_manager.webui = MagicMock()

    return mock_manager


def test_update_webui_status_gpu_cores_count_sums_known_cuda_devices() -> None:
    """Known CUDA architectures should be summed, while unknown ones are skipped."""
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    mock_manager = _make_minimal_manager_for_update_webui_status_metrics()

    stub_psutil = MagicMock()
    stub_psutil.cpu_percent.return_value = 0.0
    stub_psutil.cpu_count.return_value = 1
    stub_psutil.virtual_memory.return_value.used = 0

    stub_torch = MagicMock()
    stub_torch.cuda.is_available.return_value = True
    stub_torch.cuda.device_count.return_value = 3
    stub_torch.cuda.get_device_properties.side_effect = [
        SimpleNamespace(major=8, minor=6, multi_processor_count=30),   # 30 * 128 = 3840
        SimpleNamespace(major=8, minor=9, multi_processor_count=80),   # 80 * 128 = 10240
        SimpleNamespace(major=10, minor=0, multi_processor_count=100),  # unknown -> skipped
    ]

    with (
        patch("horde_worker_regen.process_management.process_manager.psutil", stub_psutil),
        patch.dict("sys.modules", {"torch": stub_torch}),
    ):
        method = HordeWorkerProcessManager.update_webui_status.__get__(mock_manager, HordeWorkerProcessManager)
        method()

    kwargs = mock_manager.webui.update_status.call_args.kwargs
    assert kwargs["gpu_cores_count"] == 14080


def test_update_webui_status_gpu_cores_count_unknown_arch_keeps_previous_value() -> None:
    """If all CUDA architectures are unknown, gpu_cores_count should be left unchanged."""
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    mock_manager = _make_minimal_manager_for_update_webui_status_metrics()

    stub_psutil = MagicMock()
    stub_psutil.cpu_percent.return_value = 0.0
    stub_psutil.cpu_count.return_value = 1
    stub_psutil.virtual_memory.return_value.used = 0

    stub_torch = MagicMock()
    stub_torch.cuda.is_available.return_value = True
    stub_torch.cuda.device_count.return_value = 1
    stub_torch.cuda.get_device_properties.return_value = SimpleNamespace(major=10, minor=0, multi_processor_count=100)

    with (
        patch("horde_worker_regen.process_management.process_manager.psutil", stub_psutil),
        patch.dict("sys.modules", {"torch": stub_torch}),
    ):
        method = HordeWorkerProcessManager.update_webui_status.__get__(mock_manager, HordeWorkerProcessManager)
        method()

    kwargs = mock_manager.webui.update_status.call_args.kwargs
    assert kwargs["gpu_cores_count"] is None
