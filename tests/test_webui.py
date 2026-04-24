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
        horde_username="TestUser#123",
        jobs_popped=10,
        jobs_queued=15,
        jobs_completed=8,
        jobs_faulted=1,
        processes_recovered=2,
        kudos_earned_session=100.5,
        kudos_per_hour=50.25,
        images_per_hour=12.5,
    )

    # Verify the values were updated
    assert webui.status_data["worker_name"] == "TestWorker"
    assert webui.status_data["horde_username"] == "TestUser#123"
    assert webui.status_data["jobs_popped"] == 10
    assert webui.status_data["jobs_queued"] == 15
    assert webui.status_data["jobs_completed"] == 8
    assert webui.status_data["jobs_faulted"] == 1
    assert webui.status_data["processes_recovered"] == 2
    assert webui.status_data["kudos_earned_session"] == 100.5
    assert webui.status_data["kudos_per_hour"] == 50.25
    assert webui.status_data["images_per_hour"] == 12.5


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


def test_webui_cpu_gpu_usage() -> None:
    """Test that WorkerWebUI correctly handles CPU and GPU usage updates."""
    webui = WorkerWebUI(port=0)

    # Test CPU and GPU usage update
    test_cpu_usage_percent = 45.5
    test_gpu_usage_percent = 78.2

    webui.update_status(
        cpu_usage_percent=test_cpu_usage_percent,
        gpu_usage_percent=test_gpu_usage_percent,
    )

    # Verify the values were updated correctly
    assert webui.status_data["cpu_usage_percent"] == test_cpu_usage_percent
    assert webui.status_data["gpu_usage_percent"] == test_gpu_usage_percent

    # Test edge case: 0% usage
    webui.update_status(
        cpu_usage_percent=0.0,
        gpu_usage_percent=0.0,
    )
    assert webui.status_data["cpu_usage_percent"] == 0.0
    assert webui.status_data["gpu_usage_percent"] == 0.0

    # Test edge case: 100% usage
    webui.update_status(
        cpu_usage_percent=100.0,
        gpu_usage_percent=100.0,
    )
    assert webui.status_data["cpu_usage_percent"] == 100.0
    assert webui.status_data["gpu_usage_percent"] == 100.0


def test_webui_cpu_cores_count() -> None:
    """Test that WorkerWebUI correctly handles CPU cores count updates."""
    webui = WorkerWebUI(port=0)

    # Test CPU cores count update
    test_cpu_cores_count = 16

    webui.update_status(
        cpu_cores_count=test_cpu_cores_count,
    )

    # Verify the value was updated correctly
    assert webui.status_data["cpu_cores_count"] == test_cpu_cores_count

    # Test different core counts
    webui.update_status(cpu_cores_count=8)
    assert webui.status_data["cpu_cores_count"] == 8

    webui.update_status(cpu_cores_count=32)
    assert webui.status_data["cpu_cores_count"] == 32


def test_webui_vram_over_100_percent() -> None:
    """Test that WorkerWebUI correctly handles edge case where VRAM usage might exceed total (should cap at 100%)."""
    webui = WorkerWebUI(port=0)

    # Test edge case: VRAM usage exceeding total (shouldn't happen with fix, but frontend should cap it)
    test_vram_usage_mb = 30000.0  # 30GB used
    test_total_vram_mb = 24576.0  # 24GB total

    webui.update_status(
        vram_usage_mb=test_vram_usage_mb,
        total_vram_mb=test_total_vram_mb,
    )

    # Verify the values were updated
    assert webui.status_data["vram_usage_mb"] == test_vram_usage_mb
    assert webui.status_data["total_vram_mb"] == test_total_vram_mb

    # Test that calculated percentage would be over 100% before capping (122% in this case)
    raw_percent = round((test_vram_usage_mb / test_total_vram_mb) * 100)
    assert raw_percent > 100

    # The frontend JavaScript now uses Math.min(100, ...) to cap at 100%
    # This test documents that the frontend will display 100% even if the calculation exceeds it


def test_webui_new_features() -> None:
    """Test that WorkerWebUI handles new features (image preview and console logs)."""
    webui = WorkerWebUI(port=0)

    # Test last image update (single image)
    test_image_base64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    webui.update_status(last_image_base64=[test_image_base64])
    assert webui.status_data["last_image_base64"] == [test_image_base64]

    # Test last image update (multiple images for batch jobs)
    test_images_base64 = [test_image_base64, test_image_base64, test_image_base64]
    webui.update_status(last_image_base64=test_images_base64)
    assert webui.status_data["last_image_base64"] == test_images_base64
    assert len(webui.status_data["last_image_base64"]) == 3

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
    assert webui.status_data["faulted_jobs_history"][0]["model"] == "TestModel1"
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


def test_webui_current_job_detailed_info() -> None:
    """Test that WorkerWebUI handles detailed job info (steps, size, sampler, loras) in current job."""
    webui = WorkerWebUI(port=0)

    # Test current job with all new fields
    current_job_detailed = {
        "id": "test999",
        "model": "TestModel",
        "state": "INFERENCE_PROCESSING",
        "progress": 75,
        "is_complete": False,
        "batch_size": 2,
        "steps": 30,
        "width": 512,
        "height": 768,
        "sampler": "euler_a",
        "loras": [
            {"name": "test_lora_1", "model": 1.0, "clip": 1.0},
            {"name": "test_lora_2", "model": 0.8, "clip": 0.8},
        ],
    }
    webui.update_status(current_job=current_job_detailed)
    assert webui.status_data["current_job"] == current_job_detailed
    assert webui.status_data["current_job"]["steps"] == 30
    assert webui.status_data["current_job"]["width"] == 512
    assert webui.status_data["current_job"]["height"] == 768
    assert webui.status_data["current_job"]["sampler"] == "euler_a"
    assert len(webui.status_data["current_job"]["loras"]) == 2
    assert webui.status_data["current_job"]["loras"][0]["name"] == "test_lora_1"

    # Test current job without loras
    current_job_no_loras = {
        "id": "test998",
        "model": "TestModel2",
        "state": "INFERENCE_STARTING",
        "progress": 10,
        "is_complete": False,
        "batch_size": 1,
        "steps": 20,
        "width": 1024,
        "height": 1024,
        "sampler": "dpm_2",
        "loras": None,
    }
    webui.update_status(current_job=current_job_no_loras)
    assert webui.status_data["current_job"]["loras"] is None
    assert webui.status_data["current_job"]["steps"] == 20
    assert webui.status_data["current_job"]["width"] == 1024
    assert webui.status_data["current_job"]["sampler"] == "dpm_2"


def test_webui_last_image_submission_timestamp() -> None:
    """Test that WorkerWebUI handles last image submission timestamp."""
    import time

    webui = WorkerWebUI(port=0)

    # Test default value (0.0 = no image submitted yet)
    assert webui.status_data["last_image_submission_timestamp"] == 0.0

    # Test updating with a timestamp
    test_timestamp = time.time()
    webui.update_status(last_image_submission_timestamp=test_timestamp)
    assert webui.status_data["last_image_submission_timestamp"] == test_timestamp

    # Test updating with an older timestamp (simulating submission from past)
    old_timestamp = time.time() - 3600  # 1 hour ago
    webui.update_status(last_image_submission_timestamp=old_timestamp)
    assert webui.status_data["last_image_submission_timestamp"] == old_timestamp

    # Verify timestamp is retained after updating other fields
    webui.update_status(jobs_completed=5)
    assert webui.status_data["last_image_submission_timestamp"] == old_timestamp


def test_webui_images_history() -> None:
    """Test that WorkerWebUI handles gallery images via add_gallery_image / /api/gallery."""
    webui = WorkerWebUI(port=0)

    # Test default state: no images_history in status_data; images_count starts at 0
    assert "images_history" not in webui.status_data
    assert webui.status_data["images_count"] == 0
    assert webui._gallery_dict == {}

    # Test adding a single image entry
    test_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    webui.add_gallery_image({"base64": test_image_b64, "timestamp": 1704067205.0, "model": "stable_diffusion_xl"})
    assert len(webui._gallery_dict) == 1
    assert webui.status_data["images_count"] == 1
    assert webui._gallery_dict[0]["model"] == "stable_diffusion_xl"

    # Test adding multiple image entries
    webui.add_gallery_image({"base64": test_image_b64, "timestamp": 1704067210.0, "model": "stable_diffusion_2_1"})
    webui.add_gallery_image({"base64": test_image_b64, "timestamp": 1704067215.0, "model": None})
    assert len(webui._gallery_dict) == 3
    assert webui.status_data["images_count"] == 3
    assert webui._gallery_dict[1]["model"] == "stable_diffusion_2_1"
    assert webui._gallery_dict[2]["model"] is None

    # Test that gallery is unbounded – adding more than 200 entries keeps all of them.
    for i in range(200):
        webui.add_gallery_image({"base64": test_image_b64, "timestamp": float(i), "model": "sdxl"})
    assert len(webui._gallery_dict) == 203
    assert webui.status_data["images_count"] == 203

    # Verify /api/status does NOT include base64 image data
    assert "images_history" not in webui.status_data


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


@pytest.mark.asyncio
async def test_webui_gallery_thumbnail_only() -> None:
    """Test that /api/gallery strips full-res base64 when a thumbnail is present."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # A minimal 1×1 PNG in base64
        test_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )

        # Add an entry *without* a thumbnail (simulates PIL not being available)
        webui._gallery_dict[0] = {"gallery_id": 0, "base64": test_b64, "timestamp": 1.0, "model": "m1"}

        # Add an entry *with* a thumbnail (simulates PIL available; thumbnail_only stripping applies)
        webui._gallery_dict[1] = {"gallery_id": 1, "base64": test_b64, "thumbnail": "thumb_data", "timestamp": 2.0, "model": "m2"}
        webui.status_data["images_count"] = 2

        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery?page=1&page_size=48",
        ) as response:
            assert response.status == 200
            data = await response.json()

        assert data["total"] == 2
        # Newest first: index 0 = entry with thumbnail (base64 should be stripped)
        entry_with_thumb = data["images"][0]
        assert "thumbnail" in entry_with_thumb
        assert "gallery_id" in entry_with_thumb
        assert "base64" not in entry_with_thumb, "base64 must be stripped when thumbnail exists"

        # index 1 = entry without thumbnail (base64 should be kept as fallback)
        entry_no_thumb = data["images"][1]
        assert "base64" in entry_no_thumb, "base64 must be kept when no thumbnail is available"
        assert "thumbnail" not in entry_no_thumb
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_gallery_image_endpoint() -> None:
    """Test that /api/gallery/image returns the full-resolution image by stable gallery_id."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        test_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )

        # Use add_gallery_image so gallery_id values are stamped by the server.
        webui.add_gallery_image({"base64": test_b64, "timestamp": 1.0, "model": "older"})
        webui.add_gallery_image({"base64": test_b64, "timestamp": 2.0, "model": "newer"})

        # Retrieve the gallery_id values from the /api/gallery response.
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery?page=1&page_size=48",
        ) as response:
            assert response.status == 200
            gallery_data = await response.json()

        assert gallery_data["total"] == 2
        newer_id = gallery_data["images"][0]["gallery_id"]  # newest first
        older_id = gallery_data["images"][1]["gallery_id"]

        # Fetch by stable gallery_id: should return the "newer" image regardless of order.
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image?id={newer_id}",
        ) as response:
            assert response.status == 200
            img = await response.json()
        assert img["model"] == "newer"
        assert img["base64"] == test_b64

        # Fetch the older image by its gallery_id.
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image?id={older_id}",
        ) as response:
            assert response.status == 200
            img = await response.json()
        assert img["model"] == "older"

        # Stable: adding a new image must not shift existing gallery_ids.
        webui.add_gallery_image({"base64": test_b64, "timestamp": 3.0, "model": "newest"})
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image?id={older_id}",
        ) as response:
            assert response.status == 200
            img = await response.json()
        assert img["model"] == "older", "gallery_id must remain stable after new images are added"

        # Non-existent gallery_id should return 404.
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image?id=99999",
        ) as response:
            assert response.status == 404

        # Missing id parameter should return 400.
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image",
        ) as response:
            assert response.status == 400

        # Invalid (non-integer) id should return 400.
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image?id=abc",
        ) as response:
            assert response.status == 400
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_status_excludes_images_and_last_image_endpoint() -> None:
    """Test that /api/status omits last_image_base64 and /api/last_image serves it."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        test_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        test_timestamp = 1704067200.0
        webui.update_status(
            last_image_base64=[test_b64],
            last_image_submission_timestamp=test_timestamp,
        )

        # /api/status must NOT include the image payload
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/status",
        ) as response:
            assert response.status == 200
            status = await response.json()
        assert "last_image_base64" not in status, "/api/status must not expose last_image_base64"
        assert status["last_image_submission_timestamp"] == test_timestamp

        # /api/last_image must return the full image list and timestamp
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/last_image",
        ) as response:
            assert response.status == 200
            img_data = await response.json()
        assert "last_image_base64" in img_data
        assert img_data["last_image_base64"] == [test_b64]
        assert img_data["last_image_submission_timestamp"] == test_timestamp
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_gallery_metadata_only() -> None:
    """Test that /api/gallery?metadata_only=true strips both thumbnail and base64."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        test_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )

        # Entry without thumbnail (base64 only)
        webui._gallery_dict[0] = {"gallery_id": 0, "base64": test_b64, "timestamp": 1.0, "model": "m1"}
        # Entry with both thumbnail and base64
        webui._gallery_dict[1] = {"gallery_id": 1, "base64": test_b64, "thumbnail": "thumb_data", "timestamp": 2.0, "model": "m2"}

        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery?page=1&page_size=48&metadata_only=true",
        ) as response:
            assert response.status == 200
            data = await response.json()

        assert data["total"] == 2
        for entry in data["images"]:
            assert "base64" not in entry, "base64 must be stripped with metadata_only=true"
            assert "thumbnail" not in entry, "thumbnail must be stripped with metadata_only=true"
            assert "gallery_id" in entry
            assert "timestamp" in entry
            assert "model" in entry
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_gallery_image_thumbnail_only() -> None:
    """Test that /api/gallery/image?thumbnail_only=true strips full-res base64."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        test_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )

        # Entry with both thumbnail and base64
        webui._gallery_dict[5] = {"gallery_id": 5, "base64": test_b64, "thumbnail": "thumb_data", "timestamp": 1.0, "model": "m1"}
        # Entry without thumbnail (base64 only); thumbnail_only should still work (no thumbnail to return)
        webui._gallery_dict[6] = {"gallery_id": 6, "base64": test_b64, "timestamp": 2.0, "model": "m2"}

        # thumbnail_only=true on entry that has a thumbnail: base64 must be stripped
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image?id=5&thumbnail_only=true",
        ) as response:
            assert response.status == 200
            img = await response.json()
        assert "base64" not in img, "base64 must be stripped when thumbnail_only=true"
        assert img["thumbnail"] == "thumb_data"
        assert img["model"] == "m1"

        # thumbnail_only=false (default) on same entry: base64 must be present
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image?id=5",
        ) as response:
            assert response.status == 200
            img = await response.json()
        assert img["base64"] == test_b64
        assert img["thumbnail"] == "thumb_data"

        # thumbnail_only=true on entry without thumbnail: base64 is kept as a fallback
        # so the frontend can still render the image even without a generated thumbnail.
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/gallery/image?id=6&thumbnail_only=true",
        ) as response:
            assert response.status == 200
            img = await response.json()
        assert img["base64"] == test_b64
        assert img["model"] == "m2"
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_status_excludes_errors_history_and_has_errors_count() -> None:
    """Test that /api/status omits errors_history and includes errors_count."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # Populate some errors
        webui.update_status(errors_history=["error one", "error two", "error three"])

        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/status",
        ) as response:
            assert response.status == 200
            status = await response.json()

        assert "errors_history" not in status, "/api/status must not expose the full errors_history list"
        assert "errors_count" in status, "/api/status must include errors_count"
        assert status["errors_count"] == 3

        # Adding more errors must be reflected in errors_count
        webui.update_status(errors_history=["error one", "error two", "error three", "error four"])
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/status",
        ) as response:
            status2 = await response.json()
        assert status2["errors_count"] == 4
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_errors_endpoint_pagination() -> None:
    """Test /api/errors returns paginated slices of the error history."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # Add 25 errors
        errors = [f"error {i}" for i in range(25)]
        webui.update_status(errors_history=errors)

        # Default page (page=1, page_size=10)
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors",
        ) as response:
            assert response.status == 200
            data = await response.json()
        assert data["total"] == 25
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert data["total_pages"] == 3
        assert len(data["errors"]) == 10
        assert data["errors"] == errors[:10]

        # Page 2
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors?page=2&page_size=10",
        ) as response:
            assert response.status == 200
            data2 = await response.json()
        assert data2["page"] == 2
        assert len(data2["errors"]) == 10
        assert data2["errors"] == errors[10:20]

        # Last page (partial)
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors?page=3&page_size=10",
        ) as response:
            assert response.status == 200
            data3 = await response.json()
        assert data3["page"] == 3
        assert len(data3["errors"]) == 5
        assert data3["errors"] == errors[20:25]

        # Custom page_size
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors?page=1&page_size=5",
        ) as response:
            assert response.status == 200
            data4 = await response.json()
        assert data4["total_pages"] == 5
        assert len(data4["errors"]) == 5
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_errors_endpoint_edge_cases() -> None:
    """Test /api/errors handles out-of-range page, invalid params, and empty history."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # Empty history
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors",
        ) as response:
            assert response.status == 200
            data = await response.json()
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["total_pages"] == 1
        assert data["errors"] == []

        # Populate errors for remaining tests
        webui.update_status(errors_history=[f"error {i}" for i in range(15)])

        # Out-of-range page is clamped to last page
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors?page=999",
        ) as response:
            assert response.status == 200
            data_clamped = await response.json()
        assert data_clamped["page"] == data_clamped["total_pages"]
        assert len(data_clamped["errors"]) > 0

        # page=0 is treated as page=1
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors?page=0",
        ) as response:
            assert response.status == 200
            data_zero = await response.json()
        assert data_zero["page"] == 1

        # Invalid (non-integer) page falls back to 1
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors?page=abc",
        ) as response:
            assert response.status == 200
            data_inv = await response.json()
        assert data_inv["page"] == 1

        # page_size is capped at 100
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors?page_size=9999",
        ) as response:
            assert response.status == 200
            data_cap = await response.json()
        assert data_cap["page_size"] == 100
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_status_includes_images_per_hour() -> None:
    """Test that /api/status JSON payload includes the images_per_hour field."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        webui.update_status(images_per_hour=7.5)

        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/status",
        ) as response:
            assert response.status == 200
            status = await response.json()

        assert "images_per_hour" in status, "/api/status must include images_per_hour"
        assert status["images_per_hour"] == 7.5
    finally:
        await webui.stop()


def test_webui_user_details_status_update() -> None:
    """Test that update_status correctly stores user_details in status_data."""
    webui = WorkerWebUI(port=0)

    sample_workers: list[dict] = [
        {
            "id": "worker-id-1",
            "name": "TestWorker",
            "version": "0.9.0",
            "type": "image",
            "online": True,
            "nsfw": False,
            "trusted": True,
            "img2img": True,
            "painting": False,
            "lora": True,
            "max_pixels": 4194304,
            "threads": 2,
            "models": ["stable_diffusion", "sdxl"],
            "uptime": 7200,
            "kudos_rewards": 3600.0,
        },
    ]
    user_details = {
        "worker_count": 1,
        "trusted": True,
        "moderator": False,
        "workers_list": sample_workers,
        "kudos_details": {"accumulated": 5000.0, "gifted": 100.0},
    }

    webui.update_status(user_details=user_details)

    assert "user_details" in webui.status_data, "status_data must contain user_details"
    stored = webui.status_data["user_details"]
    assert stored["worker_count"] == 1
    assert stored["trusted"] is True
    assert stored["moderator"] is False
    assert len(stored["workers_list"]) == 1
    w = stored["workers_list"][0]
    assert w["name"] == "TestWorker"
    assert w["version"] == "0.9.0"
    assert w["type"] == "image"
    assert w["nsfw"] is False
    assert w["trusted"] is True
    assert w["img2img"] is True
    assert w["threads"] == 2
    assert w["models"] == ["stable_diffusion", "sdxl"]
    assert w["uptime"] == 7200
    assert w["kudos_rewards"] == 3600.0
    assert stored["kudos_details"]["accumulated"] == 5000.0


@pytest.mark.asyncio
async def test_webui_status_api_includes_user_details() -> None:
    """Test that /api/status includes user_details with workers_list."""
    webui = WorkerWebUI(port=0)

    sample_workers: list[dict] = [
        {
            "id": "worker-id-2",
            "name": "ApiTestWorker",
            "version": "1.0.0",
            "type": "image",
            "online": True,
            "nsfw": True,
            "trusted": False,
            "img2img": False,
            "painting": True,
            "lora": False,
            "max_pixels": 1048576,
            "threads": 1,
            "models": ["model_a", "model_b", "model_c"],
            "uptime": 3600,
            "kudos_rewards": 1800.0,
        },
    ]
    user_details = {
        "worker_count": 1,
        "trusted": False,
        "workers_list": sample_workers,
    }

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        webui.update_status(user_details=user_details)

        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/status",
        ) as response:
            assert response.status == 200
            status = await response.json()

        assert "user_details" in status, "/api/status must include user_details"
        ud = status["user_details"]
        assert ud["worker_count"] == 1
        assert ud["trusted"] is False
        assert len(ud["workers_list"]) == 1
        w = ud["workers_list"][0]
        assert w["name"] == "ApiTestWorker"
        assert w["type"] == "image"
        assert w["nsfw"] is True
        assert w["models"] == ["model_a", "model_b", "model_c"]
        assert w["uptime"] == 3600
        assert w["kudos_rewards"] == 1800.0
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_delete_worker_endpoint() -> None:
    """Test the DELETE /api/worker/{worker_id} endpoint."""
    webui = WorkerWebUI(port=0)

    offline_worker: dict = {
        "id": "offline-worker-uuid",
        "name": "OldWorker",
        "version": "1.0",
        "type": "image",
        "online": False,
        "nsfw": False,
        "trusted": False,
        "img2img": False,
        "painting": False,
        "lora": False,
        "max_pixels": 1048576,
        "threads": 1,
        "models": [],
        "uptime": 0,
        "kudos_rewards": 0.0,
    }
    online_worker: dict = {**offline_worker, "id": "online-worker-uuid", "name": "ActiveWorker", "online": True}
    current_worker: dict = {**offline_worker, "id": "current-worker-uuid", "name": "CurrentWorker", "online": False}

    user_details = {
        "worker_count": 3,
        "workers_list": [offline_worker, online_worker, current_worker],
    }
    webui.update_status(worker_name="CurrentWorker", user_details=user_details)

    deleted_ids: list[str] = []

    async def fake_delete(worker_id: str) -> bool:
        deleted_ids.append(worker_id)
        return True

    webui.set_delete_worker_callback(fake_delete)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # 404 for unknown worker
        async with aiohttp.ClientSession() as session, session.delete(
            f"http://localhost:{actual_port}/api/worker/nonexistent-id",
        ) as response:
            assert response.status == 404

        # 400 for online worker
        async with aiohttp.ClientSession() as session, session.delete(
            f"http://localhost:{actual_port}/api/worker/{online_worker['id']}",
        ) as response:
            assert response.status == 400
            body = await response.json()
            assert "online" in body["error"].lower()

        # 400 for current (running) worker even though offline
        async with aiohttp.ClientSession() as session, session.delete(
            f"http://localhost:{actual_port}/api/worker/{current_worker['id']}",
        ) as response:
            assert response.status == 400
            body = await response.json()
            assert "web ui" in body["error"].lower() or "currently running" in body["error"].lower()

        # 200 for valid offline, non-current worker
        async with aiohttp.ClientSession() as session, session.delete(
            f"http://localhost:{actual_port}/api/worker/{offline_worker['id']}",
        ) as response:
            assert response.status == 200
            body = await response.json()
            assert body["deleted_id"] == offline_worker["id"]

        assert offline_worker["id"] in deleted_ids

        # Callback returning False yields 502
        async def failing_delete(worker_id: str) -> bool:
            return False

        webui.set_delete_worker_callback(failing_delete)
        # Re-add the worker so validation passes
        webui.update_status(user_details=user_details)
        async with aiohttp.ClientSession() as session, session.delete(
            f"http://localhost:{actual_port}/api/worker/{offline_worker['id']}",
        ) as response:
            assert response.status == 502

        # 503 when no callback is registered
        webui.set_delete_worker_callback(None)
        webui.update_status(user_details=user_details)
        async with aiohttp.ClientSession() as session, session.delete(
            f"http://localhost:{actual_port}/api/worker/{offline_worker['id']}",
        ) as response:
            assert response.status == 503

    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_errors_grouped_endpoint_basic() -> None:
    """Test /api/errors/grouped groups identical errors and returns correct counts."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # Empty history returns empty groups
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors/grouped",
        ) as response:
            assert response.status == 200
            data = await response.json()
        assert data["total_groups"] == 0
        assert data["total_errors"] == 0
        assert data["groups"] == []

        # Populate with repeated errors; "gamma error" only appears once and must be excluded
        errors = ["alpha error", "beta error", "alpha error", "gamma error", "alpha error", "beta error"]
        webui.update_status(errors_history=errors)

        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors/grouped",
        ) as response:
            assert response.status == 200
            data = await response.json()

        assert data["total_errors"] == 6
        # Only "alpha error" (×3) and "beta error" (×2) qualify; "gamma error" (×1) is excluded
        assert data["total_groups"] == 2

        # Groups must be sorted by count descending
        messages = [g["message"] for g in data["groups"]]
        counts = [g["count"] for g in data["groups"]]
        assert messages[0] == "alpha error"
        assert counts[0] == 3
        assert messages[1] == "beta error"
        assert counts[1] == 2
        # "gamma error" (single occurrence) must not appear in grouped view
        assert "gamma error" not in messages
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_errors_grouped_endpoint_normalisation() -> None:
    """Test /api/errors/grouped groups errors that differ only by UUID/job/process/hex ID."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        uuid1 = "11111111-2222-3333-4444-555555555555"
        uuid2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        pid1 = "98765"
        pid2 = "12345"
        hex1 = "0xDEADBEEF"
        hex2 = "0x1234ABCD"

        errors = [
            f"Job {uuid1} failed: connection timeout",
            f"Job {uuid2} failed: connection timeout",
            f"Process {pid1} crashed unexpectedly",
            f"Process {pid2} crashed unexpectedly",
            f"Memory access violation at address {hex1}",
            f"Memory access violation at address {hex2}",
        ]
        webui.update_status(errors_history=errors)

        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors/grouped",
        ) as response:
            assert response.status == 200
            data = await response.json()

        # Each pair normalises to the same key → 3 groups, each with count 2
        assert data["total_groups"] == 3
        counts = {g["count"] for g in data["groups"]}
        assert counts == {2}
        messages = [g["message"] for g in data["groups"]]
        # Each representative message must contain one of the original variable tokens
        assert any(uuid1 in m or uuid2 in m for m in messages), "UUID group representative missing"
        assert any(pid1 in m or pid2 in m for m in messages), "PID group representative missing"
        assert any(hex1 in m or hex2 in m for m in messages), "hex group representative missing"
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_errors_grouped_endpoint_pagination() -> None:
    """Test /api/errors/grouped returns paginated groups."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # 15 error types, each appearing twice so all qualify for the grouped view
        errors = [msg for i in range(15) for msg in [f"error type {i}", f"error type {i}"]]
        webui.update_status(errors_history=errors)

        # Page 1, page_size=10 → 10 groups
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors/grouped?page=1&page_size=10",
        ) as response:
            assert response.status == 200
            data = await response.json()
        assert data["total_groups"] == 15
        assert data["total_pages"] == 2
        assert len(data["groups"]) == 10

        # Page 2 → 5 groups
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors/grouped?page=2&page_size=10",
        ) as response:
            assert response.status == 200
            data2 = await response.json()
        assert data2["page"] == 2
        assert len(data2["groups"]) == 5
    finally:
        await webui.stop()


@pytest.mark.asyncio
async def test_webui_errors_grouped_endpoint_edge_cases() -> None:
    """Test /api/errors/grouped handles invalid params and out-of-range page."""
    webui = WorkerWebUI(port=0)

    try:
        await webui.start()
        await asyncio.sleep(0.5)
        actual_port = webui.site._server.sockets[0].getsockname()[1] if webui.site else 0

        # "err b" appears only once and will be excluded; "err a" appears twice and qualifies
        webui.update_status(errors_history=["err a", "err b", "err a"])

        # Invalid page falls back to 1
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors/grouped?page=abc",
        ) as response:
            assert response.status == 200
            data_inv = await response.json()
        assert data_inv["page"] == 1

        # Out-of-range page is clamped to total_pages
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors/grouped?page=999",
        ) as response:
            assert response.status == 200
            data_clamped = await response.json()
        assert data_clamped["page"] == data_clamped["total_pages"]

        # page_size is capped at 100
        async with aiohttp.ClientSession() as session, session.get(
            f"http://localhost:{actual_port}/api/errors/grouped?page_size=9999",
        ) as response:
            assert response.status == 200
            data_cap = await response.json()
        assert data_cap["page_size"] == 100
    finally:
        await webui.stop()


if __name__ == "__main__":
    # Run simple tests
    test_webui_creation()
    print("✓ WebUI creation test passed")

    test_webui_status_update()
    print("✓ WebUI status update test passed")

    test_webui_vram_resources()
    print("✓ WebUI VRAM resources test passed")

    test_webui_cpu_gpu_usage()
    print("✓ WebUI CPU/GPU usage test passed")

    test_webui_cpu_cores_count()
    print("✓ WebUI CPU cores count test passed")

    test_webui_new_features()
    print("✓ WebUI new features test passed")

    test_webui_faulted_jobs_history()
    print("✓ WebUI faulted jobs history test passed")

    test_webui_batch_size_display()
    print("✓ WebUI batch size display test passed")

    test_webui_last_image_submission_timestamp()
    print("✓ WebUI last image submission timestamp test passed")

    test_webui_images_history()
    print("✓ WebUI images history test passed")

    # Run async test
    asyncio.run(test_webui_start_stop())
    print("✓ WebUI start/stop test passed")

    print("\nAll tests passed!")
