"""Web server for the Horde Worker status UI."""

import math
import time
from typing import Any

from aiohttp import web
from loguru import logger


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
            "jobs_completed": 0,
            "jobs_faulted": 0,
            "processes_recovered": 0,
            "kudos_earned_session": 0.0,
            "kudos_per_hour": 0.0,
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
        }

        # Gallery image data stored separately – NOT included in /api/status to avoid
        # sending large base64 payloads on every poll.  Served via /api/gallery instead.
        self._gallery_data: list[dict[str, Any]] = []

        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up the web server routes."""
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/api/status", self._handle_status)
        self.app.router.add_get("/api/gallery", self._handle_gallery)
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
        .sidebar-footer { padding: 14px 20px; border-top: 1px solid rgba(255,255,255,0.07); flex-shrink: 0; }
        .sidebar-footer p { color: var(--text-muted); font-size: 0.72rem; }
        .sidebar-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 99; backdrop-filter: blur(1px); }
        .sidebar-overlay.active { display: block; }

        /* ---- Mobile navbar ---- */
        .mobile-navbar { display: none; position: fixed; top: 0; left: 0; right: 0; height: 54px; background: var(--sidebar-bg); align-items: center; padding: 0 14px; z-index: 200; gap: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.25); }
        .hamburger-btn { background: none; border: none; color: var(--text-light); font-size: 1.3rem; cursor: pointer; padding: 6px; border-radius: 6px; line-height: 1; transition: background 0.15s; }
        .hamburger-btn:hover { background: rgba(255,255,255,0.08); }
        .mobile-title { color: var(--text-light); font-size: 0.95rem; font-weight: 600; flex: 1; }

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

        .console-container { background: #0f172a; border-radius: 8px; padding: 12px 14px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', Consolas, 'Lucida Console', monospace; font-size: 0.8rem; color: #e2e8f0; line-height: 1.55; }

        /* ---- Gallery ---- */
        .image-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; width: 100%; }
        .image-grid-item { position: relative; overflow: hidden; border-radius: 8px; background: #f1f5f9; aspect-ratio: 1; display: flex; align-items: center; justify-content: center; }
        .image-grid-item img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 8px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; display: block; }
        .image-grid-item img:hover { transform: scale(1.04); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .image-grid-item .image-timestamp { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.6); color: #e2e8f0; font-size: 0.65rem; padding: 3px 6px; text-align: center; border-radius: 0 0 8px 8px; opacity: 0; transition: opacity 0.2s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .image-grid-item:hover .image-timestamp { opacity: 1; }

        .last-image-container { display: flex; align-items: center; justify-content: center; min-height: 160px; overflow: hidden; border-radius: 8px; }
        .single-image { max-width: 100%; max-height: 380px; width: 100%; height: auto; object-fit: contain; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); display: block; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; }
        .single-image:hover { transform: scale(1.02); box-shadow: 0 4px 16px rgba(0,0,0,0.18); }

        /* ---- Image overlay ---- */
        .image-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 1000; justify-content: center; align-items: center; padding: 20px; }
        .image-overlay.active { display: flex; }
        .image-overlay-content { position: relative; max-width: 95%; max-height: 95%; display: flex; justify-content: center; align-items: center; }
        .image-overlay img { max-width: 100%; max-height: 90vh; object-fit: contain; border-radius: 8px; box-shadow: 0 8px 40px rgba(0,0,0,0.6); }
        .image-overlay-close { position: absolute; top: -44px; right: 0; background: var(--accent); color: white; border: none; padding: 8px 18px; font-size: 0.9rem; font-weight: 600; border-radius: 8px; cursor: pointer; transition: background 0.2s; }
        .image-overlay-close:hover { background: var(--accent-hover); }
        .image-overlay-nav { position: fixed; top: 50%; transform: translateY(-50%); background: rgba(0,0,0,0.5); color: white; border: none; padding: 12px 18px; font-size: 1.8rem; font-weight: 700; border-radius: 8px; cursor: pointer; transition: background 0.2s; z-index: 1001; user-select: none; line-height: 1; display: none; }
        .image-overlay-nav:hover { background: rgba(0,0,0,0.85); }
        .image-overlay-nav:disabled { opacity: 0.3; cursor: default; }
        .image-overlay-nav.prev { left: 12px; }
        .image-overlay-nav.next { right: 12px; }
        .image-overlay-counter { position: absolute; bottom: -32px; left: 50%; transform: translateX(-50%); color: rgba(255,255,255,0.8); font-size: 0.85rem; white-space: nowrap; font-weight: 500; }

        /* ---- Faulted jobs ---- */
        .faulted-jobs-list { display: flex; flex-direction: column; gap: 0; }
        .faulted-job-item { background: #fff5f5; border: 1px solid #fecaca; border-left: 3px solid var(--error); border-radius: 8px; padding: 13px; margin-bottom: 10px; }
        .faulted-job-item:last-child { margin-bottom: 0; }
        .faulted-job-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 9px; padding-bottom: 7px; border-bottom: 1px solid #fecaca; flex-wrap: wrap; gap: 6px; }
        .faulted-job-id { font-family: monospace; color: #dc2626; font-weight: 700; font-size: 0.85rem; word-break: break-all; }
        .faulted-job-time { color: #94a3b8; font-size: 0.78rem; flex-shrink: 0; }
        .faulted-job-details { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; }
        .faulted-job-detail { display: flex; flex-direction: column; }
        .faulted-job-label { color: #94a3b8; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }
        .faulted-job-value { color: #334155; font-weight: 500; font-size: 0.85rem; word-break: break-word; }
        .faulted-job-lora { background: #fef3c7; color: #92400e; padding: 2px 7px; border-radius: 4px; font-size: 0.78rem; display: inline-block; margin: 2px; }
        .faulted-job-controlnet { background: #dbeafe; color: #1e40af; padding: 2px 7px; border-radius: 4px; font-size: 0.78rem; display: inline-block; font-weight: 600; }
        .faulted-job-section { margin-top: 8px; }
        .faulted-job-section-label { display: block; margin-bottom: 4px; }

        /* ---- Errors ---- */
        .errors-list { display: flex; flex-direction: column; }
        .error-item { background: #fff5f5; border: 1px solid #fecaca; border-left: 3px solid var(--error); border-radius: 6px; padding: 9px 13px; font-family: 'Courier New', monospace; font-size: 0.78rem; color: #7f1d1d; white-space: pre-wrap; word-break: break-word; margin-bottom: 5px; }
        .error-item:last-child { margin-bottom: 0; }

        .pagination-controls { display: flex; align-items: center; justify-content: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
        .pagination-controls button { background: var(--accent); color: white; border: none; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 0.82rem; font-weight: 500; transition: background 0.15s; }
        .pagination-controls button:hover:not(:disabled) { background: var(--accent-hover); }
        .pagination-controls button:disabled { background: #c7d2fe; cursor: default; }
        .pagination-info { font-size: 0.82rem; color: #64748b; }

        .scrollable { max-height: 260px; overflow-y: auto; }
        .scrollable-tall { max-height: 400px; overflow-y: auto; }

        #loading { display: flex; align-items: center; justify-content: center; height: 80vh; flex-direction: column; gap: 14px; }
        .loading-spinner { width: 36px; height: 36px; border: 3px solid #e2e8f0; border-top-color: var(--accent); border-radius: 50%; animation: spin 0.75s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .loading-text { color: #64748b; font-size: 0.9rem; }

        #update-time { font-size: 0.73rem; color: #94a3b8; text-align: right; margin-bottom: 10px; }
        .empty-state { text-align: center; padding: 24px 16px; color: #94a3b8; font-size: 0.87rem; }
        .empty-state-icon { font-size: 1.8rem; margin-bottom: 6px; display: block; }

        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

        @media (max-width: 1200px) { .grid-4 { grid-template-columns: repeat(2, 1fr); } .grid-3 { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 768px) { .sidebar { transform: translateX(-100%); } .sidebar.open { transform: translateX(0); } .mobile-navbar { display: flex; } .mobile-resources { display: flex; } .main-content { margin-left: 0; padding-top: 80px; } .topbar { display: none; } .content-area { padding: 14px 12px; } .grid-4 { grid-template-columns: repeat(2, 1fr); } .grid-3 { grid-template-columns: 1fr; } .grid-2 { grid-template-columns: 1fr; } .grid-3-popped { grid-template-columns: repeat(2, 1fr); } }
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
        .topbar-res-bar { height: 100%; border-radius: 2px; transition: width 0.4s ease; }
        .topbar-res-bar.cpu  { background: #6366f1; }
        .topbar-res-bar.gpu  { background: #10b981; }
        .topbar-res-bar.vram { background: #f59e0b; }

        /* ---- Mobile resources sub-bar ---- */
        .mobile-resources { display: none; position: fixed; top: 54px; left: 0; right: 0; height: 26px; background: #12162a; align-items: center; padding: 0 14px; gap: 14px; z-index: 199; border-bottom: 1px solid rgba(255,255,255,0.06); }
        .mobile-res-chip { color: var(--text-muted); font-size: 0.7rem; font-weight: 600; font-family: 'Courier New', monospace; }

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
        [data-theme="dark"] #update-time { color: #64748b; }
        [data-theme="dark"] .empty-state { color: #64748b; }
        [data-theme="dark"] .image-grid-item { background: #151e2e; }
        [data-theme="dark"] .faulted-job-item { background: #1a1010; border-color: #7f1d1d; }
        [data-theme="dark"] .faulted-job-value { color: #cbd5e1; }
        [data-theme="dark"] .faulted-job-label { color: #64748b; }
        [data-theme="dark"] .error-item { background: #1a1010; border-color: #7f1d1d; color: #fca5a5; }

    </style>
</head>
<body>
    <nav class="mobile-navbar" aria-label="Mobile navigation">
        <button class="hamburger-btn" onclick="toggleSidebar()" aria-label="Toggle sidebar">&#9776;</button>
        <span class="mobile-title">&#127912; Horde Worker</span>
        <span id="mobile-status-badge"></span>
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
            <button class="nav-item" onclick="showPage('logs', this)" id="nav-logs">
                <span class="nav-icon">&#128203;</span> Logs
            </button>
        </nav>
        <div class="sidebar-footer">
            <p id="sidebar-update-time">Last updated: Never</p>
        </div>
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
                <div id="update-time">Last updated: Never</div>

                <!-- OVERVIEW PAGE -->
                <div class="page active" id="page-overview">
                    <div class="grid-4" style="margin-bottom: 14px;">
                        <div class="stat-card"><div class="stat-card-label">Total Kudos</div><div class="stat-card-value success" id="user-kudos-total">-</div></div>
                        <div class="stat-card"><div class="stat-card-label">Kudos / Hour</div><div class="stat-card-value accent" id="kudos-per-hour">0</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Popped</div><div class="stat-card-value accent" id="jobs-popped">0</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Completed</div><div class="stat-card-value success" id="jobs-completed">0</div></div>
                    </div>
                    <div class="grid-3 grid-3-popped" style="margin-bottom: 14px;">
                        <div class="stat-card"><div class="stat-card-label">Jobs Queued</div><div class="stat-card-value" id="jobs-queued">0</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Recovered</div><div class="stat-card-value warning" id="processes-recovered">0</div></div>
                        <div class="stat-card"><div class="stat-card-label">Jobs Faulted</div><div class="stat-card-value error" id="jobs-faulted">0</div></div>
                    </div>
                    <div class="grid-2" style="margin-bottom: 14px;">
                        <div class="card">
                            <div class="card-header"><span class="card-title">&#9889; Current Job</span></div>
                            <div id="overview-current-job"><div class="empty-state"><span class="empty-state-icon">&#9203;</span>No job in progress</div></div>
                        </div>
                        <div class="card">
                            <div class="card-header"><span class="card-title">&#128444; Last Images</span></div>
                            <div style="font-size:0.75rem;color:#94a3b8;margin-bottom:10px;"><span id="overview-image-time">No image generated yet</span></div>
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
                            <div id="gallery-empty" class="empty-state"><span class="empty-state-icon">&#128444;</span>No images generated yet</div>
                            <div id="gallery-grid" class="image-grid" style="display:none;"></div>
                            <div class="pagination-controls" id="gallery-pagination" style="display:none;">
                                <button id="gallery-prev" onclick="galleryChangePage(-1)" disabled>&#8249; Prev</button>
                                <span class="pagination-info" id="gallery-page-info">Page 1 of 1</span>
                                <button id="gallery-next" onclick="galleryChangePage(1)">Next &#8250;</button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- LOGS PAGE -->
                <div class="page" id="page-logs">
                    <div class="section">
                        <div class="section-header"><span class="section-title">&#128203; Console</span></div>
                        <div class="card" style="padding:0;overflow:hidden;">
                            <div id="console-logs" class="console-container" style="border-radius:12px;"><div style="text-align:center;color:#475569;padding:18px;">No logs available</div></div>
                        </div>
                    </div>
                    <div class="section">
                        <div class="section-header"><span class="section-title">&#9888; Faulted Jobs</span><span class="section-count" id="faulted-jobs-count">0</span></div>
                        <div class="card">
                            <div id="faulted-jobs" class="faulted-jobs-list"><div class="empty-state"><span class="empty-state-icon">&#10003;</span>No faulted jobs</div></div>
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
        function showPage(pageId, navEl) {
            document.querySelectorAll('.page').forEach(function(p) { p.classList.remove('active'); });
            var page = document.getElementById('page-' + pageId);
            if (page) page.classList.add('active');
            document.querySelectorAll('.nav-item').forEach(function(item) { item.classList.remove('active'); });
            if (navEl) navEl.classList.add('active');
            if (window.innerWidth < 768) closeSidebar();
            if (pageId === 'gallery') fetchGalleryPage(galleryCurrentPage);
        }
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
            document.getElementById('overlay-image').src = imageSrc;
            document.getElementById('image-overlay').classList.add('active');
            _updateOverlayNav();
        }
        function overlayNavigate(delta) {
            const ni = overlayIndex + delta;
            if (ni < 0 || ni >= overlayImages.length) return;
            overlayIndex = ni;
            document.getElementById('overlay-image').src = overlayImages[overlayIndex];
            _updateOverlayNav();
        }
        function closeImageOverlay() { document.getElementById('image-overlay').classList.remove('active'); overlayImages = []; overlayIndex = -1; }
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
        const ERRORS_PAGE_SIZE = 10;
        let errorsCurrentPage = 1, errorsData = [];
        function renderErrorsPage() {
            const ed = document.getElementById('errors-history'), pi = document.getElementById('errors-page-info'),
                  pb = document.getElementById('errors-prev'), nb = document.getElementById('errors-next'),
                  pag = document.getElementById('errors-pagination'), cnt = document.getElementById('errors-count');
            if (errorsData.length === 0) {
                ed.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#10003;</span>No errors</div>';
                pag.style.display = 'none'; cnt.textContent = '0'; return;
            }
            const tp = Math.max(1, Math.ceil(errorsData.length / ERRORS_PAGE_SIZE));
            errorsCurrentPage = Math.min(Math.max(1, errorsCurrentPage), tp);
            const start = (errorsCurrentPage - 1) * ERRORS_PAGE_SIZE;
            ed.innerHTML = errorsData.slice(start, start + ERRORS_PAGE_SIZE).map(err => '<div class="error-item">'+escapeHtml(err)+'</div>').join('');
            pi.textContent = 'Page '+errorsCurrentPage+' of '+tp;
            pb.disabled = errorsCurrentPage <= 1; nb.disabled = errorsCurrentPage >= tp;
            pag.style.display = 'flex'; cnt.textContent = errorsData.length;
        }
        function errorsChangePage(delta) {
            errorsCurrentPage = Math.min(Math.max(1, errorsCurrentPage + delta), Math.max(1, Math.ceil(errorsData.length / ERRORS_PAGE_SIZE)));
            renderErrorsPage();
        }
        const GALLERY_PAGE_SIZE = 20;
        let galleryCurrentPage = 1, galleryTotalPages = 1, galleryTotalImages = 0, galleryFetchInProgress = false;
        function renderGalleryPage(images, total, page, totalPages) {
            galleryTotalImages = total; galleryCurrentPage = page; galleryTotalPages = totalPages;
            const grid = document.getElementById('gallery-grid'), empty = document.getElementById('gallery-empty'),
                  pi = document.getElementById('gallery-page-info'), pb = document.getElementById('gallery-prev'),
                  nb = document.getElementById('gallery-next'), pag = document.getElementById('gallery-pagination'),
                  cnt = document.getElementById('gallery-count');
            cnt.textContent = total;
            if (images.length === 0) {
                grid.style.display = 'none'; grid.innerHTML = ''; empty.style.display = '';
                pag.style.display = 'none'; return;
            }
            empty.style.display = 'none'; grid.style.display = '';
            const gallerySrcs = images.map(img => 'data:image/png;base64,'+img.base64);
            grid.innerHTML = images.map((img, idx) => {
                const src = gallerySrcs[idx];
                const ts = formatTimestamp(img.timestamp), model = img.model ? escapeHtml(img.model) : '';
                const cap = [ts, model].filter(Boolean).join(' \u00b7 ');
                return '<div class="image-grid-item"><img src="'+src+'" alt="Generated image" data-fullsize="'+src+'" data-idx="'+idx+'" />'+
                    (cap ? '<div class="image-timestamp">'+cap+'</div>' : '')+'</div>';
            }).join('');
            grid.querySelectorAll('img[data-fullsize]').forEach(img => { img.onclick = function() { openImageOverlay(this.getAttribute('data-fullsize'), gallerySrcs, parseInt(this.getAttribute('data-idx') || '0', 10)); }; });
            const tp = Math.max(1, totalPages);
            pi.textContent = 'Page '+page+' of '+tp;
            pb.disabled = page <= 1; nb.disabled = page >= tp;
            pag.style.display = tp > 1 ? 'flex' : 'none';
        }
        function fetchGalleryPage(page) {
            if (galleryFetchInProgress) return;
            galleryFetchInProgress = true;
            fetch('/api/gallery?page='+page+'&page_size='+GALLERY_PAGE_SIZE)
                .then(r => { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
                .then(data => { renderGalleryPage(data.images, data.total, data.page, data.total_pages); })
                .catch(err => { console.error('Gallery fetch error:', err); })
                .finally(() => { galleryFetchInProgress = false; });
        }
        function galleryChangePage(delta) {
            const newPage = Math.min(Math.max(1, galleryCurrentPage + delta), Math.max(1, galleryTotalPages));
            fetchGalleryPage(newPage);
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
        let statusAbortController = null, statusFetchInProgress = false, consecutiveErrors = 0;
        const MAX_CONSECUTIVE_ERRORS = 5;
        function updateStatus() {
            if (statusFetchInProgress) return;
            if (statusAbortController) statusAbortController.abort();
            statusAbortController = new AbortController();
            statusFetchInProgress = true;
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
                    document.getElementById('user-kudos-total').textContent = data.user_kudos_total ? data.user_kudos_total.toLocaleString(undefined, {maximumFractionDigits: 2}) : '-';
                    document.getElementById('kudos-per-hour').textContent = data.kudos_per_hour.toLocaleString(undefined, {maximumFractionDigits: 2});
                    document.getElementById('jobs-popped').textContent = data.jobs_popped;
                    document.getElementById('jobs-completed').textContent = data.jobs_completed;
                    document.getElementById('jobs-faulted').textContent = data.jobs_faulted;
                    document.getElementById('processes-recovered').textContent = data.processes_recovered;
                    document.getElementById('jobs-queued').textContent = data.jobs_queued;
                    const cpu = Math.min(100, Math.round(data.cpu_usage_percent));
                    const gpu = Math.min(100, Math.round(data.gpu_usage_percent));
                    const vram = data.total_vram_mb > 0 ? Math.min(100, Math.round((data.vram_usage_mb / data.total_vram_mb) * 100)) : 0;
                    document.getElementById('topbar-cpu-pct').textContent = cpu+'%';
                    document.getElementById('topbar-cpu-bar').style.width = cpu+'%';
                    document.getElementById('topbar-gpu-pct').textContent = gpu+'%';
                    document.getElementById('topbar-gpu-bar').style.width = gpu+'%';
                    document.getElementById('topbar-vram-pct').textContent = vram+'%';
                    document.getElementById('topbar-vram-bar').style.width = vram+'%';
                    document.getElementById('mobile-cpu').textContent = 'CPU '+cpu+'%';
                    document.getElementById('mobile-gpu').textContent = 'GPU '+gpu+'%';
                    document.getElementById('mobile-vram').textContent = 'VRAM '+vram+'%';
                    const ojd = document.getElementById('overview-current-job');
                    if (data.current_job) {
                        const job = data.current_job;
                        const sd = escapeHtml(job.state || 'N/A');
                        const pv = (job.progress !== null && job.progress !== undefined) ? job.progress : 0;
                        ojd.innerHTML =
                            '<div class="stat-row"><span class="stat-label">Job ID:</span><span class="stat-value" style="font-family:monospace;font-size:0.8rem;">'+escapeHtml(job.id||'N/A')+'</span></div>'+
                            '<div class="stat-row"><span class="stat-label">Model:</span><span class="stat-value">'+escapeHtml(job.model||'N/A')+'</span></div>'+
                            (job.batch_size!=null&&job.batch_size!==undefined?'<div class="stat-row"><span class="stat-label">Batch Size:</span><span class="stat-value">'+escapeHtml(job.batch_size)+'x</span></div>':'')+
                            (job.steps!=null&&job.steps!==undefined?'<div class="stat-row"><span class="stat-label">Steps:</span><span class="stat-value">'+escapeHtml(job.steps)+'</span></div>':'')+
                            (job.width!=null&&job.width!==undefined&&job.height!=null&&job.height!==undefined?'<div class="stat-row"><span class="stat-label">Image Size:</span><span class="stat-value">'+escapeHtml(job.width)+'x'+escapeHtml(job.height)+'</span></div>':'')+
                            (job.sampler!=null&&job.sampler!==undefined?'<div class="stat-row"><span class="stat-label">Sampler:</span><span class="stat-value">'+escapeHtml(job.sampler)+'</span></div>':'')+
                            (job.loras!=null&&job.loras!==undefined&&job.loras.length>0?'<div class="stat-row"><span class="stat-label">LoRAs:</span><span class="stat-value">'+job.loras.map(l=>escapeHtml(l.name||'Unknown')).join(', ')+'</span></div>':'')+
                            '<div class="stat-row"><span class="stat-label">State:</span><span class="job-state-badge">'+sd+'</span></div>'+
                            '<div style="margin-top:14px;"><div class="progress-header"><span class="progress-label">Progress</span><span class="progress-value">'+escapeHtml(pv)+'%</span></div><div class="progress-bar-container" style="height:12px;"><div class="progress-bar" style="width:'+escapeHtml(pv)+'%;height:100%;border-radius:6px;"></div></div></div>';
                    } else {
                        ojd.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#9203;</span>No job in progress</div>';
                    }
                    document.getElementById('overview-image-time').textContent = formatTimeAgo(data.last_image_submission_timestamp);
                    const oic = document.getElementById('overview-image-container');
                    if (data.last_image_base64 && data.last_image_base64.length > 0) {
                        if (data.last_image_base64.length === 1) {
                            const s = 'data:image/png;base64,'+data.last_image_base64[0];
                            oic.innerHTML = '<img src="'+s+'" class="single-image" alt="Last generated image" data-fullsize="'+s+'" />';
                        } else {
                            const gh = data.last_image_base64.slice(0,4).map((b,i) => { const s='data:image/png;base64,'+b; return '<div class="image-grid-item"><img src="'+s+'" alt="Generated image '+(i+1)+'" data-fullsize="'+s+'" /></div>'; }).join('');
                            oic.innerHTML = '<div class="image-grid" style="grid-template-columns:repeat(2,1fr);">'+gh+'</div>';
                        }
                        oic.querySelectorAll('img[data-fullsize]').forEach(img => { img.onclick = function() { openImageOverlay(this.getAttribute('data-fullsize')); }; });
                    } else {
                        oic.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#128444;</span>No image generated yet</div>';
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
                    const fjd = document.getElementById('faulted-jobs'), fjc = document.getElementById('faulted-jobs-count');
                    if (data.faulted_jobs_history && data.faulted_jobs_history.length > 0) {
                        fjc.textContent = data.faulted_jobs_history.length;
                        fjd.innerHTML = data.faulted_jobs_history.map(job => {
                            let ts = 'Unknown time';
                            if (job.time_faulted && !isNaN(job.time_faulted)) { const ft = new Date(job.time_faulted*1000); if (!isNaN(ft.getTime())) ts = ft.toLocaleString(); }
                            let dh = '<div class="faulted-job-details">';
                            dh += '<div class="faulted-job-detail"><span class="faulted-job-label">Model</span><span class="faulted-job-value">'+escapeHtml(job.model)+'</span></div>';
                            if (job.fault_phase) dh += '<div class="faulted-job-detail"><span class="faulted-job-label">Fault Phase</span><span class="faulted-job-value" style="color:#ef4444;font-weight:600;">'+escapeHtml(job.fault_phase)+'</span></div>';
                            if (job.width&&job.height) dh += '<div class="faulted-job-detail"><span class="faulted-job-label">Size</span><span class="faulted-job-value">'+job.width+'x'+job.height+'</span></div>';
                            if (job.steps) dh += '<div class="faulted-job-detail"><span class="faulted-job-label">Steps</span><span class="faulted-job-value">'+job.steps+'</span></div>';
                            if (job.sampler) dh += '<div class="faulted-job-detail"><span class="faulted-job-label">Sampler</span><span class="faulted-job-value">'+escapeHtml(job.sampler)+'</span></div>';
                            if (job.batch_size&&job.batch_size>1) dh += '<div class="faulted-job-detail"><span class="faulted-job-label">Batch</span><span class="faulted-job-value">'+job.batch_size+'x</span></div>';
                            dh += '</div>';
                            let lh = '';
                            if (job.loras&&job.loras.length>0) { lh='<div class="faulted-job-section"><span class="faulted-job-label faulted-job-section-label">LoRAs:</span>'; job.loras.forEach(l=>{lh+='<span class="faulted-job-lora">'+escapeHtml(l.name||'Unknown')+'</span>';}); lh+='</div>'; }
                            let ch = '';
                            if (job.controlnet) ch = '<div class="faulted-job-section"><span class="faulted-job-label faulted-job-section-label">ControlNet:</span><span class="faulted-job-controlnet">'+escapeHtml(job.controlnet)+'</span></div>';
                            return '<div class="faulted-job-item"><div class="faulted-job-header"><span class="faulted-job-id">'+escapeHtml(job.job_id)+'</span><span class="faulted-job-time">'+ts+'</span></div>'+dh+lh+ch+'</div>';
                        }).join('');
                    } else { fjc.textContent = '0'; fjd.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#10003;</span>No faulted jobs</div>'; }
                    errorsData = (data.errors_history && data.errors_history.length > 0) ? data.errors_history : [];
                    if (!data.errors_history || data.errors_history.length === 0) errorsCurrentPage = 1;
                    renderErrorsPage();
                    const cl = document.getElementById('console-logs');
                    if (data.console_logs && data.console_logs.length > 0) {
                        const atb = isScrolledToBottom(cl, SCROLL_TOLERANCE_PX);
                        cl.innerHTML = data.console_logs.map(log => '<div style="margin: 2px 0; white-space: pre-wrap; word-break: break-word;">'+ansiToHtml(log)+'</div>').join('');
                        if (atb) cl.scrollTop = cl.scrollHeight;
                    } else { cl.innerHTML = '<div style="text-align:center;color:#475569;padding:18px;">No logs available</div>'; }
                    const nowStr = new Date().toLocaleTimeString();
                    document.getElementById('update-time').textContent = 'Last updated: ' + nowStr;
                    document.getElementById('sidebar-update-time').textContent = 'Last updated: ' + nowStr;
                })
                .catch(error => {
                    if (error.name === 'AbortError') return;
                    consecutiveErrors++;
                    console.error('Error fetching status:', error);
                    if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS)
                        console.warn('Failed to fetch status '+consecutiveErrors+' times in a row. Check server connection.');
                })
                .finally(() => { statusFetchInProgress = false; statusAbortController = null; });
        }
        const DEFAULT_UPDATE_INTERVAL_MS = 1000;
        async function initializeUpdates() {
            try {
                const config = await (await fetch('/api/config')).json();
                const ui = config.update_interval_ms || DEFAULT_UPDATE_INTERVAL_MS;
                updateStatus(); setInterval(updateStatus, ui);
            } catch (e) {
                console.error('Error fetching config:', e);
                updateStatus(); setInterval(updateStatus, DEFAULT_UPDATE_INTERVAL_MS);
            }
        }
        initializeUpdates();
    </script>
</body>
</html>
        """
        return web.Response(text=html, content_type="text/html")

    async def _handle_status(self, request: web.Request) -> web.Response:
        """Handle status API request."""
        return web.json_response(self.status_data)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle health check request."""
        return web.json_response({"status": "ok"})

    async def _handle_gallery(self, request: web.Request) -> web.Response:
        """Return a paginated slice of the gallery image history.

        Query parameters:
            page: 1-based page number (default: 1)
            page_size: images per page (default: 20, max: 100)
        """
        try:
            page = max(1, int(request.rel_url.query.get("page", "1")))
        except ValueError:
            page = 1
        try:
            page_size = min(100, max(1, int(request.rel_url.query.get("page_size", "20"))))
        except ValueError:
            page_size = 20

        # Gallery is stored oldest-first; serve newest-first to the UI.
        images_reversed = list(reversed(self._gallery_data))
        total = len(images_reversed)
        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        start = (page - 1) * page_size
        return web.json_response(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "images": images_reversed[start : start + page_size],
            }
        )

    def add_gallery_image(self, image_entry: dict[str, Any]) -> None:
        """Append one image entry to the gallery and keep at most 200 entries.

        Args:
            image_entry: dict with keys ``base64``, ``timestamp``, and ``model``.
        """
        self._gallery_data.append(image_entry)
        if len(self._gallery_data) > 200:
            self._gallery_data = self._gallery_data[-200:]
        self.status_data["images_count"] = len(self._gallery_data)

    def update_status(
        self,
        worker_name: str | None = None,
        horde_username: str | None = None,
        jobs_popped: int | None = None,
        jobs_queued: int | None = None,
        jobs_completed: int | None = None,
        jobs_faulted: int | None = None,
        processes_recovered: int | None = None,
        kudos_earned_session: float | None = None,
        kudos_per_hour: float | None = None,
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
    ) -> None:
        """Update the status data for the web UI.

        Args:
            worker_name: The name of the worker
            horde_username: The horde username
            jobs_popped: Total number of jobs popped this session
            jobs_queued: Currently queued jobs count
            jobs_completed: Total number of jobs completed this session
            jobs_faulted: Total number of jobs faulted this session
            processes_recovered: Total number of jobs recovered this session
            kudos_earned_session: Total kudos earned this session
            kudos_per_hour: Current kudos per hour rate
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
        """
        if worker_name is not None:
            self.status_data["worker_name"] = worker_name
        if horde_username is not None:
            self.status_data["horde_username"] = horde_username
        if jobs_popped is not None:
            self.status_data["jobs_popped"] = jobs_popped
        if jobs_queued is not None:
            self.status_data["jobs_queued"] = jobs_queued
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
