"""Web server for the Horde Worker status UI."""

import base64
import io
import math
import time
from typing import Any

from aiohttp import web
from loguru import logger

try:
    from PIL import Image as _PILImage

    _PIL_AVAILABLE = True
except ImportError:
    _PILImage = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False
    logger.warning(
        "Pillow is not installed; gallery thumbnails will not be generated. "
        "Install the 'Pillow' package to enable thumbnail generation in the web UI.",
    )

_THUMBNAIL_MAX_PX = 256
"""Maximum pixel dimension (width or height) for gallery thumbnails."""


class WorkerWebUI:
    """Web UI server for displaying worker status and progress."""

    def __init__(self, port: int = 3000, update_interval: float = 1.0) -> None:
        """Initialize the web UI server.

        Args:
            port: The port to run the web server on (default: 3000)
            update_interval: How often to update status in seconds (default: 1.0)
        """
        self.port = port
        self.update_interval = update_interval
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None

        # Status data that will be updated by the worker
        self.status_data: dict[str, Any] = {
            "worker_name": "Unknown",
            "horde_username": "Unknown",
            "uptime": 0,
            "session_start_time": time.time(),
            "jobs_popped": 0,
            "jobs_queued": 0,
            "time_without_jobs": 0.0,
            "jobs_completed": 0,
            "jobs_faulted": 0,
            "processes_recovered": 0,
            "kudos_earned_session": 0.0,
            "kudos_per_hour": 0.0,
            "images_per_hour": 0.0,
            "current_job": None,
            "job_queue": [],
            "processes": [],
            "models_loaded": [],
            "ram_usage_mb": 0,
            "vram_usage_mb": 0,
            "total_vram_mb": 0,
            "cpu_usage_percent": 0,
            "cpu_cores_count": 0,
            "gpu_usage_percent": 0,
            "maintenance_mode": False,
            "user_kudos_total": 0.0,
            "last_image_base64": [],
            "last_image_submission_timestamp": 0.0,
            "console_logs": [],
            "faulted_jobs_history": [],
            "errors_history": [],
            "images_count": 0,
            "user_details": {},
        }

        # Gallery image data stored separately – NOT included in /api/status to avoid
        # sending large base64 payloads on every poll.  Served via /api/gallery instead.
        # Keyed by gallery_id (int) for O(1) lookup; insertion order is oldest-first.
        self._gallery_dict: dict[int, dict[str, Any]] = {}
        # Monotonically increasing counter used to assign stable gallery_id values.
        self._next_gallery_id: int = 0

        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up the web server routes."""
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/api/status", self._handle_status)
        self.app.router.add_get("/api/errors", self._handle_errors)
        self.app.router.add_get("/api/last_image", self._handle_last_image)
        self.app.router.add_get("/api/gallery", self._handle_gallery)
        self.app.router.add_get("/api/gallery/image", self._handle_gallery_image)
        self.app.router.add_get("/api/config", self._handle_config)
        self.app.router.add_get("/health", self._handle_health)

    async def _handle_config(self, request: web.Request) -> web.Response:
        """Handle config API request."""
        # Return update interval in milliseconds for JavaScript
        return web.json_response({"update_interval_ms": int(self.update_interval * 1000)})

    async def _handle_index(self, request: web.Request) -> web.Response:
        """Serve the main HTML page."""
        html = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Horde Worker Admin</title>
    <style>
        *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --sidebar-width: 260px;
            --sidebar-bg: #1a1d2e;
            --sidebar-hover: #2d3148;
            --accent: #6366f1;
            --accent-hover: #4f46e5;
            --success: #10b981;
            --warning: #f59e0b;
            --error: #ef4444;
            --text-muted: #94a3b8;
            --text-light: #e2e8f0;
            --main-bg: #f1f5f9;
            --card-bg: #ffffff;
            --border: #e2e8f0;
        }


        html { scroll-behavior: smooth; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--main-bg);
            color: #334155;
            min-height: 100vh;
            display: flex;
        }

        /* ---- Sidebar ---- */
        .sidebar {
            width: var(--sidebar-width);
            background: var(--sidebar-bg);
            position: fixed;
            top: 0; left: 0;
            height: 100vh;
            display: flex;
            flex-direction: column;
            z-index: 100;
            transition: transform 0.28s cubic-bezier(.4,0,.2,1);
            overflow-y: auto;
        }
        .sidebar-logo { padding: 22px 20px 18px; border-bottom: 1px solid rgba(255,255,255,0.07); flex-shrink: 0; }
        .sidebar-logo h1 { color: var(--text-light); font-size: 1.15rem; font-weight: 700; letter-spacing: 0.3px; }
        .sidebar-logo p { color: var(--text-muted); font-size: 0.75rem; margin-top: 3px; }
        .sidebar-nav { flex: 1; padding: 12px 0; }
        .nav-section-label { color: var(--text-muted); font-size: 0.67rem; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; padding: 10px 20px 4px; }
        .nav-item { display: flex; align-items: center; gap: 10px; padding: 9px 20px; color: var(--text-muted); font-size: 0.875rem; font-weight: 500; transition: background 0.15s, color 0.15s, border-color 0.15s; cursor: pointer; border-left: 3px solid transparent; user-select: none; background: none; border-top: none; border-right: none; border-bottom: none; width: 100%; text-align: left; }
        .nav-item:hover { background: var(--sidebar-hover); color: var(--text-light); }
        .nav-item.active { background: var(--sidebar-hover); color: var(--text-light); border-left-color: var(--accent); }
        .nav-icon { font-size: 1rem; width: 18px; text-align: center; flex-shrink: 0; }
        .sidebar-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 99; backdrop-filter: blur(1px); }
        .sidebar-overlay.active { display: block; }

        /* ---- Mobile navbar ---- */
        .mobile-navbar { display: none; position: fixed; top: 0; left: 0; right: 0; height: 54px; background: var(--sidebar-bg); align-items: center; padding: 0 14px; z-index: 200; gap: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.25); }
        .hamburger-btn { background: none; border: none; color: var(--text-light); font-size: 1.3rem; cursor: pointer; padding: 6px; border-radius: 6px; line-height: 1; transition: background 0.15s; }
        .hamburger-btn:hover { background: rgba(255,255,255,0.08); }
        .mobile-title { color: var(--text-light); font-size: 0.95rem; font-weight: 600; flex: 1; }
        .mobile-uptime { color: var(--text-muted); font-size: 0.7rem; font-family: 'Courier New', monospace; white-space: nowrap; flex-shrink: 0; }

        /* ---- Mobile resources sub-bar ---- */
        .mobile-resources { display: none; position: fixed; top: 54px; left: 0; right: 0; height: 26px; background: #12162a; align-items: center; padding: 0 14px; gap: 14px; z-index: 199; border-bottom: 1px solid rgba(255,255,255,0.06); }
        .mobile-res-chip { color: var(--text-muted); font-size: 0.7rem; font-weight: 600; font-family: 'Courier New', monospace; }

        /* ---- Main content ---- */
        .main-content { margin-left: var(--sidebar-width); flex: 1; min-height: 100vh; display: flex; flex-direction: column; min-width: 0; }

        /* ---- Top bar ---- */
        .topbar { background: white; border-bottom: 1px solid var(--border); padding: 14px 24px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; flex-shrink: 0; }
        .topbar-worker { flex: 1; min-width: 0; }
        .topbar-worker-name { font-size: 1.15rem; font-weight: 700; color: #1e293b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .topbar-worker-sub { font-size: 0.82rem; color: #64748b; margin-top: 2px; }
        .topbar-meta { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .topbar-uptime { font-size: 0.82rem; color: #64748b; }

        /* ---- Status badges ---- */
        .status-badge { display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px; }
        .status-badge::before { content: ''; width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
        .status-active { background: #d1fae5; color: #065f46; }
        .status-active::before { background: #10b981; }
        .status-maintenance { background: #fef3c7; color: #92400e; }
        .status-maintenance::before { background: #f59e0b; animation: pulse-dot 1.5s ease-in-out infinite; }
        @keyframes pulse-dot { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

        .content-area { padding: 22px 24px; flex: 1; }

        /* ---- Page (SPA) ---- */
        .page { display: none; }
        .page.active { display: block; }

        .section { margin-bottom: 30px; }
        .section-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
        .section-title { font-size: 0.82rem; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 1px; }
        .section-count { background: #e2e8f0; color: #475569; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 20px; }

        .card { background: var(--card-bg); border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.04); border: 1px solid var(--border); }
        .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9; }
        .card-title { font-size: 0.8rem; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.8px; display: flex; align-items: center; gap: 7px; }

        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
        .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
        .grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }

        .stat-card { background: var(--card-bg); border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.07); border: 1px solid var(--border); }
        .stat-card-label { font-size: 0.75rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }
        .stat-card-value { font-size: 1.7rem; font-weight: 700; color: #1e293b; line-height: 1; }
        .stat-card-value.success { color: var(--success); }
        .stat-card-value.warning { color: var(--warning); }
        .stat-card-value.error   { color: var(--error); }
        .stat-card-value.accent  { color: var(--accent); }

        .stat-row { display: flex; justify-content: space-between; align-items: center; padding: 9px 0; border-bottom: 1px solid #f8fafc; }
        .stat-row:last-child { border-bottom: none; }
        .stat-label { color: #64748b; font-size: 0.85rem; font-weight: 500; }
        .stat-value { color: #1e293b; font-weight: 600; font-size: 0.9rem; text-align: right; max-width: 62%; word-break: break-word; }
        .stat-value.success { color: var(--success); }
        .stat-value.warning { color: var(--warning); }
        .stat-value.error   { color: var(--error); }

        .progress-section { margin-bottom: 14px; }
        .progress-section:last-child { margin-bottom: 0; }
        .progress-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; }
        .progress-label { font-size: 0.83rem; font-weight: 500; color: #475569; }
        .progress-value { font-size: 0.83rem; font-weight: 700; color: #1e293b; }
        .progress-bar-container { width: 100%; height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; }
        .progress-bar { height: 100%; background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%); border-radius: 4px; transition: width 0.4s ease; min-width: 0; }

        .job-state-badge { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; background: #e0e7ff; color: #4338ca; }

        .process-item { background: #f8fafc; border: 1px solid #e8eef4; border-left: 3px solid var(--accent); border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; }
        .process-item:last-child { margin-bottom: 0; }
        .process-id-row { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-bottom: 3px; }
        .process-id { font-weight: 700; color: var(--accent); font-size: 0.88rem; }
        .process-type-badge { font-size: 0.72rem; background: #e0e7ff; color: #4338ca; padding: 1px 7px; border-radius: 4px; font-weight: 600; }
        .process-state-badge { font-size: 0.72rem; background: #f0fdf4; color: #166534; padding: 1px 7px; border-radius: 4px; font-weight: 600; }
        .process-detail-text { font-size: 0.8rem; color: #64748b; }

        .job-item { background: #f8fafc; border: 1px solid #e8eef4; border-radius: 7px; padding: 7px 12px; margin-bottom: 5px; font-size: 0.83rem; }
        .job-item:last-child { margin-bottom: 0; }
        .job-id { font-family: 'Courier New', monospace; color: var(--accent); font-weight: 600; font-size: 0.8rem; }

        .model-list { display: flex; flex-wrap: wrap; gap: 6px; }
        .model-badge { background: #e0e7ff; color: #4338ca; padding: 4px 10px; border-radius: 6px; font-size: 0.78rem; font-weight: 500; }

        .console-container { background: #0f172a; border-radius: 8px; padding: 12px 14px; max-height: 400px; overflow-y: auto; font-family: 'Courier New', Consolas, 'Lucida Console', monospace; font-size: 0.8rem; color: #e2e8f0; line-height: 1.55; }
        .console-pause-btn { margin-left: auto; background: #e2e8f0; color: #475569; border: none; border-radius: 6px; padding: 3px 10px; font-size: 0.75rem; font-weight: 600; cursor: pointer; transition: background 0.15s, color 0.15s; }
        .console-pause-btn:hover { background: #cbd5e1; }
        .console-pause-btn.paused { background: var(--accent); color: #fff; }
        .console-pause-btn.paused:hover { background: var(--accent-hover); }

        /* ---- Gallery ---- */
        .image-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; width: 100%; }
        .image-grid-item { position: relative; overflow: hidden; border-radius: 8px; background: #f1f5f9; aspect-ratio: 1; display: flex; align-items: center; justify-content: center; }
        .image-grid-item img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 8px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; display: block; }
        .image-grid-item img:hover { transform: scale(1.04); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .image-grid-item .image-timestamp { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.6); color: #e2e8f0; font-size: 0.65rem; padding: 3px 6px; text-align: center; border-radius: 0 0 8px 8px; opacity: 0; transition: opacity 0.2s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .image-grid-item:hover .image-timestamp { opacity: 1; }
        @keyframes gallery-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
        .image-grid-item.loading { background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%); background-size: 200% 100%; animation: gallery-shimmer 1.5s infinite; }
        [data-theme="dark"] .image-grid-item.loading { background: linear-gradient(90deg, #1e293b 25%, #2d3f55 50%, #1e293b 75%); background-size: 200% 100%; animation: gallery-shimmer 1.5s infinite; }

        .last-image-container { display: flex; align-items: center; justify-content: center; border-radius: 8px; height: 320px; overflow: hidden; }
        .last-image-container.loading { background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%); background-size: 200% 100%; animation: gallery-shimmer 1.5s infinite; }
        [data-theme="dark"] .last-image-container.loading { background: linear-gradient(90deg, #1e293b 25%, #2d3f55 50%, #1e293b 75%); background-size: 200% 100%; animation: gallery-shimmer 1.5s infinite; }
        @media (prefers-reduced-motion: reduce) { .last-image-container.loading { animation: none; background: #e2e8f0; background-size: auto; } [data-theme="dark"] .last-image-container.loading { animation: none; background: #1e293b; background-size: auto; } }
        .last-image-container > .image-grid-item { aspect-ratio: auto; min-height: 0; height: 100%; display: flex; align-items: center; justify-content: center; overflow: hidden; }
        .last-image-container .image-grid-item img { max-width: 100%; height: 100%; max-height: 100%; object-fit: contain; border-radius: 4px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; display: block; }
        .last-image-container .image-grid-item img:hover { transform: scale(1.02); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .single-image { max-width: 100%; max-height: 100%; width: auto; height: auto; object-fit: contain; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); display: block; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; }
        .single-image:hover { transform: scale(1.02); box-shadow: 0 4px 16px rgba(0,0,0,0.18); }

        /* ---- Image overlay ---- */
        .image-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 1000; justify-content: center; align-items: center; padding: 20px; }
        .image-overlay.active { display: flex; }
        .image-overlay-content { position: relative; max-width: 95%; max-height: 95%; display: flex; justify-content: center; align-items: center; }
        .image-overlay img { max-width: 100%; max-height: 90vh; object-fit: contain; border-radius: 8px; box-shadow: 0 8px 40px rgba(0,0,0,0.6); transition: opacity 0.2s ease; }
        .image-overlay-close { position: absolute; top: -44px; right: 0; background: var(--accent); color: white; border: none; padding: 8px 18px; font-size: 0.9rem; font-weight: 600; border-radius: 8px; cursor: pointer; transition: background 0.2s; }
        .image-overlay-close:hover { background: var(--accent-hover); }
        .image-overlay-nav { position: fixed; top: 50%; transform: translateY(-50%); background: rgba(0,0,0,0.5); color: white; border: none; padding: 12px 18px; font-size: 1.8rem; font-weight: 700; border-radius: 8px; cursor: pointer; transition: background 0.2s; z-index: 1001; user-select: none; line-height: 1; display: none; }
        .image-overlay-nav:hover { background: rgba(0,0,0,0.85); }
        .image-overlay-nav:disabled { opacity: 0.3; cursor: default; }
        .image-overlay-nav.prev { left: 12px; }
        .image-overlay-nav.next { right: 12px; }
        .image-overlay-counter { position: absolute; bottom: -32px; left: 50%; transform: translateX(-50%); color: rgba(255,255,255,0.8); font-size: 0.85rem; white-space: nowrap; font-weight: 500; }

        /* ---- Errors ---- */
        .errors-list { display: flex; flex-direction: column; max-height: 400px; overflow-y: auto; }
        .error-item { background: #fff5f5; border: 1px solid #fecaca; border-left: 3px solid var(--error); border-radius: 6px; padding: 9px 13px; font-family: 'Courier New', monospace; font-size: 0.78rem; color: #7f1d1d; white-space: pre-wrap; word-break: break-word; margin-bottom: 5px; }
        .error-item:last-child { margin-bottom: 0; }

        .pagination-controls { display: flex; align-items: center; justify-content: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
        .pagination-controls button { background: var(--accent); color: white; border: none; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 0.82rem; font-weight: 500; transition: background 0.15s; }
        .pagination-controls button:hover:not(:disabled) { background: var(--accent-hover); }
        .pagination-controls button:disabled { background: #c7d2fe; cursor: default; }
        .pagination-info { font-size: 0.82rem; color: var(--text-muted); }
        .page-size-select { font-size: 0.82rem; color: inherit; background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; cursor: pointer; transition: border-color 0.15s; }
        .page-size-select:focus-visible { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(99,102,241,0.35); }

        .scrollable { max-height: 260px; overflow-y: auto; }
        .scrollable-tall { max-height: 400px; overflow-y: auto; }

        #loading { display: flex; align-items: center; justify-content: center; height: 80vh; flex-direction: column; gap: 14px; }
        .loading-spinner { width: 36px; height: 36px; border: 3px solid #e2e8f0; border-top-color: var(--accent); border-radius: 50%; animation: spin 0.75s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .loading-text { color: #64748b; font-size: 0.9rem; }

        .empty-state { text-align: center; padding: 24px 16px; color: #94a3b8; font-size: 0.87rem; }
        .empty-state-icon { font-size: 1.8rem; margin-bottom: 6px; display: block; }
        .centered-empty-container { display: flex; align-items: center; justify-content: center; min-height: 320px; }

        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

        @media (max-width: 1200px) { .grid-4 { grid-template-columns: repeat(2, 1fr); } .grid-3 { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 768px) { .sidebar { transform: translateX(-100%); top: 80px; height: calc(100vh - 80px); } .sidebar.open { transform: translateX(0); } .mobile-navbar { display: flex; } .mobile-resources { display: flex; } .main-content { margin-left: 0; padding-top: 80px; } .topbar { display: none; } .content-area { padding: 14px 12px; } .grid-4 { grid-template-columns: repeat(2, 1fr); } .grid-3 { grid-template-columns: 1fr; } .grid-2 { grid-template-columns: 1fr; } .grid-3-popped { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 480px) { .grid-4 { grid-template-columns: repeat(2, 1fr); gap: 10px; } .stat-card-value { font-size: 1.4rem; } }

        /* ---- Theme toggle (square) ---- */
        .theme-toggle { background: none; border: 1px solid rgba(255,255,255,0.18); color: var(--text-light); font-size: 1rem; cursor: pointer; padding: 5px 9px; border-radius: 4px; line-height: 1; transition: background 0.15s; flex-shrink: 0; }
        .theme-toggle:hover { background: rgba(255,255,255,0.08); }
        .topbar .theme-toggle { background: none; border: 1px solid #e2e8f0; color: #475569; }
        .topbar .theme-toggle:hover { background: #f1f5f9; }

        /* ---- Topbar resource pills with bars ---- */
        .topbar-resources { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .topbar-res-pill { background: #f1f5f9; border: 1px solid #e2e8f0; color: #475569; font-size: 0.72rem; font-weight: 600; padding: 4px 10px; border-radius: 8px; white-space: nowrap; display: flex; flex-direction: column; gap: 3px; min-width: 80px; }
        .topbar-res-pill-label { display: flex; justify-content: space-between; align-items: center; font-family: 'Courier New', monospace; }
        .topbar-res-bar-track { width: 100%; height: 4px; background: #cbd5e1; border-radius: 2px; overflow: hidden; }
        .topbar-res-bar { height: 100%; border-radius: 2px; transition: width 0.4s ease, background-color 0.4s ease; }
        /* ---- Dark mode ---- */
        [data-theme="dark"] { --main-bg: #0f172a; --card-bg: #1e293b; --border: #2d3f55; --sidebar-bg: #0d1117; --sidebar-hover: #161e2e; }
        [data-theme="dark"] body { color: #cbd5e1; }
        [data-theme="dark"] .topbar { background: #1e293b; border-bottom-color: #2d3f55; }
        [data-theme="dark"] .topbar-worker-name { color: #f1f5f9; }
        [data-theme="dark"] .topbar-worker-sub, [data-theme="dark"] .topbar-uptime { color: #94a3b8; }
        [data-theme="dark"] .topbar .theme-toggle { border-color: #2d3f55; color: #94a3b8; }
        [data-theme="dark"] .topbar .theme-toggle:hover { background: #2d3f55; }
        [data-theme="dark"] .topbar-res-pill { background: #151e2e; border-color: #2d3f55; color: #94a3b8; }
        [data-theme="dark"] .topbar-res-bar-track { background: #2d3f55; }
        [data-theme="dark"] .stat-card-value:not(.success):not(.accent):not(.warning):not(.error) { color: #f1f5f9; }
        [data-theme="dark"] .stat-card-value.success { color: #34d399; }
        [data-theme="dark"] .stat-card-value.accent  { color: #818cf8; }
        [data-theme="dark"] .stat-card-value.warning { color: #fbbf24; }
        [data-theme="dark"] .stat-card-value.error   { color: #f87171; }
        [data-theme="dark"] .stat-card-label { color: #94a3b8; }
        [data-theme="dark"] .stat-label { color: #94a3b8; }
        [data-theme="dark"] .stat-value { color: #f1f5f9; }
        [data-theme="dark"] .stat-row { border-bottom-color: #2d3f55; }
        [data-theme="dark"] .card-header { border-bottom-color: #2d3f55; }
        [data-theme="dark"] .card-title { color: #94a3b8; }
        [data-theme="dark"] .progress-label { color: #94a3b8; }
        [data-theme="dark"] .progress-value { color: #f1f5f9; }
        [data-theme="dark"] .progress-bar-container { background: #2d3f55; }
        [data-theme="dark"] .section-title { color: #94a3b8; }
        [data-theme="dark"] .section-count { background: #2d3f55; color: #94a3b8; }
        [data-theme="dark"] .process-item { background: #151e2e; border-color: #2d3f55; }
        [data-theme="dark"] .process-type-badge { background: #312e81; color: #a5b4fc; }
        [data-theme="dark"] .process-state-badge { background: #14532d; color: #86efac; }
        [data-theme="dark"] .process-detail-text { color: #94a3b8; }
        [data-theme="dark"] .job-item { background: #151e2e; border-color: #2d3f55; }
        [data-theme="dark"] .model-badge { background: #312e81; color: #a5b4fc; }
        [data-theme="dark"] .job-state-badge { background: #312e81; color: #a5b4fc; }
        [data-theme="dark"] .loading-text { color: #94a3b8; }
        [data-theme="dark"] .loading-spinner { border-color: #2d3f55; border-top-color: var(--accent); }
        [data-theme="dark"] .empty-state { color: #64748b; }
        [data-theme="dark"] .image-grid-item { background: #151e2e; }
        [data-theme="dark"] .page-size-select { color: #cbd5e1; }
        [data-theme="dark"] .error-item { background: #1a1010; border-color: #7f1d1d; color: #fca5a5; }

        /* ---- Worker cards (User page) ---- */
        .worker-card { background: var(--card-bg); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; }
        .worker-card:last-child { margin-bottom: 0; }
        .worker-card-header { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
        .worker-card-name { font-weight: 700; color: var(--accent); font-size: 0.95rem; flex-shrink: 0; }
        .worker-version-badge { font-size: 0.68rem; background: #e0e7ff; color: #4338ca; padding: 2px 7px; border-radius: 4px; font-weight: 600; font-family: 'Courier New', monospace; }
        .worker-type-badge { font-size: 0.68rem; background: #f0fdf4; color: #166534; padding: 2px 7px; border-radius: 4px; font-weight: 600; text-transform: capitalize; }
        .worker-online-badge { font-size: 0.68rem; padding: 2px 7px; border-radius: 4px; font-weight: 600; margin-left: auto; }
        .worker-online-badge.online { background: #dcfce7; color: #166534; }
        .worker-online-badge.offline { background: #fee2e2; color: #991b1b; }
        .worker-caps-row { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }
        .wcap { font-size: 0.68rem; padding: 2px 8px; border-radius: 4px; font-weight: 600; }
        .wcap-yes { background: #dcfce7; color: #166534; }
        .wcap-no { background: #f1f5f9; color: #64748b; }
        .wcap-nsfw { background: #fef3c7; color: #92400e; }
        .wcap-sfw { background: #f1f5f9; color: #64748b; }
        .worker-meta-row { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; font-size: 0.82rem; color: #475569; }
        .wm-item { display: flex; align-items: center; gap: 4px; }
        .models-pill { cursor: default; text-decoration: underline dotted; position: relative; }
        .models-pill[data-tooltip]:not([data-tooltip=""]):hover::after { content: attr(data-tooltip); white-space: normal; overflow-wrap: anywhere; position: absolute; bottom: calc(100% + 4px); left: 0; background: #334155; color: #f1f5f9; padding: 6px 10px; border-radius: 6px; font-size: 0.78rem; line-height: 1.5; z-index: 1000; pointer-events: none; box-shadow: 0 2px 8px rgba(0,0,0,0.3); border: 1px solid #475569; min-width: 140px; max-width: min(90vw, 480px); }
        [data-theme="dark"] .models-pill[data-tooltip]:not([data-tooltip=""]):hover::after { background: #1e293b; border-color: #334155; }
        .worker-stats-row { display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.82rem; color: #64748b; border-top: 1px solid var(--border); padding-top: 8px; margin-top: 2px; }
        .ws-item { display: flex; align-items: center; gap: 4px; }
        .ws-item.accent { color: var(--accent); font-weight: 600; }
        [data-theme="dark"] .worker-version-badge { background: #312e81; color: #a5b4fc; }
        [data-theme="dark"] .worker-type-badge { background: #14532d; color: #86efac; }
        [data-theme="dark"] .worker-online-badge.online { background: #14532d; color: #86efac; }
        [data-theme="dark"] .worker-online-badge.offline { background: #450a0a; color: #fca5a5; }
        [data-theme="dark"] .wcap-yes { background: #14532d; color: #86efac; }
        [data-theme="dark"] .wcap-no { background: #1e293b; color: #64748b; }
        [data-theme="dark"] .wcap-nsfw { background: #451a03; color: #fcd34d; }
        [data-theme="dark"] .wcap-sfw { background: #1e293b; color: #64748b; }
        [data-theme="dark"] .worker-meta-row { color: #94a3b8; }
        [data-theme="dark"] .worker-stats-row { color: #94a3b8; }
        [data-theme="dark"] .worker-card { background: #151e2e; border-color: #2d3f55; }

        /* ---- Gallery new-images banner ---- */
        #gallery-new-banner { display: none; background: #dbeafe; border: 1px solid #93c5fd; border-radius: 8px; padding: 8px 14px; margin-bottom: 12px; cursor: pointer; font-size: 0.85rem; font-weight: 500; color: #1d4ed8; }
        [data-theme="dark"] #gallery-new-banner { background: #1e3a5f; border-color: #2d5fa0; color: #93c5fd; }

    </style>
</head>
<body>
    <nav class="mobile-navbar" aria-label="Mobile navigation">
        <button class="hamburger-btn" onclick="toggleSidebar()" aria-label="Toggle sidebar">&#9776;</button>
        <span class="mobile-title">&#127912; Horde Worker</span>
        <span id="mobile-status-badge"></span>
        <span class="mobile-uptime" id="mobile-uptime">&#9201; --</span>
        <button class="theme-toggle" onclick="toggleTheme()" id="mobile-theme-toggle" aria-label="Toggle theme">&#127769;</button>
    </nav>
    <div class="mobile-resources" aria-label="Resource usage">
        <span class="mobile-res-chip" id="mobile-cpu">CPU 0%</span>
        <span class="mobile-res-chip" id="mobile-gpu">GPU 0%</span>
        <span class="mobile-res-chip" id="mobile-vram">VRAM 0%</span>
    </div>
    <div class="sidebar-overlay" id="sidebar-overlay" onclick="closeSidebar()"></div>
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-logo">
            <h1>&#127912; Horde Worker</h1>
            <p>AI Image Generation</p>
        </div>
        <nav class="sidebar-nav" aria-label="Page navigation">
            <div class="nav-section-label">Navigation</div>
            <button class="nav-item active" onclick="showPage('overview', this)" id="nav-overview">
                <span class="nav-icon">&#128202;</span> Overview
            </button>
            <button class="nav-item" onclick="showPage('gallery', this)" id="nav-gallery">
                <span class="nav-icon">&#128444;</span> Gallery
            </button>
            <button class="nav-item" onclick="showPage('user', this)" id="nav-user">
                <span class="nav-icon">&#128100;</span> User
            </button>
            <button class="nav-item" onclick="showPage('logs', this)" id="nav-logs">
                <span class="nav-icon">&#128203;</span> Logs
            </button>
        </nav>
    </aside>
    <div class="main-content">
        <div class="topbar">
            <div class="topbar-worker">
                <div class="topbar-worker-name" id="topbar-worker-name">Horde Worker</div>
                <div class="topbar-worker-sub" id="topbar-worker-sub">Loading...</div>
            </div>
            <div class="topbar-resources">
                <div class="topbar-res-pill">
                    <div class="topbar-res-pill-label"><span>CPU</span><span id="topbar-cpu-pct">0%</span></div>
                    <div class="topbar-res-bar-track"><div class="topbar-res-bar cpu" id="topbar-cpu-bar" style="width:0%"></div></div>
                </div>
                <div class="topbar-res-pill">
                    <div class="topbar-res-pill-label"><span>GPU</span><span id="topbar-gpu-pct">0%</span></div>
                    <div class="topbar-res-bar-track"><div class="topbar-res-bar gpu" id="topbar-gpu-bar" style="width:0%"></div></div>
                </div>
                <div class="topbar-res-pill">
                    <div class="topbar-res-pill-label"><span id="topbar-vram-label">VRAM</span><span id="topbar-vram-pct">0%</span></div>
                    <div class="topbar-res-bar-track"><div class="topbar-res-bar vram" id="topbar-vram-bar" style="width:0%"></div></div>
                </div>
            </div>
            <div class="topbar-meta">
                <span id="worker-status-badge"></span>
                <span class="topbar-uptime">&#9201; <span id="uptime">--</span></span>
                <button class="theme-toggle" onclick="toggleTheme()" id="topbar-theme-toggle" aria-label="Toggle theme">&#127769;</button>
            </div>
        </div>
        <div class="content-area">
            <div id="loading"><div class="loading-spinner"></div><span class="loading-text">Connecting to worker...</span></div>
            <div id="content" style="display: none;">
                <!-- OVERVIEW PAGE -->
                <div class="page active" id="page-overview">
                    <div class="grid-4" style="margin-bottom: 14px;">
                        <div class="stat-card"><div class="stat-card-label">Total Kudos</div><div class="stat-card-value success" id="user-kudos-total">-</div></div>
                        <div class="stat-card"><div class="stat-card-label">Images / Hour</div><div class="stat-card-value accent" id="images-per-hour">0</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Popped</div><div class="stat-card-value accent" id="jobs-popped">0</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Completed</div><div class="stat-card-value success" id="jobs-completed">0</div></div>
                    </div>
                    <div class="grid-4" style="margin-bottom: 14px;">
                        <div class="stat-card"><div class="stat-card-label">Total Time without Jobs</div><div class="stat-card-value warning" id="time-without-jobs">0h 0m 0s</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Queued</div><div class="stat-card-value" id="jobs-queued">0</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Recovered</div><div class="stat-card-value warning" id="processes-recovered">0</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Faulted</div><div class="stat-card-value error" id="jobs-faulted">0</div></div>
                    </div>
                    <div class="grid-2" style="margin-bottom: 14px;">
                        <div class="card">
                            <div class="card-header"><span class="card-title">&#9889; Current Job</span></div>
                            <div id="overview-current-job" class="centered-empty-container"><div class="empty-state"><span class="empty-state-icon">&#9203;</span>No job in progress</div></div>
                        </div>
                        <div class="card">
                            <div class="card-header"><span class="card-title">&#128444; Last Result</span><span id="overview-image-time" style="margin-left:auto;font-size:0.75rem;color:#94a3b8;"></span></div>
                            <div id="overview-image-container" class="last-image-container"><div class="empty-state"><span class="empty-state-icon">&#128444;</span>No image generated yet</div></div>
                        </div>
                    </div>
                    <div class="grid-2">
                        <div class="card">
                            <div class="card-header"><span class="card-title">&#9881; Processes</span><span class="section-count" id="process-count">0</span></div>
                            <div id="processes" class="scrollable-tall"><div class="empty-state"><span class="empty-state-icon">&#9881;</span>No process info</div></div>
                        </div>
                        <div class="card">
                            <div class="card-header"><span class="card-title">&#128230; Job Queue &amp; Models</span></div>
                            <div style="margin-bottom: 14px;">
                                <div style="font-size:0.75rem;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:7px;">Queue (<span id="queue-count">0</span>)</div>
                                <div id="job-queue" class="scrollable"><div class="empty-state">Queue is empty</div></div>
                            </div>
                            <div>
                                <div style="font-size:0.75rem;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:7px;">Active Models</div>
                                <div id="models-loaded" class="model-list"><span style="color:#94a3b8;font-size:0.83rem;">No models loaded</span></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- GALLERY PAGE -->
                <div class="page" id="page-gallery">
                    <div class="section">
                        <div class="section-header"><span class="section-title">&#128444; Gallery</span><span class="section-count" id="gallery-count">0</span></div>
                        <div class="card">
                            <div id="gallery-new-banner" role="button" tabindex="0" onclick="fetchGalleryPage(1)" onkeydown="if(event.key==='Enter'||event.key===' '){fetchGalleryPage(1);event.preventDefault();}">&#128444; New images available &#8212; click to view latest</div>
                            <div id="gallery-loading" style="display:none;text-align:center;padding:24px 16px;"><div class="loading-spinner" style="margin:0 auto 8px;"></div><span class="loading-text">Loading gallery&#8230;</span></div>
                            <div id="gallery-empty" class="empty-state" style="display:none;"><span class="empty-state-icon">&#128444;</span>No images generated yet</div>
                            <div id="gallery-grid" class="image-grid" style="display:none;"></div>
                            <div class="pagination-controls" id="gallery-pagination" style="display:none;">
                                <button id="gallery-prev" onclick="galleryChangePage(-1)" disabled>&#8249; Prev</button>
                                <span class="pagination-info" id="gallery-page-info">Page 1 of 1</span>
                                <button id="gallery-next" onclick="galleryChangePage(1)">Next &#8250;</button>
                                <label for="gallery-page-size" class="pagination-info">Per page:</label>
                                <select id="gallery-page-size" class="page-size-select" onchange="galleryChangePageSize(this.value)">
                                    <option value="12">12</option>
                                    <option value="24">24</option>
                                    <option value="48">48</option>
                                    <option value="96">96</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- USER PAGE -->
                <div class="page" id="page-user">
                    <div class="section">
                        <div class="section-header"><span class="section-title">&#128100; User Details</span></div>
                        <div class="grid-4" style="margin-bottom: 14px;">
                            <div class="stat-card"><div class="stat-card-label">Username</div><div class="stat-card-value" id="user-page-username">-</div></div>
                            <div class="stat-card"><div class="stat-card-label">Total Kudos</div><div class="stat-card-value success" id="user-page-kudos-total">-</div></div>
                            <div class="stat-card"><div class="stat-card-label">Kudos / Hour</div><div class="stat-card-value accent" id="user-page-kudos-per-hour">0</div></div>
                            <div class="stat-card"><div class="stat-card-label">Kudos This Session</div><div class="stat-card-value accent" id="user-page-kudos-session">0</div></div>
                        </div>
                        <div class="grid-4" style="margin-bottom: 14px;">
                            <div class="stat-card"><div class="stat-card-label">Images / Hour</div><div class="stat-card-value accent" id="user-page-images-per-hour">0</div></div>
                            <div class="stat-card"><div class="stat-card-label">Jobs Completed</div><div class="stat-card-value success" id="user-page-jobs-completed">0</div></div>
                            <div class="stat-card"><div class="stat-card-label">Trusted</div><div class="stat-card-value" id="user-page-trusted">-</div></div>
                            <div class="stat-card"><div class="stat-card-label">Worker Count</div><div class="stat-card-value" id="user-page-worker-count">-</div></div>
                        </div>
                        <div class="card">
                            <div class="card-header"><span class="card-title">&#127881; Kudos Breakdown</span></div>
                            <div id="user-page-kudos-breakdown"></div>
                        </div>
                    </div>
                    <div class="section">
                        <div class="section-header"><span class="section-title">&#9881; Workers</span><span class="section-count" id="user-workers-count">0</span></div>
                        <div id="user-workers-list"><div class="empty-state"><span class="empty-state-icon">&#9881;</span>No worker data yet</div></div>
                    </div>
                </div>

                <!-- LOGS PAGE -->
                <div class="page" id="page-logs">
                    <div class="section">
                        <div class="section-header"><span class="section-title">&#128203; Console</span><button id="console-pause-btn" class="console-pause-btn" onclick="toggleConsolePause()" title="Pause console output" aria-pressed="false">&#9646;&#9646; Pause</button></div>
                        <div class="card" style="padding:0;overflow:hidden;">
                            <div id="console-logs" class="console-container" style="border-radius:12px;"><div style="text-align:center;color:#475569;padding:18px;">No logs available</div></div>
                        </div>
                    </div>
                    <div class="section">
                        <div class="section-header"><span class="section-title">&#10060; Errors</span><span class="section-count" id="errors-count">0</span></div>
                        <div class="card">
                            <div id="errors-history" class="errors-list"><div class="empty-state"><span class="empty-state-icon">&#10003;</span>No errors</div></div>
                            <div class="pagination-controls" id="errors-pagination" style="display:none;">
                                <button id="errors-prev" onclick="errorsChangePage(-1)" disabled>&#8249; Prev</button>
                                <span class="pagination-info" id="errors-page-info">Page 1 of 1</span>
                                <button id="errors-next" onclick="errorsChangePage(1)">Next &#8250;</button>
                            </div>
                        </div>
                    </div>
                </div>

            </div>
        </div>
    </div>
    <div id="image-overlay" class="image-overlay">
        <button id="overlay-prev" class="image-overlay-nav prev" onclick="overlayNavigate(-1)" aria-label="Previous image" title="Previous image">&#8249;</button>
        <div class="image-overlay-content">
            <button class="image-overlay-close" onclick="closeImageOverlay()">&#10005; Close</button>
            <img id="overlay-image" src="" alt="Full resolution image" />
            <div id="overlay-counter" class="image-overlay-counter"></div>
        </div>
        <button id="overlay-next" class="image-overlay-nav next" onclick="overlayNavigate(1)" aria-label="Next image" title="Next image">&#8250;</button>
    </div>
    <script>
        function toggleSidebar() { document.getElementById('sidebar').classList.toggle('open'); document.getElementById('sidebar-overlay').classList.toggle('active'); }
        function closeSidebar() { document.getElementById('sidebar').classList.remove('open'); document.getElementById('sidebar-overlay').classList.remove('active'); }
        function escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }
        const VALID_PAGES = Object.freeze(['overview', 'gallery', 'user', 'horde', 'logs']);
        let galleryCurrentPage = 1, galleryTotalPages = 1, galleryTotalImages = 0, galleryFetchInProgress = false;
        let cachedWorkersList = (function() { try { var s = localStorage.getItem('horde-workers-list'); var parsed = s ? JSON.parse(s) : []; return Array.isArray(parsed) ? parsed : []; } catch(e) { return []; } })();
        function renderWorkersList() {
            const workersList = Array.isArray(cachedWorkersList) ? cachedWorkersList : [];
            document.getElementById('user-workers-count').textContent = workersList.length;
            const wlEl = document.getElementById('user-workers-list');
            if (workersList.length === 0) {
                wlEl.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#9881;</span>No worker data yet</div>';
            } else {
                wlEl.innerHTML = workersList.map(function(w) {
                    const onlineCls = w.online ? 'online' : 'offline';
                    const onlineTxt = w.online ? 'Online' : 'Offline';
                    const capBadge = function(val, label) {
                        if (val === null || val === undefined) return '';
                        return '<span class="wcap '+(val?'wcap-yes':'wcap-no')+'">'+escapeHtml(label)+'</span>';
                    };
                    const nsfwBadge = w.nsfw === true ? '<span class="wcap wcap-nsfw">NSFW</span>' : (w.nsfw === false ? '<span class="wcap wcap-sfw">SFW</span>' : '');
                    const caps = nsfwBadge +
                        capBadge(w.trusted, 'Trusted') +
                        capBadge(w.img2img, 'img2img') +
                        capBadge(w.painting, 'Painting') +
                        capBadge(w.lora, 'LoRA');
                    const models = w.models || [];
                    const modelCount = models.length;
                    const modelTitles = models.join(', ');
                    const sizeStr = w.max_pixels ? ('\u2248'+Math.round(Math.sqrt(w.max_pixels))+'px') : '-';
                    const uptimeSecs = w.uptime || 0;
                    const uh = Math.floor(uptimeSecs/3600), um = Math.floor((uptimeSecs%3600)/60);
                    const uptimeStr = uh > 0 ? uh+'h '+um+'m' : (um > 0 ? um+'m' : uptimeSecs+'s');
                    const kudos = w.kudos_rewards != null ? Number(w.kudos_rewards).toLocaleString(undefined,{maximumFractionDigits:0}) : '-';
                    const kph = (w.kudos_rewards != null && uptimeSecs > 0)
                        ? (w.kudos_rewards / (uptimeSecs / 3600)).toLocaleString(undefined, {maximumFractionDigits:1})
                        : '-';
                    return '<div class="worker-card">' +
                        '<div class="worker-card-header">' +
                        '<span class="worker-card-name">'+escapeHtml(w.name||'Unknown')+'</span>' +
                        (w.version ? '<span class="worker-version-badge">v'+escapeHtml(w.version)+'</span>' : '') +
                        (w.type ? '<span class="worker-type-badge">'+escapeHtml(w.type)+'</span>' : '') +
                        '<span class="worker-online-badge '+onlineCls+'">'+onlineTxt+'</span>' +
                        '</div>' +
                        (caps ? '<div class="worker-caps-row">'+caps+'</div>' : '') +
                        '<div class="worker-meta-row">' +
                        '<span class="wm-item">\uD83D\uDCCF '+escapeHtml(sizeStr)+'</span>' +
                        (w.threads != null ? '<span class="wm-item">\uD83E\uDDF5 '+escapeHtml(w.threads)+' thread'+(w.threads!==1?'s':'')+'</span>' : '') +
                        (modelTitles ? '<span class="wm-item models-pill" data-tooltip="'+escapeHtml(modelTitles)+'">' : '<span class="wm-item models-pill">') +'\uD83E\uDDE9 '+modelCount+' model'+(modelCount!==1?'s':'')+(modelCount>0?' \u25BE':'')+'</span>' +
                        '</div>' +
                        '<div class="worker-stats-row">' +
                        '<span class="ws-item">&#9201; '+escapeHtml(uptimeStr)+' uptime</span>' +
                        '<span class="ws-item">\uD83D\uDC8E '+kudos+' kudos</span>' +
                        '<span class="ws-item accent">\uD83D\uDCC8 '+kph+' k/h</span>' +
                        '</div>' +
                        '</div>';
                }).join('');
            }
        }
        function showPage(pageId, navEl, push) {
            if (!VALID_PAGES.includes(pageId)) pageId = 'overview';
            document.querySelectorAll('.page').forEach(function(p) { p.classList.remove('active'); });
            var page = document.getElementById('page-' + pageId);
            if (page) page.classList.add('active');
            document.querySelectorAll('.nav-item').forEach(function(item) { item.classList.remove('active'); });
            var activeNav = navEl || document.getElementById('nav-' + pageId);
            if (activeNav) activeNav.classList.add('active');
            if (window.innerWidth < 768) closeSidebar();
            var newHash = '#' + pageId;
            if (push !== false) {
                if (location.hash !== newHash) history.pushState({page: pageId}, '', newHash);
            }
            if (pageId === 'gallery') {
                const gridEl = document.getElementById('gallery-grid');
                const gridEmpty = !gridEl || !gridEl.querySelector('.image-grid-item');
                if (gridEmpty) {
                    // First visit (or after page-size change cleared the grid): full fetch.
                    fetchGalleryPage(galleryCurrentPage);
                } else if (galleryHasUnseenImages) {
                    // New images arrived while we were on another tab.  Handle exactly the
                    // same way the status-poll would if the gallery tab had been active.
                    galleryHasUnseenImages = false;
                    if (galleryCurrentPage === 1) {
                        if (!galleryFetchInProgress) refreshGalleryPage1();
                    } else {
                        const bnr = document.getElementById('gallery-new-banner');
                        if (bnr) bnr.style.display = '';
                    }
                }
                // Otherwise the grid already shows the current page with cached thumbnails;
                // new-image notifications continue via the status-poll path.
            }
            if (pageId === 'user') {
                // Render cached workers immediately so the list is visible before the next status poll.
                renderWorkersList();
            }
        }
        window.addEventListener('popstate', function() {
            var hash = location.hash.replace('#', '');
            showPage(VALID_PAGES.includes(hash) ? hash : 'overview', null, false);
        });
        (function() {
            var hash = location.hash.replace('#', '');
            if (hash && VALID_PAGES.includes(hash)) {
                showPage(hash, null, false);
            } else {
                history.replaceState({page: 'overview'}, '', '#overview');
            }
        })();
        function initTheme() {
            const saved = localStorage.getItem('horde-theme') || 'light';
            document.documentElement.setAttribute('data-theme', saved);
            const icon = saved === 'dark' ? '&#9728;' : '&#127769;';
            document.getElementById('topbar-theme-toggle').innerHTML = icon;
            document.getElementById('mobile-theme-toggle').innerHTML = icon;
        }
        function toggleTheme() {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('horde-theme', next);
            const icon = next === 'dark' ? '&#9728;' : '&#127769;';
            document.getElementById('topbar-theme-toggle').innerHTML = icon;
            document.getElementById('mobile-theme-toggle').innerHTML = icon;
        }
        initTheme();
        let overlayImages = [], overlayIndex = -1;
        // When non-null, holds the stable gallery_id values for the current overlay page
        // so images can be fetched lazily via /api/gallery/image.
        let _galleryOverlayIds = null;
        // AbortController for the in-flight overlay image fetch; prevents stale responses
        // from overwriting the overlay when the user navigates quickly.
        let _overlayFetchController = null;
        function _updateOverlayNav() {
            const hasList = overlayImages.length > 1;
            const pb = document.getElementById('overlay-prev'), nb = document.getElementById('overlay-next');
            const ctr = document.getElementById('overlay-counter');
            pb.style.display = nb.style.display = hasList ? 'block' : 'none';
            if (hasList) { pb.disabled = overlayIndex <= 0; nb.disabled = overlayIndex >= overlayImages.length - 1; ctr.textContent = (overlayIndex + 1) + ' / ' + overlayImages.length; }
            else { ctr.textContent = ''; }
        }
        function openImageOverlay(imageSrc, images, index) {
            if (Array.isArray(images) && Number.isFinite(index) && images.length > 0) {
                const len = images.length;
                const safeIndex = Math.min(Math.max(Math.trunc(index), 0), len - 1);
                overlayImages = images;
                overlayIndex = safeIndex;
            } else { overlayImages = []; overlayIndex = -1; }
            _galleryOverlayIds = null;
            if (_overlayFetchController) { _overlayFetchController.abort(); _overlayFetchController = null; }
            document.getElementById('overlay-image').src = imageSrc;
            document.getElementById('image-overlay').classList.add('active');
            _updateOverlayNav();
        }
        function _loadGalleryOverlayImage(galleryId) {
            if (_overlayFetchController) _overlayFetchController.abort();
            _overlayFetchController = new AbortController();
            const ctrl = _overlayFetchController;
            const el = document.getElementById('overlay-image');
            el.style.opacity = '0.35';
            fetch('/api/gallery/image?id=' + galleryId, { signal: ctrl.signal })
                .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
                .then(function(data) { if (ctrl !== _overlayFetchController) return; el.src = 'data:image/png;base64,' + data.base64; el.style.opacity = ''; })
                .catch(function(err) { if (err.name === 'AbortError') return; console.error('Failed to load gallery image:', err); el.style.opacity = ''; });
        }
        function openGalleryImageOverlay(galleryId, galleryIds, localIdx) {
            if (_overlayFetchController) { _overlayFetchController.abort(); _overlayFetchController = null; }
            if (Array.isArray(galleryIds) && galleryIds.length > 0) {
                overlayImages = galleryIds;
                overlayIndex = localIdx;
                _galleryOverlayIds = galleryIds;
            } else {
                overlayImages = [galleryId];
                overlayIndex = 0;
                _galleryOverlayIds = [galleryId];
            }
            document.getElementById('overlay-image').src = '';
            document.getElementById('image-overlay').classList.add('active');
            _updateOverlayNav();
            _loadGalleryOverlayImage(galleryId);
        }
        function overlayNavigate(delta) {
            const ni = overlayIndex + delta;
            if (ni < 0 || ni >= overlayImages.length) return;
            overlayIndex = ni;
            if (_galleryOverlayIds !== null) {
                _loadGalleryOverlayImage(_galleryOverlayIds[overlayIndex]);
            } else {
                document.getElementById('overlay-image').src = overlayImages[overlayIndex];
            }
            _updateOverlayNav();
        }
        function closeImageOverlay() {
            if (_overlayFetchController) { _overlayFetchController.abort(); _overlayFetchController = null; }
            document.getElementById('image-overlay').classList.remove('active');
            overlayImages = []; overlayIndex = -1; _galleryOverlayIds = null;
        }
        document.getElementById('image-overlay').addEventListener('click', function(e) { if (e.target === this) closeImageOverlay(); });
        document.addEventListener('keydown', function(e) {
            const overlayActive = document.getElementById('image-overlay').classList.contains('active');
            if (e.key === 'Escape') {
                if (overlayActive) { e.preventDefault(); e.stopPropagation(); }
                closeImageOverlay();
            } else if (overlayActive && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
                e.preventDefault();
                e.stopPropagation();
                overlayNavigate(e.key === 'ArrowLeft' ? -1 : 1);
            }
        });
        function formatUptime(seconds) {
            const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = Math.floor(seconds % 60);
            return h+'h '+m+'m '+s+'s';
        }
        function formatTimeAgo(timestamp) {
            if (!timestamp || timestamp === 0) return 'No image generated yet';
            const now = Date.now() / 1000, sa = Math.floor(now - timestamp);
            if (sa < 60) return 'Last submission: '+sa+' second'+(sa !== 1 ? 's' : '')+' ago';
            else if (sa < 3600) { const m = Math.floor(sa/60); return 'Last submission: '+m+' minute'+(m !== 1?'s':'')+' ago'; }
            else if (sa < 86400) { const h = Math.floor(sa/3600); return 'Last submission: '+h+' hour'+(h !== 1?'s':'')+' ago'; }
            else { const d = Math.floor(sa/86400); return 'Last submission: '+d+' day'+(d !== 1?'s':'')+' ago'; }
        }
        function formatTimestamp(timestamp) {
            if (!timestamp || timestamp === 0) return '';
            const d = new Date(timestamp * 1000);
            return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        }
        const SCROLL_TOLERANCE_PX = 1;
        let consolePaused = false;
        function toggleConsolePause() {
            consolePaused = !consolePaused;
            const btn = document.getElementById('console-pause-btn');
            if (consolePaused) { btn.textContent = '\u25B6 Resume'; btn.classList.add('paused'); btn.title = 'Resume console output'; btn.setAttribute('aria-pressed', 'true'); }
            else { btn.textContent = '\u25AE\u25AE Pause'; btn.classList.remove('paused'); btn.title = 'Pause console output'; btn.setAttribute('aria-pressed', 'false'); }
        }
        const ERRORS_PAGE_SIZE = 10;
        let errorsCurrentPage = 1, errorsTotal = 0, errorsTotalPages = 1, errorsPageData = [];
        let _errorsAbortController = null;
        function fetchErrorsPage(page) {
            if (_errorsAbortController) _errorsAbortController.abort();
            _errorsAbortController = new AbortController();
            const ctrl = _errorsAbortController;
            fetch('/api/errors?page='+page+'&page_size='+ERRORS_PAGE_SIZE, { signal: ctrl.signal })
                .then(r => { if (!r.ok) throw new Error('HTTP error! status: '+r.status); return r.json(); })
                .then(data => {
                    if (ctrl !== _errorsAbortController) return;
                    _errorsAbortController = null;
                    errorsCurrentPage = data.page;
                    errorsTotal = data.total;
                    errorsTotalPages = data.total_pages;
                    errorsPageData = data.errors || [];
                    renderErrorsPage();
                })
                .catch(err => { if (err.name !== 'AbortError') console.error('Failed to fetch /api/errors:', err); });
        }
        function renderErrorsPage() {
            const ed = document.getElementById('errors-history'), pi = document.getElementById('errors-page-info'),
                  pb = document.getElementById('errors-prev'), nb = document.getElementById('errors-next'),
                  pag = document.getElementById('errors-pagination'), cnt = document.getElementById('errors-count');
            if (errorsTotal === 0) {
                ed.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#10003;</span>No errors</div>';
                pag.style.display = 'none'; cnt.textContent = '0'; return;
            }
            ed.innerHTML = errorsPageData.map(err => '<div class="error-item">'+escapeHtml(err)+'</div>').join('');
            pi.textContent = 'Page '+errorsCurrentPage+' of '+errorsTotalPages;
            pb.disabled = errorsCurrentPage <= 1; nb.disabled = errorsCurrentPage >= errorsTotalPages;
            pag.style.display = 'flex'; cnt.textContent = errorsTotal;
        }
        function errorsChangePage(delta) {
            const newPage = Math.min(Math.max(1, errorsCurrentPage + delta), errorsTotalPages);
            if (newPage !== errorsCurrentPage) fetchErrorsPage(newPage);
        }
        const GALLERY_DEFAULT_PAGE_SIZE = 96;
        let galleryPageSize = GALLERY_DEFAULT_PAGE_SIZE;
        // Sync the select element's initial value with the JS constant (single source of truth)
        document.getElementById('gallery-page-size').value = String(GALLERY_DEFAULT_PAGE_SIZE);
        let lastKnownImagesCount = -1; // -1 = sentinel: first status poll not yet completed
        // Set to true when new images arrive while the gallery tab is not active.
        // Consumed by showPage() to refresh or show the banner on return.
        let galleryHasUnseenImages = false;
        // Monotonically increasing batch ID used to cancel stale thumbnail loads when the
        // page changes before the previous batch has finished.
        let _galleryThumbnailBatchId = 0;
        // AbortController for the currently running thumbnail batch; aborted when the page changes.
        let _galleryBatchAbort = null;
        // Ordered list of gallery_ids for the currently displayed page; used by overlay navigation.
        // Stored at module scope so incremental updates (refreshGalleryPage1) keep it in sync.
        let _currentPageGalleryIds = [];
        // Client-side cache: gallery_id (integer) → thumbnail data-URL string.
        // Avoids re-fetching thumbnails when the user switches pages or returns to the gallery tab.
        // Evicts the oldest entry once the cache exceeds _GALLERY_THUMBNAIL_CACHE_MAX to bound memory.
        const _galleryThumbnailCache = new Map();
        const _GALLERY_THUMBNAIL_CACHE_MAX = 1000;
        const GALLERY_VALID_COLS = [1, 2, 3, 4, 6, 12];
        const GALLERY_MIN_ITEM_PX = 160;
        const GALLERY_GRID_GAP_PX = 10;
        function updateGalleryColumns() {
            const grid = document.getElementById('gallery-grid');
            if (!grid) return;
            const width = grid.clientWidth;
            if (!width) return;
            // Account for gaps between columns so tiles never shrink below GALLERY_MIN_ITEM_PX.
            // For n columns there are (n-1) gaps, so the available width per column is
            // (width - (n-1)*gap) / n >= GALLERY_MIN_ITEM_PX, i.e. n <= (width + gap) / (GALLERY_MIN_ITEM_PX + gap).
            const rawCols = Math.max(1, Math.floor((width + GALLERY_GRID_GAP_PX) / (GALLERY_MIN_ITEM_PX + GALLERY_GRID_GAP_PX)));
            const cols = GALLERY_VALID_COLS.filter(c => c <= rawCols).pop() || 1;
            grid.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(' + GALLERY_MIN_ITEM_PX + 'px, 1fr))';
        }
        let _galleryResizeObserver = null;
        if (typeof ResizeObserver !== 'undefined') {
            _galleryResizeObserver = new ResizeObserver(function() { updateGalleryColumns(); });
            const _galleryGridEl = document.getElementById('gallery-grid');
            if (_galleryGridEl) _galleryResizeObserver.observe(_galleryGridEl);
        }
        function _cacheThumbnail(galleryId, dataUrl) {
            _galleryThumbnailCache.set(galleryId, dataUrl);
            if (_galleryThumbnailCache.size > _GALLERY_THUMBNAIL_CACHE_MAX) {
                _galleryThumbnailCache.delete(_galleryThumbnailCache.keys().next().value);
            }
        }
        function renderGalleryPageSkeleton(images, total, page, totalPages) {
            galleryTotalImages = total; galleryCurrentPage = page; galleryTotalPages = totalPages;
            const grid = document.getElementById('gallery-grid'), empty = document.getElementById('gallery-empty'),
                  pi = document.getElementById('gallery-page-info'), pb = document.getElementById('gallery-prev'),
                  nb = document.getElementById('gallery-next'), pag = document.getElementById('gallery-pagination'),
                  cnt = document.getElementById('gallery-count');
            cnt.textContent = total;
            if (page === 1) { const bnr = document.getElementById('gallery-new-banner'); if (bnr) bnr.style.display = 'none'; }
            if (images.length === 0) {
                grid.style.display = 'none'; grid.innerHTML = ''; empty.style.display = '';
                pag.style.display = 'none'; return;
            }
            empty.style.display = 'none'; grid.style.display = '';
            updateGalleryColumns();
            // Use stable gallery_id values (assigned at insertion time) rather than
            // positional indices, so the overlay remains correct even when new images
            // arrive after the page was rendered.
            _currentPageGalleryIds = images.map(img => img.gallery_id);
            // Render placeholder items with a shimmer animation; images are filled in
            // one by one by loadGalleryThumbnailsOneByOne once the skeleton is shown.
            // For thumbnails already in the client-side cache, skip the shimmer and
            // show the image immediately.
            grid.innerHTML = images.map((img, idx) => {
                const galleryId = img.gallery_id;
                const ts = formatTimestamp(img.timestamp), model = img.model ? escapeHtml(img.model) : '';
                const cap = [ts, model].filter(Boolean).join(' \u00b7 ');
                const cachedSrc = _galleryThumbnailCache.get(galleryId);
                // Only use the cached value when it is a well-formed image data URL to
                // guard against any unexpected cache content reaching innerHTML.
                if (cachedSrc && (cachedSrc.startsWith('data:image/jpeg;base64,') || cachedSrc.startsWith('data:image/png;base64,'))) {
                    return '<div class="image-grid-item" data-gallery-id="'+galleryId+'"><img alt="Generated image" src="'+cachedSrc+'" data-gallery-id="'+galleryId+'" data-idx="'+idx+'" />'+
                        (cap ? '<div class="image-timestamp">'+cap+'</div>' : '')+'</div>';
                }
                return '<div class="image-grid-item loading" data-gallery-id="'+galleryId+'"><img alt="Generated image" data-gallery-id="'+galleryId+'" data-idx="'+idx+'" style="display:none;" />'+
                    (cap ? '<div class="image-timestamp">'+cap+'</div>' : '')+'</div>';
            }).join('');
            grid.querySelectorAll('img[data-gallery-id]').forEach(img => {
                img.onclick = function() {
                    const galleryId = parseInt(this.getAttribute('data-gallery-id') || '0', 10);
                    const localIdx = parseInt(this.getAttribute('data-idx') || '0', 10);
                    openGalleryImageOverlay(galleryId, _currentPageGalleryIds, localIdx);
                };
            });
            const tp = Math.max(1, totalPages);
            pi.textContent = 'Page '+page+' of '+tp;
            pb.disabled = page <= 1; nb.disabled = page >= tp;
            pag.style.display = 'flex';
        }
        function loadGalleryThumbnailsOneByOne(galleryIds) {
            // Increment the batch ID so any stale responses from a previous page are discarded.
            const batchId = ++_galleryThumbnailBatchId;
            // Use an AbortController so in-flight requests are truly cancelled when the page changes.
            const batchAbort = new AbortController();
            function buildThumbnailDataUrl(data) {
                if (data.thumbnail) return 'data:image/jpeg;base64,'+data.thumbnail;
                if (data.base64) return 'data:image/png;base64,'+data.base64;
                return null;
            }
            function loadNext(i) {
                if (batchId !== _galleryThumbnailBatchId || i >= galleryIds.length) return;
                const galleryId = galleryIds[i];
                // If the thumbnail is already cached (rendered immediately by renderGalleryPageSkeleton),
                // skip the network request and move straight to the next item.
                if (_galleryThumbnailCache.has(galleryId)) { loadNext(i + 1); return; }
                fetch('/api/gallery/image?id='+galleryId+'&thumbnail_only=true', { signal: batchAbort.signal })
                    .then(r => { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
                    .then(data => {
                        if (batchId !== _galleryThumbnailBatchId) return;
                        const container = document.querySelector('.image-grid-item[data-gallery-id="'+galleryId+'"]');
                        const imgEl = container ? container.querySelector('img[data-gallery-id="'+galleryId+'"]') : null;
                        const thumbSrc = buildThumbnailDataUrl(data);
                        // Only cache actual JPEG thumbnails (Pillow-generated, small).
                        // When Pillow is absent the response falls back to full-resolution PNG;
                        // caching those would balloon memory for workers without Pillow.
                        if (data.thumbnail && thumbSrc) { _cacheThumbnail(galleryId, thumbSrc); }
                        if (thumbSrc && imgEl) { imgEl.src = thumbSrc; imgEl.style.display = ''; }
                        // Always remove the shimmer class; if no image data was returned the tile
                        // shows as an empty placeholder rather than spinning indefinitely.
                        if (container) container.classList.remove('loading');
                    })
                    .catch(err => {
                        if (err.name === 'AbortError') return;
                        console.error('Thumbnail load error for id '+galleryId+':', err);
                        // On error, stop the shimmer so the tile doesn't spin forever.
                        const container = document.querySelector('.image-grid-item[data-gallery-id="'+galleryId+'"]');
                        if (container) container.classList.remove('loading');
                    })
                    .finally(() => { loadNext(i + 1); });
            }
            // Abort the previous batch's requests and register the new controller.
            if (_galleryBatchAbort) { try { _galleryBatchAbort.abort(); } catch(_){} }
            _galleryBatchAbort = batchAbort;
            loadNext(0);
        }
        function fetchGalleryPage(page) {
            if (galleryFetchInProgress) return;
            galleryFetchInProgress = true;
            // Show a loading indicator and hide the empty-state while the fetch is in progress
            // so the "No images generated yet" message is not shown before we know the result.
            const glEl = document.getElementById('gallery-loading'), geEl = document.getElementById('gallery-empty');
            if (glEl) glEl.style.display = 'block';
            if (geEl) geEl.style.display = 'none';
            // Phase 1: fetch lightweight metadata only so the page skeleton can be shown
            // immediately without waiting for all thumbnail data to transfer.
            fetch('/api/gallery?page='+page+'&page_size='+galleryPageSize+'&metadata_only=true')
                .then(r => { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
                .then(data => {
                    if (glEl) glEl.style.display = 'none';
                    renderGalleryPageSkeleton(data.images, data.total, data.page, data.total_pages);
                    galleryFetchInProgress = false;
                    // Phase 2: load each thumbnail one by one, updating the skeleton as images arrive.
                    loadGalleryThumbnailsOneByOne(data.images.map(img => img.gallery_id));
                })
                .catch(err => {
                    console.error('Gallery fetch error:', err);
                    if (glEl) glEl.style.display = 'none';
                    galleryFetchInProgress = false;
                    // On error, if the grid has no content (e.g. first load) show the empty-state
                    // so the user isn't left with a completely blank gallery card.
                    const gridEl = document.getElementById('gallery-grid');
                    const hasGridContent = gridEl && gridEl.querySelector('.image-grid-item');
                    if (!hasGridContent) {
                        if (geEl) geEl.style.display = '';
                    }
                });
        }
        // Incrementally update page 1 when new images arrive: prepend only new tiles and load
        // their thumbnails without disturbing images that are already loaded in the grid.
        function refreshGalleryPage1() {
            if (galleryFetchInProgress) return;
            galleryFetchInProgress = true;
            fetch('/api/gallery?page=1&page_size='+galleryPageSize+'&metadata_only=true')
                .then(r => { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
                .then(data => {
                    galleryFetchInProgress = false;
                    galleryCurrentPage = 1; galleryTotalImages = data.total; galleryTotalPages = data.total_pages;
                    const grid = document.getElementById('gallery-grid'), cnt = document.getElementById('gallery-count'),
                          pi = document.getElementById('gallery-page-info'), pb = document.getElementById('gallery-prev'),
                          nb = document.getElementById('gallery-next'), pag = document.getElementById('gallery-pagination'),
                          bnr = document.getElementById('gallery-new-banner'), empty = document.getElementById('gallery-empty');
                    cnt.textContent = data.total;
                    if (bnr) bnr.style.display = 'none';
                    const tp = Math.max(1, data.total_pages);
                    pi.textContent = 'Page 1 of '+tp; pb.disabled = true; nb.disabled = 1 >= tp; pag.style.display = 'flex';
                    if (data.images.length === 0) {
                        grid.style.display = 'none'; grid.innerHTML = ''; empty.style.display = '';
                        pag.style.display = 'none'; return;
                    }
                    empty.style.display = 'none'; grid.style.display = '';
                    updateGalleryColumns();
                    const fetchedIds = data.images.map(img => img.gallery_id);
                    const fetchedSet = new Set(fetchedIds);
                    const existingItems = Array.from(grid.querySelectorAll('.image-grid-item[data-gallery-id]'));
                    const existingSet = new Set(existingItems.map(el => parseInt(el.getAttribute('data-gallery-id'), 10)));
                    // Remove tiles that have been pushed off the current page by new arrivals.
                    existingItems.forEach(el => { if (!fetchedSet.has(parseInt(el.getAttribute('data-gallery-id'), 10))) el.remove(); });
                    // Update the stable ID list and data-idx attributes for correct overlay navigation.
                    _currentPageGalleryIds = fetchedIds;
                    data.images.forEach((img, idx) => {
                        const ie = grid.querySelector('img[data-gallery-id="'+img.gallery_id+'"]');
                        if (ie) ie.setAttribute('data-idx', idx);
                    });
                    // Prepend skeleton tiles for new images, then load only their thumbnails.
                    // Build newImages with the index from data.images (which matches fetchedIds 1:1)
                    // to avoid repeated indexOf scans when setting data-idx on each tile.
                    const newImages = data.images.reduce((acc, img, idx) => {
                        if (!existingSet.has(img.gallery_id)) acc.push({ img, idx });
                        return acc;
                    }, []);
                    if (newImages.length > 0) {
                        const frag = document.createDocumentFragment();
                        newImages.forEach(({ img, idx }) => {
                            const galleryId = img.gallery_id;
                            const ts = formatTimestamp(img.timestamp), model = img.model ? escapeHtml(img.model) : '';
                            const cap = [ts, model].filter(Boolean).join(' \u00b7 ');
                            const div = document.createElement('div');
                            div.className = 'image-grid-item loading';
                            div.setAttribute('data-gallery-id', galleryId);
                            div.innerHTML = '<img alt="Generated image" data-gallery-id="'+galleryId+'" data-idx="'+idx+'" style="display:none;" />'+(cap ? '<div class="image-timestamp">'+cap+'</div>' : '');
                            div.querySelector('img').onclick = function() { openGalleryImageOverlay(parseInt(this.getAttribute('data-gallery-id')||'0',10), _currentPageGalleryIds, parseInt(this.getAttribute('data-idx')||'0',10)); };
                            frag.appendChild(div);
                        });
                        grid.insertBefore(frag, grid.firstChild);
                        // Abort previous batch and start a new one so incremental thumbnail fetches
                        // are cancelled if the user navigates away or a full page reload is triggered.
                        if (_galleryBatchAbort) _galleryBatchAbort.abort();
                        const incrAbort = new AbortController();
                        _galleryBatchAbort = incrAbort;
                        newImages.forEach(({ img }) => {
                            const galleryId = img.gallery_id;
                            fetch('/api/gallery/image?id='+galleryId+'&thumbnail_only=true', { signal: incrAbort.signal })
                                .then(r => { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
                                .then(d => {
                                    const c = grid.querySelector('.image-grid-item[data-gallery-id="'+galleryId+'"]');
                                    const ie = c ? c.querySelector('img') : null;
                                    const src = d.thumbnail ? 'data:image/jpeg;base64,'+d.thumbnail : (d.base64 ? 'data:image/png;base64,'+d.base64 : null);
                                    // Only cache actual JPEG thumbnails; skip full-res PNG fallback.
                                    if (d.thumbnail && src) { _cacheThumbnail(galleryId, src); }
                                    if (src && ie) { ie.src = src; ie.style.display = ''; }
                                    if (c) c.classList.remove('loading');
                                })
                                .catch(err => {
                                    if (err.name === 'AbortError') return;
                                    const c = grid.querySelector('.image-grid-item[data-gallery-id="'+galleryId+'"]');
                                    if (c) c.classList.remove('loading');
                                });
                        });
                    }
                })
                .catch(err => { console.error('Gallery refresh error:', err); galleryFetchInProgress = false; });
        }
        function galleryChangePage(delta) {
            const newPage = Math.min(Math.max(1, galleryCurrentPage + delta), Math.max(1, galleryTotalPages));
            fetchGalleryPage(newPage);
        }
        function galleryChangePageSize(val) {
            galleryPageSize = parseInt(val, 10) || GALLERY_DEFAULT_PAGE_SIZE;
            fetchGalleryPage(1);
        }
        function isScrolledToBottom(el, tol) { return el.scrollHeight - el.clientHeight <= el.scrollTop + tol; }
        function ansiToHtml(text) {
            text = escapeHtml(text);
            const colors = {'30':'#000000','31':'#cd3131','32':'#0dbc79','33':'#e5e510','34':'#2472c8','35':'#bc3fbc','36':'#11a8cd','37':'#e5e5e5','90':'#666666','91':'#f14c4c','92':'#23d18b','93':'#f5f543','94':'#3b8eea','95':'#d670d6','96':'#29b8db','97':'#ffffff','1;30':'#666666','1;31':'#f14c4c','1;32':'#23d18b','1;33':'#f5f543','1;34':'#3b8eea','1;35':'#d670d6','1;36':'#29b8db','1;37':'#ffffff'};
            const bgColors = {'40':'#000000','41':'#cd3131','42':'#0dbc79','43':'#e5e510','44':'#2472c8','45':'#bc3fbc','46':'#11a8cd','47':'#e5e5e5','100':'#666666','101':'#f14c4c','102':'#23d18b','103':'#f5f543','104':'#3b8eea','105':'#d670d6','106':'#29b8db','107':'#ffffff'};
            let result = '', cs = [];
            const parts = text.split(/\x1b\[([0-9;]+)m/);
            for (let i = 0; i < parts.length; i++) {
                if (i % 2 === 0) { result += cs.length > 0 ? '<span style="'+cs.join(';')+'">'+parts[i]+'</span>' : parts[i]; }
                else {
                    for (const c of parts[i].split(';')) {
                        if (c === '0' || c === '') { cs = []; }
                        else if (c === '1') { if (!cs.some(s => s.startsWith('font-weight:'))) cs.push('font-weight:bold'); }
                        else if (c === '2') { if (!cs.some(s => s.startsWith('opacity:'))) cs.push('opacity:0.6'); }
                        else if (c === '3') { if (!cs.some(s => s.startsWith('font-style:'))) cs.push('font-style:italic'); }
                        else if (c === '4') { if (!cs.some(s => s.startsWith('text-decoration:'))) cs.push('text-decoration:underline'); }
                        else if (colors[c]) { cs = cs.filter(s => !s.startsWith('color:')); cs.push('color:'+colors[c]); }
                        else if (bgColors[c]) { cs = cs.filter(s => !s.startsWith('background-color:')); cs.push('background-color:'+bgColors[c]); }
                    }
                }
            }
            return result;
        }
        let statusAbortController = null, _lastImageFetchController = null, _lastImageFetchTimestamp = null, consecutiveErrors = 0;
        let statusUpdateTimestamp = Date.now(), updateIntervalMs = 1000, scheduledUpdateTimer = null;
        const MAX_CONSECUTIVE_ERRORS = 5;
        function resBarColor(pct) { return pct >= 80 ? '#ef4444' : pct >= 60 ? '#f59e0b' : '#10b981'; }
        let _lastRenderedImageKey = null;
        // Tracks the last image submission timestamp for which images have been fetched.
        // Images are only re-fetched when this value changes, keeping /api/status lightweight.
        let _lastFetchedImageTimestamp = null;
        // Track the current job id and its highest-seen progress so the bar never goes
        // backwards for the same job.  Reset whenever the displayed job id changes.
        let _currentJobId = null;
        let _currentJobProgress = 0;
        function _getImageKey(rawB64, timestamp) {
            if (!rawB64 || rawB64.length === 0) return 'empty';
            // Use count + submission timestamp as the change-detection key.
            // The first bytes of a PNG base64 string are always a fixed header, so sampling
            // from the beginning is not reliable. The timestamp changes whenever new images arrive.
            return rawB64.length + ':' + (timestamp || 0);
        }
        function renderLastImages(rawB64, oic, timestamp) {
            const key = _getImageKey(rawB64, timestamp);
            if (key === _lastRenderedImageKey) return;
            _lastRenderedImageKey = key;
            oic.classList.remove('loading');
            // Capture the render token so async image-load callbacks can detect whether a
            // newer renderLastImages() call has already superseded this one.
            const renderToken = key;
            if (!rawB64 || rawB64.length === 0) {
                oic.removeAttribute('style');
                oic.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#128444;</span>No image generated yet</div>';
                return;
            }
            const previewB64 = rawB64.slice(0, 4);
            const count = previewB64.length;
            const srcs = previewB64.map(function(b) { return 'data:image/png;base64,' + b; });
            const allSrcs = rawB64.map(function(b) { return 'data:image/png;base64,' + b; });
            function attachClicks() {
                oic.querySelectorAll('img[data-fullsize]').forEach(function(img) {
                    img.onclick = function() { openImageOverlay(this.getAttribute('data-fullsize'), allSrcs, parseInt(this.getAttribute('data-idx') || '0', 10)); };
                });
            }
            if (count === 1) {
                oic.removeAttribute('style');
                oic.innerHTML = '<img src="' + srcs[0] + '" class="single-image" alt="Last generated image" data-fullsize="' + srcs[0] + '" data-idx="0" />';
                attachClicks();
                return;
            }
            function makeItem(s, i, spanFull) {
                var span = spanFull ? ' style="grid-column:1/-1;"' : '';
                return '<div class="image-grid-item"' + span + '><img src="' + s + '" alt="Generated image ' + (i + 1) + '" data-fullsize="' + s + '" data-idx="' + i + '" /></div>';
            }
            var imgDims = new Array(count).fill(null), loadedCount = 0;
            function renderGrid() {
                if (_lastRenderedImageKey !== renderToken) return;
                var containerWidth = oic.offsetWidth || 320;
                var containerHeight = oic.offsetHeight || 320;
                var gap = 4; // CSS gap in px; must match the gap value in the grid style below
                // Average image aspect ratio (width/height); all images in a batch share the same resolution,
                // so avgImgAR is effectively the single image AR.
                var avgImgAR = imgDims.reduce(function(sum, d) { return sum + (d ? d.w / d.h : 1.0); }, 0) / count;
                // Fraction of a cell's area covered by an image using object-fit:contain.
                // An image of AR imgAR in a cell of AR cellAR fills min(cellAR/imgAR, imgAR/cellAR) of the cell.
                // Choosing the layout with the highest cellEff minimises leftover (unused) container space.
                function cellEff(cellAR, imgAR) {
                    return imgAR > cellAR ? cellAR / imgAR : imgAR / cellAR;
                }
                var gridStyle, items;
                if (count === 2) {
                    // 1×2 side-by-side: 1 horizontal gap; each cell AR = (W−gap)/2 / H.
                    // 2×1 stacked:      1 vertical gap;   each cell AR = W / ((H−gap)/2).
                    var ar1x2 = (containerWidth - gap) / 2 / containerHeight;
                    var ar2x1 = containerWidth * 2 / (containerHeight - gap);
                    if (cellEff(ar1x2, avgImgAR) >= cellEff(ar2x1, avgImgAR)) {
                        gridStyle = 'grid-template-columns:repeat(2,1fr);grid-template-rows:1fr;';
                    } else {
                        gridStyle = 'grid-template-columns:1fr;grid-template-rows:repeat(2,1fr);';
                    }
                    items = srcs.map(function(s, i) { return makeItem(s, i, false); }).join('');
                } else if (count === 3) {
                    // 1×3 row:    2 horizontal gaps; each cell AR = (W−2×gap)/3 / H.
                    // 2+1 layout: 1 vertical gap between rows; each row height = (H−gap)/2.
                    //   Top cell spans full width: AR = W / rowH.
                    //   Two bottom cells share a horizontal gap: AR = (W−gap)/2 / rowH.
                    //   Area-weighted efficiency ≈ 0.5×cellEff(top) + 0.5×cellEff(bottom).
                    var rowH = (containerHeight - gap) / 2;
                    var ar1x3 = (containerWidth - 2 * gap) / 3 / containerHeight;
                    var ar2p1top = containerWidth / rowH;
                    var ar2p1bot = (containerWidth - gap) / 2 / rowH;
                    var eff1x3 = cellEff(ar1x3, avgImgAR);
                    var eff2p1 = 0.5 * cellEff(ar2p1top, avgImgAR) + 0.5 * cellEff(ar2p1bot, avgImgAR);
                    if (eff1x3 >= eff2p1) {
                        gridStyle = 'grid-template-columns:repeat(3,1fr);grid-template-rows:1fr;';
                        items = srcs.map(function(s, i) { return makeItem(s, i, false); }).join('');
                    } else {
                        gridStyle = 'grid-template-columns:repeat(2,1fr);grid-template-rows:1fr 1fr;';
                        items = srcs.map(function(s, i) { return makeItem(s, i, i === 0); }).join('');
                    }
                } else {
                    // count === 4
                    // 1×4 row:  3 horizontal gaps; each column width = (W−3×gap)/4, cell AR = colW / H.
                    //           Requires each column to be at least 120 px wide after subtracting gaps.
                    // 2×2 grid: 1 horizontal + 1 vertical gap; each cell AR = (W−gap) / (H−gap).
                    // 0 (impossible efficiency) disables 1×4 when columns would be narrower than 120 px.
                    var minColumnWidthPx = 120;
                    var col1x4 = (containerWidth - 3 * gap) / 4;
                    var ar1x4 = col1x4 / containerHeight;
                    var ar2x2 = (containerWidth - gap) / (containerHeight - gap);
                    var eff1x4 = col1x4 >= minColumnWidthPx ? cellEff(ar1x4, avgImgAR) : 0;
                    var eff2x2 = cellEff(ar2x2, avgImgAR);
                    if (eff1x4 >= eff2x2) {
                        gridStyle = 'grid-template-columns:repeat(4,1fr);grid-template-rows:1fr;';
                    } else {
                        gridStyle = 'grid-template-columns:repeat(2,1fr);grid-template-rows:1fr 1fr;';
                    }
                    items = srcs.map(function(s, i) { return makeItem(s, i, false); }).join('');
                }
                oic.style.cssText = 'display:grid;width:100%;gap:4px;align-items:stretch;' + gridStyle;
                oic.innerHTML = items;
                attachClicks();
            }
            srcs.forEach(function(src, i) {
                var img = new window.Image();
                img.onload = function() { imgDims[i] = { w: this.naturalWidth, h: this.naturalHeight }; loadedCount++; if (loadedCount === count) renderGrid(); };
                img.onerror = function() { imgDims[i] = { w: 1, h: 1 }; loadedCount++; if (loadedCount === count) renderGrid(); };
                img.src = src;
            });
        }
        function fetchLastImage(timestamp) {
            // Fetch images from the dedicated endpoint so that /api/status stays lightweight.
            // Only called when last_image_submission_timestamp changes.
            // If a fetch for this same timestamp is already in flight, let it complete rather
            // than aborting and restarting on every 1-second status poll.
            if (_lastImageFetchController && _lastImageFetchTimestamp === timestamp) return;
            // A *different* (newer) timestamp supersedes the previous request — abort it so
            // that a stale response can never overwrite a newer image (which would cause the
            // display to flicker back to an older result).
            if (_lastImageFetchController) _lastImageFetchController.abort();
            _lastImageFetchController = new AbortController();
            _lastImageFetchTimestamp = timestamp;
            const ctrl = _lastImageFetchController;
            fetch('/api/last_image', { signal: ctrl.signal })
                .then(r => { if (!r.ok) throw new Error('HTTP error! status: '+r.status); return r.json(); })
                .then(imgData => {
                    // Discard the response if a newer fetch has already superseded this one.
                    if (ctrl !== _lastImageFetchController) return;
                    _lastImageFetchController = null;
                    // Prefer the timestamp from the /api/last_image response so that the
                    // cache marker reflects the actual data that was rendered, not the
                    // /api/status snapshot that triggered the fetch.
                    var ts = imgData && imgData.last_image_submission_timestamp;
                    if (typeof ts !== 'number') { ts = Number(ts); }
                    if (!Number.isFinite(ts)) {
                        ts = (typeof timestamp === 'number' && Number.isFinite(timestamp)) ? timestamp
                            : (Number.isFinite(_lastFetchedImageTimestamp) ? _lastFetchedImageTimestamp : 0);
                    }
                    _lastFetchedImageTimestamp = ts;
                    renderLastImages(imgData.last_image_base64, document.getElementById('overview-image-container'), ts);
                })
                .catch(function(err) {
                    if (err.name === 'AbortError') return;
                    // Reset the in-flight marker so the next status poll can retry the request.
                    if (ctrl === _lastImageFetchController) { _lastImageFetchController = null; _lastImageFetchTimestamp = null; }
                    // Log the error but do not advance the cache marker so we can retry on the next status poll.
                    console.error('Failed to fetch /api/last_image:', err);
                    var container = document.getElementById('overview-image-container');
                    if (container) {
                        container.classList.remove('loading');
                        if (!container.hasChildNodes()) {
                            container.removeAttribute('style');
                            container.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#128444;</span>No image generated yet</div>';
                        }
                    }
                });
        }
        function scheduleUpdate() {
            if (scheduledUpdateTimer !== null) return;
            const elapsed = Date.now() - statusUpdateTimestamp;
            const delay = Math.max(0, updateIntervalMs - elapsed);
            scheduledUpdateTimer = setTimeout(updateStatus, delay);
        }
        function updateStatus() {
            scheduledUpdateTimer = null;
            statusUpdateTimestamp = Date.now();
            if (statusAbortController) statusAbortController.abort();
            statusAbortController = new AbortController();
            fetch('/api/status', { signal: statusAbortController.signal })
                .then(r => { if (!r.ok) throw new Error('HTTP error! status: '+r.status); return r.json(); })
                .then(data => {
                    consecutiveErrors = 0;
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('content').style.display = 'block';
                    const workerName = data.worker_name || 'Unknown';
                    document.getElementById('topbar-worker-name').textContent = workerName;
                    document.getElementById('topbar-worker-sub').textContent = '@'+data.horde_username;
                    const badgeHtml = data.maintenance_mode
                        ? '<span class="status-badge status-maintenance">Maintenance</span>'
                        : '<span class="status-badge status-active">Active</span>';
                    document.getElementById('worker-status-badge').innerHTML = badgeHtml;
                    document.getElementById('mobile-status-badge').innerHTML = data.maintenance_mode
                        ? '<span class="status-badge status-maintenance" style="font-size:0.68rem;padding:2px 7px;">Maint.</span>'
                        : '<span class="status-badge status-active" style="font-size:0.68rem;padding:2px 7px;">Active</span>';
                    const uptimeStr = formatUptime(data.uptime);
                    document.getElementById('uptime').textContent = uptimeStr;
                    document.getElementById('mobile-uptime').textContent = '\u23F1 ' + uptimeStr;
                    document.getElementById('user-kudos-total').textContent = data.user_kudos_total ? data.user_kudos_total.toLocaleString(undefined, {maximumFractionDigits: 2}) : '-';
                    document.getElementById('images-per-hour').textContent = (data.images_per_hour || 0).toLocaleString(undefined, {maximumFractionDigits: 2});
                    document.getElementById('jobs-popped').textContent = data.jobs_popped;
                    document.getElementById('jobs-completed').textContent = data.jobs_completed;
                    document.getElementById('jobs-faulted').textContent = data.jobs_faulted;
                    document.getElementById('processes-recovered').textContent = data.processes_recovered;
                    document.getElementById('jobs-queued').textContent = data.jobs_queued;
                    document.getElementById('time-without-jobs').textContent = formatUptime(data.time_without_jobs || 0);
                    const cpu = Math.min(100, Math.round(data.cpu_usage_percent));
                    const gpu = Math.min(100, Math.round(data.gpu_usage_percent));
                    const vram = data.total_vram_mb > 0 ? Math.min(100, Math.round((data.vram_usage_mb / data.total_vram_mb) * 100)) : 0;
                    document.getElementById('topbar-cpu-pct').textContent = cpu+'%';
                    const cpuBar = document.getElementById('topbar-cpu-bar');
                    cpuBar.style.width = cpu+'%';
                    cpuBar.style.backgroundColor = resBarColor(cpu);
                    document.getElementById('topbar-gpu-pct').textContent = gpu+'%';
                    const gpuBar = document.getElementById('topbar-gpu-bar');
                    gpuBar.style.width = gpu+'%';
                    gpuBar.style.backgroundColor = resBarColor(gpu);
                    document.getElementById('topbar-vram-pct').textContent = vram+'%';
                    const vramBar = document.getElementById('topbar-vram-bar');
                    vramBar.style.width = vram+'%';
                    vramBar.style.backgroundColor = resBarColor(vram);

                    document.getElementById('mobile-cpu').textContent = 'CPU '+cpu+'%';
                    document.getElementById('mobile-cpu').style.color = resBarColor(cpu);
                    document.getElementById('mobile-gpu').textContent = 'GPU '+gpu+'%';
                    document.getElementById('mobile-gpu').style.color = resBarColor(gpu);
                    document.getElementById('mobile-vram').textContent = 'VRAM '+vram+'%';
                    document.getElementById('mobile-vram').style.color = resBarColor(vram);
                    const ojd = document.getElementById('overview-current-job');
                    if (data.current_job) {
                        const job = data.current_job;
                        const sd = escapeHtml(job.state || 'N/A');
                        const rawPv = (job.progress !== null && job.progress !== undefined) ? job.progress : 0;
                        // Use null for missing ids so that two jobs without ids are never
                        // treated as the same job by the high-water-mark logic below.
                        const jobId = job.id || null;
                        // Never let the progress bar go backwards for the same job id.
                        // Skip the high-water mark when jobId is null (unknown id) so a
                        // missing-id job never pins progress across separate jobs.
                        let pv;
                        if (jobId !== null && jobId === _currentJobId) {
                            pv = Math.max(_currentJobProgress, rawPv);
                        } else {
                            _currentJobId = jobId;
                            pv = rawPv;
                        }
                        _currentJobProgress = pv;
                        ojd.classList.remove('centered-empty-container');
                        ojd.innerHTML =
                            '<div class="stat-row"><span class="stat-label">Job ID:</span><span class="stat-value" style="font-family:monospace;font-size:0.8rem;">'+escapeHtml(job.id||'N/A')+'</span></div>'+
                            '<div class="stat-row"><span class="stat-label">Model:</span><span class="stat-value">'+escapeHtml(job.model||'N/A')+'</span></div>'+
                            (job.batch_size!=null&&job.batch_size!==undefined?'<div class="stat-row"><span class="stat-label">Batch Size:</span><span class="stat-value">'+escapeHtml(job.batch_size)+'x</span></div>':'')+
                            (job.steps!=null&&job.steps!==undefined?'<div class="stat-row"><span class="stat-label">Steps:</span><span class="stat-value">'+escapeHtml(job.steps)+'</span></div>':'')+
                            (job.width!=null&&job.width!==undefined&&job.height!=null&&job.height!==undefined?'<div class="stat-row"><span class="stat-label">Image Size:</span><span class="stat-value">'+escapeHtml(job.width)+'x'+escapeHtml(job.height)+'</span></div>':'')+
                            (job.sampler!=null&&job.sampler!==undefined?'<div class="stat-row"><span class="stat-label">Sampler:</span><span class="stat-value">'+escapeHtml(job.sampler)+'</span></div>':'')+
                            '<div class="stat-row"><span class="stat-label">LoRAs:</span><span class="stat-value">'+(job.loras!=null&&job.loras!==undefined&&job.loras.length>0?job.loras.map(l=>escapeHtml(l.name||'Unknown')).join(', '):'None')+'</span></div>'+
                            '<div class="stat-row"><span class="stat-label">State:</span><span class="job-state-badge">'+sd+'</span></div>'+
                            '<div style="margin-top:14px;"><div class="progress-header"><span class="progress-label">Progress</span><span class="progress-value">'+escapeHtml(pv)+'%</span></div><div class="progress-bar-container" style="height:12px;"><div class="progress-bar" style="width:'+escapeHtml(pv)+'%;height:100%;border-radius:6px;"></div></div></div>';
                    } else {
                        ojd.classList.add('centered-empty-container');
                        ojd.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#9203;</span>No job in progress</div>';
                    }
                    const hasImage = data.last_image_submission_timestamp && data.last_image_submission_timestamp !== 0;
                    document.getElementById('overview-image-time').textContent = hasImage ? formatTimeAgo(data.last_image_submission_timestamp) : '';
                    // Fetch images separately so the status payload stays small.
                    // Images are re-fetched only when the submission timestamp changes.
                    if (data.last_image_submission_timestamp !== _lastFetchedImageTimestamp) {
                        if (hasImage) {
                            const oic = document.getElementById('overview-image-container');
                            if (!oic.querySelector('img')) {
                                oic.innerHTML = '';
                                oic.classList.add('loading');
                            }
                            fetchLastImage(data.last_image_submission_timestamp);
                        } else {
                            _lastFetchedImageTimestamp = data.last_image_submission_timestamp;
                            renderLastImages([], document.getElementById('overview-image-container'), 0);
                        }
                    }
                    const qd = document.getElementById('job-queue');
                    document.getElementById('queue-count').textContent = data.job_queue.length;
                    if (data.job_queue.length > 0) {
                        qd.innerHTML = data.job_queue.map(j => { const bi = j.batch_size&&j.batch_size>1?' ('+escapeHtml(j.batch_size)+'x batch)':''; return '<div class="job-item"><span class="job-id">'+escapeHtml(j.id||'N/A')+'</span>: '+escapeHtml(j.model||'Unknown model')+bi+'</div>'; }).join('');
                    } else { qd.innerHTML = '<div class="empty-state">Queue is empty</div>'; }
                    const md = document.getElementById('models-loaded');
                    if (data.models_loaded.length > 0) {
                        md.innerHTML = data.models_loaded.map(m => '<div class="model-badge">'+escapeHtml(m)+'</div>').join('');
                    } else { md.innerHTML = '<span style="color:#94a3b8;font-size:0.83rem;">No models loaded</span>'; }
                    const pd = document.getElementById('processes');
                    document.getElementById('process-count').textContent = data.processes.length;
                    if (data.processes.length > 0) {
                        pd.innerHTML = data.processes.map(proc => {
                            let sl = [];
                            if (proc.model) sl.push('Model: '+escapeHtml(proc.model));
                            if (proc.batch_size!=null&&proc.batch_size!==undefined) sl.push('Batch: '+escapeHtml(proc.batch_size)+'x');
                            if (proc.progress!=null&&proc.progress!==undefined) sl.push('Progress: '+escapeHtml(proc.progress)+'%');
                            return '<div class="process-item"><div class="process-id-row"><span class="process-id">Process #'+escapeHtml(proc.id)+'</span><span class="process-type-badge">'+escapeHtml(proc.type)+'</span><span class="process-state-badge">'+escapeHtml(proc.state)+'</span></div><div class="process-detail-text">'+(sl.length>0?sl.join(' | '):'Idle')+'</div></div>';
                        }).join('');
                    } else { pd.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#9881;</span>No process info</div>'; }
                    document.getElementById('gallery-count').textContent = data.images_count || 0;
                    const newImagesCount = data.images_count || 0;
                    const hasNewImages = lastKnownImagesCount >= 0 && newImagesCount > lastKnownImagesCount;
                    const galleryPageActive = document.getElementById('page-gallery').classList.contains('active');
                    if (hasNewImages && galleryPageActive) {
                        if (galleryCurrentPage === 1) {
                            if (!galleryFetchInProgress) {
                                refreshGalleryPage1();
                                lastKnownImagesCount = newImagesCount;
                            }
                            // If a fetch is already in progress, don't update lastKnownImagesCount so
                            // the next poll can still detect the new images and retry the refresh.
                        } else {
                            const gbn = document.getElementById('gallery-new-banner');
                            if (gbn) gbn.style.display = '';
                            lastKnownImagesCount = newImagesCount;
                        }
                    } else {
                        if (hasNewImages && !galleryPageActive) {
                            // New images arrived while another tab is shown.  Record this so
                            // showPage() can act when the user returns to the gallery tab.
                            galleryHasUnseenImages = true;
                        }
                        lastKnownImagesCount = newImagesCount;
                    }
                    const newErrorsCount = data.errors_count || 0;
                    if (newErrorsCount !== errorsTotal) {
                        if (newErrorsCount === 0) { errorsCurrentPage = 1; errorsTotal = 0; errorsTotalPages = 1; errorsPageData = []; renderErrorsPage(); }
                        else fetchErrorsPage(errorsCurrentPage);
                    }
                    const cl = document.getElementById('console-logs');
                    if (!consolePaused) {
                        if (data.console_logs && data.console_logs.length > 0) {
                            const atb = isScrolledToBottom(cl, SCROLL_TOLERANCE_PX);
                            cl.innerHTML = data.console_logs.map(log => '<div style="margin: 2px 0; white-space: pre-wrap; word-break: break-word;">'+ansiToHtml(log)+'</div>').join('');
                            if (atb) cl.scrollTop = cl.scrollHeight;
                        } else { cl.innerHTML = '<div style="text-align:center;color:#475569;padding:18px;">No logs available</div>'; }
                    }
                    // Update user page
                    const ud = data.user_details || {};
                    document.getElementById('user-page-username').textContent = data.horde_username || '-';
                    document.getElementById('user-page-kudos-total').textContent = data.user_kudos_total != null ? data.user_kudos_total.toLocaleString(undefined, {maximumFractionDigits: 2}) : '-';
                    document.getElementById('user-page-kudos-per-hour').textContent = (data.kudos_per_hour || 0).toLocaleString(undefined, {maximumFractionDigits: 2});
                    document.getElementById('user-page-kudos-session').textContent = (data.kudos_earned_session || 0).toLocaleString(undefined, {maximumFractionDigits: 2});
                    document.getElementById('user-page-images-per-hour').textContent = (data.images_per_hour || 0).toLocaleString(undefined, {maximumFractionDigits: 2});
                    document.getElementById('user-page-jobs-completed').textContent = data.jobs_completed || 0;
                    const trusted = ud.trusted;
                    document.getElementById('user-page-trusted').textContent = trusted === true ? '\u2714 Yes' : (trusted === false ? '\u2718 No' : '-');
                    document.getElementById('user-page-trusted').className = 'stat-card-value ' + (trusted === true ? 'success' : (trusted === false ? 'error' : ''));
                    document.getElementById('user-page-worker-count').textContent = ud.worker_count != null ? ud.worker_count : '-';
                    const kb = document.getElementById('user-page-kudos-breakdown');
                    const kd = ud.kudos_details || {};
                    const kdRows = [
                        ['Accumulated', kd.accumulated],
                        ['Gifted', kd.gifted],
                        ['Admin', kd.admin],
                        ['Received', kd.received],
                        ['Donated', kd.donated],
                        ['Recurring', kd.recurring],
                    ].filter(function(r){return r[1] != null;});
                    kb.innerHTML = kdRows.length > 0
                        ? kdRows.map(function(r){return '<div class="stat-row"><span class="stat-label">'+escapeHtml(r[0])+':</span><span class="stat-value">'+Number(r[1]).toLocaleString(undefined,{maximumFractionDigits:2})+'</span></div>';}).join('')
                        : '<div class="empty-state">No kudos breakdown available</div>';
                    // Render per-worker cards
                    if (Array.isArray(ud.workers_list)) {
                        cachedWorkersList = ud.workers_list;
                        try {
                            if (cachedWorkersList.length > 0) {
                                localStorage.setItem('horde-workers-list', JSON.stringify(cachedWorkersList));
                            } else {
                                localStorage.removeItem('horde-workers-list');
                            }
                        } catch(e) {}
                    } else if (ud.worker_count === 0) {
                        cachedWorkersList = [];
                        try { localStorage.removeItem('horde-workers-list'); } catch(e) {}
                    }
                    renderWorkersList();
                })
                .catch(error => {
                    if (error.name === 'AbortError') return;
                    consecutiveErrors++;
                    console.error('Error fetching status:', error);
                    if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS)
                        console.warn('Failed to fetch status '+consecutiveErrors+' times in a row. Check server connection.');
                })
                .finally(() => { statusAbortController = null; scheduleUpdate(); });
        }
        const DEFAULT_UPDATE_INTERVAL_MS = 1000;
        const CONFIG_FETCH_TIMEOUT_MS = 5000;
        async function fetchWithTimeout(url, timeoutMs) {
            const controller = new AbortController();
            const timerId = setTimeout(() => controller.abort(new Error('Request timed out after '+timeoutMs+'ms')), timeoutMs);
            try {
                return await fetch(url, { signal: controller.signal });
            } finally {
                clearTimeout(timerId);
            }
        }
        async function initializeUpdates() {
            try {
                const config = await (await fetchWithTimeout('/api/config', CONFIG_FETCH_TIMEOUT_MS)).json();
                updateIntervalMs = config.update_interval_ms || DEFAULT_UPDATE_INTERVAL_MS;
                updateStatus();
            } catch (e) {
                console.error('Error fetching config:', e);
                updateStatus();
            }
        }
        document.addEventListener('visibilitychange', function() {
            if (document.visibilityState === 'visible') {
                if (scheduledUpdateTimer !== null) { clearTimeout(scheduledUpdateTimer); scheduledUpdateTimer = null; }
                // If a status request is already in flight, let it complete rather than
                // aborting it and starting a new one. This avoids races between overlapping
                // requests and stale `.finally()` handlers.
                if (!statusAbortController) {
                    updateStatus();
                }
            }
        });
        initializeUpdates();
    </script>
</body>
</html>
        """
        return web.Response(text=html, content_type="text/html")

    async def _handle_status(self, request: web.Request) -> web.Response:
        """Handle status API request.

        Returns all status fields **except** ``last_image_base64`` and the full
        ``errors_history`` list so that large payloads are not included in every
        poll.  Clients should use ``last_image_submission_timestamp`` to detect
        new images (fetch via ``/api/last_image``) and ``errors_count`` to detect
        new errors (fetch the relevant page via ``/api/errors``).
        """
        payload = {k: v for k, v in self.status_data.items() if k not in ("last_image_base64", "errors_history")}
        payload["errors_count"] = len(self.status_data["errors_history"])
        return web.json_response(payload)

    async def _handle_last_image(self, request: web.Request) -> web.Response:
        """Return only the last generated image(s) and their submission timestamp.

        Separating image data from the main status response keeps ``/api/status``
        lightweight so the overview page loads quickly.  The client fetches this
        endpoint only when ``last_image_submission_timestamp`` changes, i.e. when
        a genuinely new image is available.
        """
        return web.json_response(
            {
                "last_image_base64": self.status_data["last_image_base64"],
                "last_image_submission_timestamp": self.status_data["last_image_submission_timestamp"],
            },
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle health check request."""
        return web.json_response({"status": "ok"})

    async def _handle_errors(self, request: web.Request) -> web.Response:
        """Return a paginated slice of the error history.

        Query parameters:
            page: 1-based page number (default: 1)
            page_size: errors per page (default: 10, max: 100)
        """
        try:
            page = max(1, int(request.rel_url.query.get("page", "1")))
        except ValueError:
            page = 1
        try:
            page_size = min(100, max(1, int(request.rel_url.query.get("page_size", "10"))))
        except ValueError:
            page_size = 10
        errors = self.status_data["errors_history"]
        total = len(errors)
        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        start = (page - 1) * page_size
        return web.json_response(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "errors": errors[start : start + page_size],
            },
        )

    async def _handle_gallery(self, request: web.Request) -> web.Response:
        """Return a paginated slice of the gallery image history.

        Full-resolution ``base64`` is stripped from entries that have a ``thumbnail``
        so that the grid payload is small (thumbnails only).  Entries without a
        thumbnail keep their ``base64`` as a fallback.  The full image can be
        fetched on demand via ``/api/gallery/image``.

        Query parameters:
            page: 1-based page number (default: 1)
            page_size: images per page (default: 96, max: 96)
            metadata_only: if "true"/"1", strip both ``thumbnail`` and ``base64`` so
                only lightweight metadata (gallery_id, timestamp, model) is returned.
                Use this to render the page skeleton quickly; images can then be
                fetched individually via ``/api/gallery/image``.
        """
        try:
            page = max(1, int(request.rel_url.query.get("page", "1")))
        except ValueError:
            page = 1
        try:
            page_size = min(96, max(1, int(request.rel_url.query.get("page_size", "96"))))
        except ValueError:
            page_size = 96
        metadata_only = request.rel_url.query.get("metadata_only", "").lower() in ("1", "true", "yes")

        # Gallery is stored oldest-first (insertion order); serve newest-first to the UI.
        images_reversed = list(reversed(self._gallery_dict.values()))
        total = len(self._gallery_dict)
        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        start = (page - 1) * page_size
        page_images = images_reversed[start : start + page_size]

        if metadata_only:
            # Strip all image data so only lightweight metadata is returned.
            # The UI uses this to render the page skeleton immediately, then
            # fetches each thumbnail individually via /api/gallery/image.
            page_images = [{k: v for k, v in dict(entry).items() if k not in ("base64", "thumbnail")} for entry in page_images]
        else:
            # Strip the full-resolution base64 from entries that already have a thumbnail.
            # This drastically reduces the response payload for the gallery grid view.
            # Entries without a thumbnail keep their base64 as a display fallback.
            # All entries are copied so the originals in _gallery_dict are not mutated.
            page_images = [
                ({k: v for k, v in entry.items() if k != "base64"} if entry.get("thumbnail") else dict(entry))
                for entry in page_images
            ]

        return web.json_response(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "images": page_images,
            },
        )

    async def _handle_gallery_image(self, request: web.Request) -> web.Response:
        """Return a single gallery image by its stable ``gallery_id``.

        Used by the overlay viewer to lazily fetch full-resolution images only when
        the user actually opens them, and by the gallery grid to progressively load
        thumbnails one by one after the page skeleton is rendered.

        Query parameters:
            id: stable ``gallery_id`` assigned when the image was added (required)
            thumbnail_only: if "true"/"1", strip the full-resolution ``base64`` from
                the response and return only the ``thumbnail`` (plus metadata).  Use
                this when loading the gallery grid to avoid transferring large
                full-resolution images for every grid item.
        """
        try:
            gallery_id = int(request.rel_url.query.get("id", ""))
        except ValueError:
            raise web.HTTPBadRequest(reason="Invalid or missing id parameter") from None
        thumbnail_only = request.rel_url.query.get("thumbnail_only", "").lower() in ("1", "true", "yes")

        entry = self._gallery_dict.get(gallery_id)
        if entry is None:
            raise web.HTTPNotFound(reason="Gallery image not found")
        if thumbnail_only and entry.get("thumbnail"):
            # When a thumbnail is available, omit the full-resolution base64
            # to keep the payload small for the gallery grid.
            return web.json_response({k: v for k, v in entry.items() if k != "base64"})
        # If no thumbnail is available (e.g. Pillow not installed), fall back to
        # returning the full entry including base64 so the client can still render.
        return web.json_response(entry)

    def add_gallery_image(self, image_entry: dict[str, Any]) -> None:
        """Append one image entry to the gallery history.

        A small JPEG thumbnail is generated and stored under the ``thumbnail`` key so
        that the gallery grid can load much faster than serving the full-resolution PNG.
        The original full-resolution ``base64`` value is preserved for the overlay viewer.

        Args:
            image_entry: dict with keys ``base64``, ``timestamp``, and ``model``.
        """
        entry = dict(image_entry)
        entry["gallery_id"] = self._next_gallery_id
        self._next_gallery_id += 1
        if _PIL_AVAILABLE and entry.get("base64"):
            try:
                raw = base64.b64decode(entry["base64"])
                with io.BytesIO(raw) as img_bytes, _PILImage.open(img_bytes) as img:
                    img.thumbnail((_THUMBNAIL_MAX_PX, _THUMBNAIL_MAX_PX), _PILImage.LANCZOS)
                    with io.BytesIO() as buf:
                        img.convert("RGB").save(buf, format="JPEG", quality=75)
                        entry["thumbnail"] = base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to generate gallery thumbnail: {}", exc)
        self._gallery_dict[entry["gallery_id"]] = entry
        self.status_data["images_count"] = len(self._gallery_dict)

    def update_status(
        self,
        worker_name: str | None = None,
        horde_username: str | None = None,
        jobs_popped: int | None = None,
        jobs_queued: int | None = None,
        time_without_jobs: float | None = None,
        jobs_completed: int | None = None,
        jobs_faulted: int | None = None,
        processes_recovered: int | None = None,
        kudos_earned_session: float | None = None,
        kudos_per_hour: float | None = None,
        images_per_hour: float | None = None,
        current_job: dict[str, Any] | None = None,
        job_queue: list[dict[str, Any]] | None = None,
        processes: list[dict[str, Any]] | None = None,
        models_loaded: list[str] | None = None,
        ram_usage_mb: float | None = None,
        vram_usage_mb: float | None = None,
        total_vram_mb: float | None = None,
        cpu_usage_percent: float | None = None,
        cpu_cores_count: int | None = None,
        gpu_usage_percent: float | None = None,
        maintenance_mode: bool | None = None,
        user_kudos_total: float | None = None,
        last_image_base64: list[str] | None = None,
        last_image_submission_timestamp: float | None = None,
        console_logs: list[str] | None = None,
        faulted_jobs_history: list[dict[str, Any]] | None = None,
        errors_history: list[str] | None = None,
        user_details: dict[str, Any] | None = None,
    ) -> None:
        """Update the status data for the web UI.

        Args:
            worker_name: The name of the worker
            horde_username: The horde username
            jobs_popped: Total number of jobs popped this session
            jobs_queued: Currently queued jobs count
            time_without_jobs: Total seconds spent with no active jobs this session
            jobs_completed: Total number of jobs completed this session
            jobs_faulted: Total number of jobs faulted this session
            processes_recovered: Total number of jobs recovered this session
            kudos_earned_session: Total kudos earned this session
            kudos_per_hour: Current kudos per hour rate
            images_per_hour: Current images generated per hour rate
            current_job: Information about the current job being processed
            job_queue: List of jobs in the queue
            processes: List of process information
            models_loaded: List of currently loaded models
            ram_usage_mb: RAM usage in MB
            vram_usage_mb: VRAM usage in MB
            total_vram_mb: Total VRAM in MB
            cpu_usage_percent: CPU usage percentage
            cpu_cores_count: Number of CPU cores
            gpu_usage_percent: GPU usage percentage
            maintenance_mode: Whether worker is in maintenance mode
            user_kudos_total: Total kudos accumulated by the user
            last_image_base64: List of base64 encoded last generated images (supports batch jobs)
            last_image_submission_timestamp: Timestamp when the last image was submitted
            console_logs: Recent console log messages
            faulted_jobs_history: List of faulted jobs with details
            errors_history: List of recent error messages
            user_details: Extended user details from the Horde API (worker_count, trusted, moderator, etc.)
        """
        if worker_name is not None:
            self.status_data["worker_name"] = worker_name
        if horde_username is not None:
            self.status_data["horde_username"] = horde_username
        if jobs_popped is not None:
            self.status_data["jobs_popped"] = jobs_popped
        if jobs_queued is not None:
            self.status_data["jobs_queued"] = jobs_queued
        if time_without_jobs is not None:
            self.status_data["time_without_jobs"] = time_without_jobs
        if jobs_completed is not None:
            self.status_data["jobs_completed"] = jobs_completed
        if jobs_faulted is not None:
            self.status_data["jobs_faulted"] = jobs_faulted
        if processes_recovered is not None:
            self.status_data["processes_recovered"] = processes_recovered
        if kudos_earned_session is not None:
            self.status_data["kudos_earned_session"] = kudos_earned_session
        if kudos_per_hour is not None:
            self.status_data["kudos_per_hour"] = kudos_per_hour
        if images_per_hour is not None:
            self.status_data["images_per_hour"] = images_per_hour
        if current_job is not None:
            self.status_data["current_job"] = current_job
        if job_queue is not None:
            self.status_data["job_queue"] = job_queue
        if processes is not None:
            self.status_data["processes"] = processes
        if models_loaded is not None:
            self.status_data["models_loaded"] = models_loaded
        if ram_usage_mb is not None:
            self.status_data["ram_usage_mb"] = ram_usage_mb
        if vram_usage_mb is not None:
            self.status_data["vram_usage_mb"] = vram_usage_mb
        if total_vram_mb is not None:
            self.status_data["total_vram_mb"] = total_vram_mb
        if cpu_usage_percent is not None:
            self.status_data["cpu_usage_percent"] = cpu_usage_percent
        if cpu_cores_count is not None:
            self.status_data["cpu_cores_count"] = cpu_cores_count
        if gpu_usage_percent is not None:
            self.status_data["gpu_usage_percent"] = gpu_usage_percent
        if maintenance_mode is not None:
            self.status_data["maintenance_mode"] = maintenance_mode
        if user_kudos_total is not None:
            self.status_data["user_kudos_total"] = user_kudos_total
        if last_image_base64 is not None:
            self.status_data["last_image_base64"] = list(last_image_base64)
        if last_image_submission_timestamp is not None:
            self.status_data["last_image_submission_timestamp"] = last_image_submission_timestamp
        if console_logs is not None:
            self.status_data["console_logs"] = console_logs
        if faulted_jobs_history is not None:
            self.status_data["faulted_jobs_history"] = faulted_jobs_history
        if errors_history is not None:
            self.status_data["errors_history"] = list(errors_history)
        if user_details is not None:
            self.status_data["user_details"] = user_details

        # Update uptime
        self.status_data["uptime"] = time.time() - self.status_data["session_start_time"]

    async def start(self) -> None:
        """Start the web server."""
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, "0.0.0.0", self.port)
            await self.site.start()
            logger.info(f"Web UI started at http://0.0.0.0:{self.port}")
        except Exception as e:
            logger.error(f"Failed to start web UI server: {e}")
            raise

    async def stop(self) -> None:
        """Stop the web server."""
        try:
            if self.site:
                await self.site.stop()
            if self.runner:
                await self.runner.cleanup()
            logger.info("Web UI server stopped")
        except Exception as e:
            logger.error(f"Error stopping web UI server: {e}")
