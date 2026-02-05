"""Simple test to verify the web UI server can be created and started."""

import asyncio

import aiohttp
import pytest

from horde_worker_regen.webui.server import WorkerWebUI


def test_webui_creation():
    """Test that WorkerWebUI can be instantiated."""
    webui = WorkerWebUI(port=0)  # Let OS assign a port
    assert webui is not None
    assert webui.port == 0
    assert webui.status_data is not None


def test_webui_status_update():
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


@pytest.mark.asyncio
async def test_webui_start_stop():
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
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{actual_port}/health") as response:
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
    
    # Run async test
    asyncio.run(test_webui_start_stop())
    print("✓ WebUI start/stop test passed")
    
    print("\nAll tests passed!")
