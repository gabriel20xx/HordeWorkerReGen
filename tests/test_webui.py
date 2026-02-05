"""Simple test to verify the web UI server can be created and started."""

import asyncio

import aiohttp
import pytest

from horde_worker_regen.webui.server import WorkerWebUI


def test_webui_creation() -> None:
    """Test that WorkerWebUI can be instantiated."""
    webui = WorkerWebUI(port=0)  # Let OS assign a port
    assert webui is not None
    assert webui.port == 0
    assert webui.status_data is not None


def test_webui_status_update() -> None:
    """Test that WorkerWebUI status can be updated."""
    webui = WorkerWebUI(port=0)  # Let OS assign a port

    # Update some status values
    webui.update_status(
        worker_name="TestWorker",
        jobs_popped=10,
        jobs_completed=8,
        jobs_faulted=1,
        kudos_earned_session=100.5,
        kudos_per_hour=50.25,
    )

    # Verify the values were updated
    assert webui.status_data["worker_name"] == "TestWorker"
    assert webui.status_data["jobs_popped"] == 10
    assert webui.status_data["jobs_completed"] == 8
    assert webui.status_data["jobs_faulted"] == 1
    assert webui.status_data["kudos_earned_session"] == 100.5
    assert webui.status_data["kudos_per_hour"] == 50.25


def test_webui_vram_resources() -> None:
    """Test that WorkerWebUI correctly handles VRAM resource updates."""
    webui = WorkerWebUI(port=0)

    # Test VRAM usage and total VRAM update
    test_vram_usage_mb = 8192.5  # 8GB used
    test_total_vram_mb = 24576.0  # 24GB total
    test_ram_usage_mb = 16384.0  # 16GB RAM

    webui.update_status(
        vram_usage_mb=test_vram_usage_mb,
        total_vram_mb=test_total_vram_mb,
        ram_usage_mb=test_ram_usage_mb,
    )

    # Verify the values were updated correctly
    assert webui.status_data["vram_usage_mb"] == test_vram_usage_mb
    assert webui.status_data["total_vram_mb"] == test_total_vram_mb
    assert webui.status_data["ram_usage_mb"] == test_ram_usage_mb

    # Test that VRAM percentage would be calculated correctly (33% in this case)
    expected_percent = round((test_vram_usage_mb / test_total_vram_mb) * 100)
    assert expected_percent == 33


def test_webui_new_features() -> None:
    """Test that WorkerWebUI handles new features (image preview and console logs)."""
    webui = WorkerWebUI(port=0)

    # Test last image update
    test_image_base64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    webui.update_status(last_image_base64=test_image_base64)
    assert webui.status_data["last_image_base64"] == test_image_base64

    # Test console logs update
    test_logs = ["Log line 1", "Log line 2", "Log line 3"]
    webui.update_status(console_logs=test_logs)
    assert webui.status_data["console_logs"] == test_logs

    # Test current job with is_complete flag
    current_job = {
        "id": "test123",
        "model": "TestModel",
        "state": "INFERENCE_COMPLETE",
        "progress": 100,
        "is_complete": True,
    }
    webui.update_status(current_job=current_job)
    assert webui.status_data["current_job"] == current_job
    assert webui.status_data["current_job"]["is_complete"] is True


def test_webui_faulted_jobs_history() -> None:
    """Test that WorkerWebUI handles faulted jobs history."""
    webui = WorkerWebUI(port=0)

    # Test faulted jobs history update
    test_faulted_jobs = [
        {
            "job_id": "job123",
            "model": "TestModel1",
            "time_faulted": 1234567890.0,
            "width": 512,
            "height": 512,
            "steps": 30,
            "sampler": "euler_a",
            "loras": [{"name": "test_lora", "model": 1.0, "clip": 1.0}],
            "controlnet": "canny",
            "workflow": "qr_code",
            "batch_size": 4,
            "fault_phase": "During Inference",
        },
        {
            "job_id": "job456",
            "model": "TestModel2",
            "time_faulted": 1234567891.0,
            "width": 768,
            "height": 768,
            "steps": 50,
            "sampler": "dpm_2",
            "loras": [],
            "controlnet": None,
            "workflow": None,
            "batch_size": 1,
            "fault_phase": "Post Processing",
        },
    ]
    webui.update_status(faulted_jobs_history=test_faulted_jobs)
    assert webui.status_data["faulted_jobs_history"] == test_faulted_jobs
    assert len(webui.status_data["faulted_jobs_history"]) == 2
    assert webui.status_data["faulted_jobs_history"][0]["job_id"] == "job123"
    assert webui.status_data["faulted_jobs_history"][0]["batch_size"] == 4
    assert webui.status_data["faulted_jobs_history"][0]["fault_phase"] == "During Inference"
    assert webui.status_data["faulted_jobs_history"][1]["model"] == "TestModel2"
    assert webui.status_data["faulted_jobs_history"][1]["fault_phase"] == "Post Processing"


def test_webui_batch_size_display() -> None:
    """Test that WorkerWebUI handles batch size in current job and job queue."""
    webui = WorkerWebUI(port=0)

    # Test current job with batch size
    current_job_batch = {
        "id": "test789",
        "model": "TestModel",
        "state": "INFERENCE_STARTING",
        "progress": 50,
        "is_complete": False,
        "batch_size": 3,
    }
    webui.update_status(current_job=current_job_batch)
    assert webui.status_data["current_job"] == current_job_batch
    assert webui.status_data["current_job"]["batch_size"] == 3

    # Test current job without batch size (batch_size = 1)
    current_job_single = {
        "id": "test790",
        "model": "TestModel2",
        "state": "PROCESSING",
        "progress": 25,
        "is_complete": False,
        "batch_size": 1,
    }
    webui.update_status(current_job=current_job_single)
    assert webui.status_data["current_job"]["batch_size"] == 1

    # Test job queue with various batch sizes
    job_queue_with_batches = [
        {"id": "queue1", "model": "Model1", "batch_size": 2},
        {"id": "queue2", "model": "Model2", "batch_size": 1},
        {"id": "queue3", "model": "Model3", "batch_size": 5},
    ]
    webui.update_status(job_queue=job_queue_with_batches)
    assert webui.status_data["job_queue"] == job_queue_with_batches
    assert webui.status_data["job_queue"][0]["batch_size"] == 2
    assert webui.status_data["job_queue"][1]["batch_size"] == 1
    assert webui.status_data["job_queue"][2]["batch_size"] == 5


@pytest.mark.asyncio
async def test_webui_start_stop() -> None:
    """Test that WorkerWebUI can be started and stopped."""
    webui = WorkerWebUI(port=0)  # Let OS assign an available port

    try:
        # Start the server
        await webui.start()

        # Give it a moment to start
        await asyncio.sleep(0.5)

        # Get the actual port assigned
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # Verify it's running by checking if we can access the health endpoint
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/health",
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert data["status"] == "ok"
    finally:
        # Stop the server
        await webui.stop()


if __name__ == "__main__":
    # Run simple tests
    test_webui_creation()
    print("✓ WebUI creation test passed")

    test_webui_status_update()
    print("✓ WebUI status update test passed")

    test_webui_vram_resources()
    print("✓ WebUI VRAM resources test passed")

    test_webui_new_features()
    print("✓ WebUI new features test passed")

    test_webui_faulted_jobs_history()
    print("✓ WebUI faulted jobs history test passed")

    test_webui_batch_size_display()
    print("✓ WebUI batch size display test passed")

    # Run async test
    asyncio.run(test_webui_start_stop())
    print("✓ WebUI start/stop test passed")

    print("\nAll tests passed!")
