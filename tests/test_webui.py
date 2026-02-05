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

    # Run async test
    asyncio.run(test_webui_start_stop())
    print("✓ WebUI start/stop test passed")

    print("\nAll tests passed!")
