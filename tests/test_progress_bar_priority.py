"""Tests for progress bar priority: current job progress must stay active until submitted.

The progress bar should remain active (at 100%) for a job until the generation is fully
submitted to the API, before resetting to 0% for the next generation.  Even when a new
inference job has been dispatched and is at 0%, the webui must still show the submitting
job at 100% because jobs_pending_submit is checked first.
"""

from unittest.mock import MagicMock, call

import pytest

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

    # The webui must be non-None so the method does not return immediately
    mock_manager.webui = MagicMock()

    # Bind and call the real method
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
    """When there is no pending-submit job, the inference job is shown with its
    actual progress (0% at INFERENCE_STARTING)."""
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
    assert current_job["progress"] == 0, (
        f"Expected progress=0 for fresh inference job, got {current_job['progress']}"
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
