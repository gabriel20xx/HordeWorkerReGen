"""Web server for the Horde Worker status UI."""

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
        }

        self._setup_routes()

    def _setup_routes(self) -> None:
        """Set up the web server routes."""
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/api/status", self._handle_status)
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
            top: 0;
            left: 0;
            height: 100vh;
            display: flex;
            flex-direction: column;
            z-index: 100;
            transition: transform 0.28s cubic-bezier(.4,0,.2,1);
            overflow-y: auto;
        }

        .sidebar-logo {
            padding: 22px 20px 18px;
            border-bottom: 1px solid rgba(255,255,255,0.07);
            flex-shrink: 0;
        }

        .sidebar-logo h1 {
            color: var(--text-light);
            font-size: 1.15rem;
            font-weight: 700;
            letter-spacing: 0.3px;
        }

        .sidebar-logo p {
            color: var(--text-muted);
            font-size: 0.75rem;
            margin-top: 3px;
        }

        .sidebar-nav { flex: 1; padding: 12px 0; }

        .nav-section-label {
            color: var(--text-muted);
            font-size: 0.67rem;
            font-weight: 700;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            padding: 10px 20px 4px;
        }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 9px 20px;
            color: var(--text-muted);
            text-decoration: none;
            font-size: 0.875rem;
            font-weight: 500;
            transition: background 0.15s, color 0.15s, border-color 0.15s;
            cursor: pointer;
            border-left: 3px solid transparent;
            user-select: none;
            background: none;
            border-top: none;
            border-right: none;
            border-bottom: none;
            width: 100%;
            text-align: left;
        }

        .nav-item:hover {
            background: var(--sidebar-hover);
            color: var(--text-light);
        }

        .nav-item.active {
            background: var(--sidebar-hover);
            color: var(--text-light);
            border-left-color: var(--accent);
        }

        .nav-icon { font-size: 1rem; width: 18px; text-align: center; flex-shrink: 0; }

        .sidebar-footer {
            padding: 14px 20px;
            border-top: 1px solid rgba(255,255,255,0.07);
            flex-shrink: 0;
        }

        .sidebar-footer p { color: var(--text-muted); font-size: 0.72rem; }

        /* ---- Sidebar overlay (mobile) ---- */
        .sidebar-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.55);
            z-index: 99;
            backdrop-filter: blur(1px);
        }
        .sidebar-overlay.active { display: block; }

        /* ---- Mobile top navbar ---- */
        .mobile-navbar {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0;
            height: 54px;
            background: var(--sidebar-bg);
            align-items: center;
            padding: 0 14px;
            z-index: 200;
            gap: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.25);
        }

        .hamburger-btn {
            background: none;
            border: none;
            color: var(--text-light);
            font-size: 1.3rem;
            cursor: pointer;
            padding: 6px;
            border-radius: 6px;
            line-height: 1;
            transition: background 0.15s;
        }
        .hamburger-btn:hover { background: rgba(255,255,255,0.08); }

        .mobile-title { color: var(--text-light); font-size: 0.95rem; font-weight: 600; flex: 1; }

        /* ---- Main content ---- */
        .main-content {
            margin-left: var(--sidebar-width);
            flex: 1;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            min-width: 0;
        }

        /* ---- Top bar (desktop) ---- */
        .topbar {
            background: white;
            border-bottom: 1px solid var(--border);
            padding: 14px 24px;
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
            flex-shrink: 0;
        }

        .topbar-worker { flex: 1; min-width: 0; }
        .topbar-worker-name {
            font-size: 1.15rem;
            font-weight: 700;
            color: #1e293b;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .topbar-worker-sub { font-size: 0.82rem; color: #64748b; margin-top: 2px; }
        .topbar-meta { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .topbar-uptime { font-size: 0.82rem; color: #64748b; }

        /* ---- Status badges ---- */
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.4px;
        }
        .status-badge::before {
            content: '';
            width: 6px;
            height: 6px;
            border-radius: 50%;
            display: inline-block;
        }
        .status-active { background: #d1fae5; color: #065f46; }
        .status-active::before { background: #10b981; }
        .status-maintenance { background: #fef3c7; color: #92400e; }
        .status-maintenance::before { background: #f59e0b; animation: pulse-dot 1.5s ease-in-out infinite; }

        @keyframes pulse-dot { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

        /* ---- Content area ---- */
        .content-area { padding: 22px 24px; flex: 1; }

        /* ---- Section ---- */
        .section { margin-bottom: 30px; scroll-margin-top: 24px; }
        .section-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
        .section-title {
            font-size: 0.82rem;
            font-weight: 700;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .section-count {
            background: #e2e8f0;
            color: #475569;
            font-size: 0.72rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 20px;
        }

        /* ---- Card ---- */
        .card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 18px 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.04);
            border: 1px solid var(--border);
        }
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 14px;
            padding-bottom: 10px;
            border-bottom: 1px solid #f1f5f9;
        }
        .card-title {
            font-size: 0.8rem;
            font-weight: 700;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            display: flex;
            align-items: center;
            gap: 7px;
        }

        /* ---- Grid layouts ---- */
        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
        .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
        .grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }

        /* ---- Stat card (big overview numbers) ---- */
        .stat-card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 18px 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.07);
            border: 1px solid var(--border);
        }
        .stat-card-label {
            font-size: 0.75rem;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin-bottom: 8px;
        }
        .stat-card-value {
            font-size: 1.7rem;
            font-weight: 700;
            color: #1e293b;
            line-height: 1;
        }
        .stat-card-value.success { color: var(--success); }
        .stat-card-value.warning { color: var(--warning); }
        .stat-card-value.error   { color: var(--error); }
        .stat-card-value.accent  { color: var(--accent); }

        /* ---- Stat row (label: value) ---- */
        .stat-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 9px 0;
            border-bottom: 1px solid #f8fafc;
        }
        .stat-row:last-child { border-bottom: none; }
        .stat-label { color: #64748b; font-size: 0.85rem; font-weight: 500; }
        .stat-value {
            color: #1e293b;
            font-weight: 600;
            font-size: 0.9rem;
            text-align: right;
            max-width: 62%;
            word-break: break-word;
        }
        .stat-value.success { color: var(--success); }
        .stat-value.warning { color: var(--warning); }
        .stat-value.error   { color: var(--error); }

        /* ---- Progress bars ---- */
        .progress-section { margin-bottom: 14px; }
        .progress-section:last-child { margin-bottom: 0; }
        .progress-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; }
        .progress-label { font-size: 0.83rem; font-weight: 500; color: #475569; }
        .progress-value { font-size: 0.83rem; font-weight: 700; color: #1e293b; }
        .progress-bar-container {
            width: 100%;
            height: 8px;
            background: #e2e8f0;
            border-radius: 4px;
            overflow: hidden;
        }
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%);
            border-radius: 4px;
            transition: width 0.4s ease;
            min-width: 0;
        }

        /* ---- Job state badge ---- */
        .job-state-badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 700;
            background: #e0e7ff;
            color: #4338ca;
        }

        /* ---- Process items ---- */
        .process-item {
            background: #f8fafc;
            border: 1px solid #e8eef4;
            border-left: 3px solid var(--accent);
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 8px;
        }
        .process-item:last-child { margin-bottom: 0; }
        .process-id-row { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-bottom: 3px; }
        .process-id { font-weight: 700; color: var(--accent); font-size: 0.88rem; }
        .process-type-badge {
            font-size: 0.72rem;
            background: #e0e7ff;
            color: #4338ca;
            padding: 1px 7px;
            border-radius: 4px;
            font-weight: 600;
        }
        .process-state-badge {
            font-size: 0.72rem;
            background: #f0fdf4;
            color: #166534;
            padding: 1px 7px;
            border-radius: 4px;
            font-weight: 600;
        }
        .process-detail-text { font-size: 0.8rem; color: #64748b; }

        /* ---- Job queue items ---- */
        .job-item {
            background: #f8fafc;
            border: 1px solid #e8eef4;
            border-radius: 7px;
            padding: 7px 12px;
            margin-bottom: 5px;
            font-size: 0.83rem;
        }
        .job-item:last-child { margin-bottom: 0; }
        .job-id { font-family: 'Courier New', monospace; color: var(--accent); font-weight: 600; font-size: 0.8rem; }

        /* ---- Model badges ---- */
        .model-list { display: flex; flex-wrap: wrap; gap: 6px; }
        .model-badge { background: #e0e7ff; color: #4338ca; padding: 4px 10px; border-radius: 6px; font-size: 0.78rem; font-weight: 500; }

        /* ---- Console ---- */
        .console-container {
            background: #0f172a;
            border-radius: 8px;
            padding: 12px 14px;
            max-height: 440px;
            overflow-y: auto;
            font-family: 'Courier New', Consolas, 'Lucida Console', monospace;
            font-size: 0.8rem;
            color: #e2e8f0;
            line-height: 1.55;
        }

        /* ---- Images ---- */
        .image-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 10px;
            width: 100%;
        }
        .image-grid-item {
            position: relative;
            overflow: hidden;
            border-radius: 8px;
            background: #f1f5f9;
            aspect-ratio: 1;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .image-grid-item img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            display: block;
        }
        .image-grid-item img:hover { transform: scale(1.04); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }

        .last-image-container {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 160px;
        }

        .single-image {
            max-width: 100%;
            max-height: 380px;
            width: auto;
            height: auto;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            display: block;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .single-image:hover { transform: scale(1.02); box-shadow: 0 4px 16px rgba(0,0,0,0.18); }

        /* ---- Image overlay ---- */
        .image-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.92);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .image-overlay.active { display: flex; }
        .image-overlay-content {
            position: relative;
            max-width: 95%;
            max-height: 95%;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .image-overlay img {
            max-width: 100%;
            max-height: 90vh;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 8px 40px rgba(0,0,0,0.6);
        }
        .image-overlay-close {
            position: absolute;
            top: -44px;
            right: 0;
            background: var(--accent);
            color: white;
            border: none;
            padding: 8px 18px;
            font-size: 0.9rem;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.2s;
        }
        .image-overlay-close:hover { background: var(--accent-hover); }

        /* ---- Faulted jobs ---- */
        .faulted-jobs-list { display: flex; flex-direction: column; gap: 0; }
        .faulted-job-item {
            background: #fff5f5;
            border: 1px solid #fecaca;
            border-left: 3px solid var(--error);
            border-radius: 8px;
            padding: 13px;
            margin-bottom: 10px;
        }
        .faulted-job-item:last-child { margin-bottom: 0; }
        .faulted-job-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 9px;
            padding-bottom: 7px;
            border-bottom: 1px solid #fecaca;
            flex-wrap: wrap;
            gap: 6px;
        }
        .faulted-job-id { font-family: monospace; color: #dc2626; font-weight: 700; font-size: 0.85rem; word-break: break-all; }
        .faulted-job-time { color: #94a3b8; font-size: 0.78rem; flex-shrink: 0; }
        .faulted-job-details { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; }
        .faulted-job-detail { display: flex; flex-direction: column; }
        .faulted-job-label {
            color: #94a3b8;
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 2px;
        }
        .faulted-job-value { color: #334155; font-weight: 500; font-size: 0.85rem; word-break: break-word; }
        .faulted-job-lora { background: #fef3c7; color: #92400e; padding: 2px 7px; border-radius: 4px; font-size: 0.78rem; display: inline-block; margin: 2px; }
        .faulted-job-controlnet { background: #dbeafe; color: #1e40af; padding: 2px 7px; border-radius: 4px; font-size: 0.78rem; display: inline-block; font-weight: 600; }
        .faulted-job-section { margin-top: 8px; }
        .faulted-job-section-label { display: block; margin-bottom: 4px; }

        /* ---- Errors ---- */
        .errors-list { display: flex; flex-direction: column; }
        .error-item {
            background: #fff5f5;
            border: 1px solid #fecaca;
            border-left: 3px solid var(--error);
            border-radius: 6px;
            padding: 9px 13px;
            font-family: 'Courier New', monospace;
            font-size: 0.78rem;
            color: #7f1d1d;
            white-space: pre-wrap;
            word-break: break-word;
            margin-bottom: 5px;
        }
        .error-item:last-child { margin-bottom: 0; }

        .pagination-controls {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            margin-top: 12px;
            flex-wrap: wrap;
        }
        .pagination-controls button {
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 6px;
            padding: 6px 14px;
            cursor: pointer;
            font-size: 0.82rem;
            font-weight: 500;
            transition: background 0.15s;
        }
        .pagination-controls button:hover:not(:disabled) { background: var(--accent-hover); }
        .pagination-controls button:disabled { background: #c7d2fe; cursor: default; }
        .pagination-info { font-size: 0.82rem; color: #64748b; }

        /* ---- Scrollable ---- */
        .scrollable { max-height: 260px; overflow-y: auto; }
        .scrollable-tall { max-height: 400px; overflow-y: auto; }

        /* ---- Loading ---- */
        #loading {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 80vh;
            flex-direction: column;
            gap: 14px;
        }
        .loading-spinner {
            width: 36px;
            height: 36px;
            border: 3px solid #e2e8f0;
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.75s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .loading-text { color: #64748b; font-size: 0.9rem; }

        /* ---- Misc ---- */
        #update-time { font-size: 0.73rem; color: #94a3b8; text-align: right; margin-bottom: 10px; }
        .empty-state { text-align: center; padding: 24px 16px; color: #94a3b8; font-size: 0.87rem; }
        .empty-state-icon { font-size: 1.8rem; margin-bottom: 6px; display: block; }

        /* ---- Scrollbar ---- */
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

        /* ---- Responsive ---- */
        @media (max-width: 1200px) {
            .grid-4 { grid-template-columns: repeat(2, 1fr); }
            .grid-3 { grid-template-columns: repeat(2, 1fr); }
        }

        @media (max-width: 768px) {
            .sidebar { transform: translateX(-100%); }
            .sidebar.open { transform: translateX(0); }
            .mobile-navbar { display: flex; }
            .mobile-resources { display: flex; }
            .main-content { margin-left: 0; padding-top: 80px; }
            .topbar { display: none; }
            .content-area { padding: 14px 12px; }
            .grid-4 { grid-template-columns: repeat(2, 1fr); }
            .grid-3 { grid-template-columns: 1fr; }
            .grid-2 { grid-template-columns: 1fr; }
            .grid-3-popped { grid-template-columns: repeat(2, 1fr); }
        }

        @media (max-width: 480px) {
            .grid-4 { grid-template-columns: repeat(2, 1fr); gap: 10px; }
            .stat-card-value { font-size: 1.4rem; }
        }

        /* ---- Theme toggle button ---- */
        .theme-toggle {
            background: none;
            border: 1px solid rgba(255,255,255,0.18);
            color: var(--text-light);
            font-size: 1rem;
            cursor: pointer;
            padding: 5px 9px;
            border-radius: 8px;
            line-height: 1;
            transition: background 0.15s;
            flex-shrink: 0;
        }
        .theme-toggle:hover { background: rgba(255,255,255,0.08); }
        .topbar .theme-toggle {
            background: none;
            border: 1px solid #e2e8f0;
            color: #475569;
        }
        .topbar .theme-toggle:hover { background: #f1f5f9; }

        /* ---- Topbar resource chips ---- */
        .topbar-resources { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .topbar-res-chip {
            background: #f1f5f9;
            border: 1px solid #e2e8f0;
            color: #475569;
            font-size: 0.74rem;
            font-weight: 600;
            padding: 3px 9px;
            border-radius: 20px;
            font-family: 'Courier New', monospace;
            white-space: nowrap;
        }

        /* ---- Mobile resources sub-bar ---- */
        .mobile-resources {
            display: none;
            position: fixed;
            top: 54px; left: 0; right: 0;
            height: 26px;
            background: #12162a;
            align-items: center;
            padding: 0 14px;
            gap: 14px;
            z-index: 199;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .mobile-res-chip {
            color: var(--text-muted);
            font-size: 0.7rem;
            font-weight: 600;
            font-family: 'Courier New', monospace;
        }

        /* ---- Dark mode ---- */
        [data-theme="dark"] {
            --main-bg: #0f172a;
            --card-bg: #1e293b;
            --border: #2d3f55;
            --sidebar-bg: #0d1117;
            --sidebar-hover: #161e2e;
        }
        [data-theme="dark"] body { color: #cbd5e1; }
        [data-theme="dark"] .topbar { background: #1e293b; border-bottom-color: #2d3f55; }
        [data-theme="dark"] .topbar-worker-name { color: #f1f5f9; }
        [data-theme="dark"] .topbar-worker-sub,
        [data-theme="dark"] .topbar-uptime { color: #94a3b8; }
        [data-theme="dark"] .topbar .theme-toggle { border-color: #2d3f55; color: #94a3b8; }
        [data-theme="dark"] .topbar .theme-toggle:hover { background: #2d3f55; }
        [data-theme="dark"] .topbar-res-chip { background: #151e2e; border-color: #2d3f55; color: #94a3b8; }
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
        /* ---- Log tabs ---- */
        .log-tabs {
            display: flex;
            gap: 0;
            margin-top: 12px;
            border-bottom: none;
        }
        .log-tab {
            background: #e2e8f0;
            border: 1px solid var(--border);
            border-bottom: none;
            color: #475569;
            font-size: 0.82rem;
            font-weight: 600;
            padding: 8px 18px;
            cursor: pointer;
            border-radius: 8px 8px 0 0;
            margin-right: 4px;
            transition: background 0.15s, color 0.15s;
            white-space: nowrap;
        }
        .log-tab:hover { background: #cbd5e1; }
        .log-tab.active { background: var(--card-bg); color: var(--accent); border-color: var(--border); }
        .tab-count {
            background: #cbd5e1;
            color: #475569;
            font-size: 0.7rem;
            font-weight: 700;
            padding: 1px 7px;
            border-radius: 20px;
            margin-left: 4px;
        }
        .log-tab.active .tab-count { background: #e0e7ff; color: var(--accent); }
        [data-theme="dark"] .log-tab { background: #151e2e; border-color: #2d3f55; color: #94a3b8; }
        [data-theme="dark"] .log-tab:hover { background: #1e2d42; }
        [data-theme="dark"] .log-tab.active { background: var(--card-bg); color: var(--accent); }
        [data-theme="dark"] .tab-count { background: #2d3f55; color: #94a3b8; }
        [data-theme="dark"] .log-tab.active .tab-count { background: #312e81; color: #a5b4fc; }

    </style>
</head>
<body>
    <!-- Mobile top navbar -->
    <nav class="mobile-navbar" aria-label="Mobile navigation">
        <button class="hamburger-btn" onclick="toggleSidebar()" aria-label="Toggle sidebar">&#9776;</button>
        <span class="mobile-title">&#127912; Horde Worker</span>
        <span id="mobile-status-badge"></span>
        <button class="theme-toggle" onclick="toggleTheme()" id="mobile-theme-toggle" aria-label="Toggle theme">&#127769;</button>
    </nav>

    <!-- Mobile resources sub-bar -->
    <div class="mobile-resources" aria-label="Resource usage">
        <span class="mobile-res-chip" id="mobile-cpu">CPU 0%</span>
        <span class="mobile-res-chip" id="mobile-gpu">GPU 0%</span>
        <span class="mobile-res-chip" id="mobile-vram">VRAM 0%</span>
    </div>

    <!-- Sidebar overlay -->
    <div class="sidebar-overlay" id="sidebar-overlay" onclick="closeSidebar()"></div>

    <!-- Sidebar -->
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-logo">
            <h1>&#127912; Horde Worker</h1>
            <p>AI Image Generation</p>
        </div>
        <nav class="sidebar-nav" aria-label="Page sections">
            <div class="nav-section-label">Navigation</div>
            <button class="nav-item active" onclick="scrollToSection('overview', this)">
                <span class="nav-icon">&#128202;</span> Overview
            </button>
            <button class="nav-item" onclick="scrollToSection('images-section', this)">
                <span class="nav-icon">&#128444;</span> Images
            </button>
            <button class="nav-item" onclick="scrollToSection('logs-section', this)">
                <span class="nav-icon">&#128203;</span> Logs
            </button>
        </nav>
        <div class="sidebar-footer">
            <p id="sidebar-update-time">Last updated: Never</p>
        </div>
    </aside>

    <!-- Main content -->
    <div class="main-content">
        <!-- Top bar (desktop only) -->
        <div class="topbar">
            <div class="topbar-worker">
                <div class="topbar-worker-name" id="topbar-worker-name">Horde Worker</div>
                <div class="topbar-worker-sub" id="topbar-worker-sub">Loading...</div>
            </div>
            <div class="topbar-resources">
                <span class="topbar-res-chip" id="topbar-cpu">CPU 0%</span>
                <span class="topbar-res-chip" id="topbar-gpu">GPU 0%</span>
                <span class="topbar-res-chip" id="topbar-vram">VRAM 0%</span>
            </div>
            <div class="topbar-meta">
                <span id="worker-status-badge"></span>
                <span class="topbar-uptime">&#9201; <span id="uptime">--</span></span>
                <button class="theme-toggle" onclick="toggleTheme()" id="topbar-theme-toggle" aria-label="Toggle theme">&#127769;</button>
            </div>
        </div>

        <!-- Content area -->
        <div class="content-area">
            <!-- Loading state -->
            <div id="loading">
                <div class="loading-spinner"></div>
                <span class="loading-text">Connecting to worker...</span>
            </div>

            <!-- Main content (hidden until data loads) -->
            <div id="content" style="display: none;">
                <div id="update-time">Last updated: Never</div>

                <!-- OVERVIEW -->
                <section class="section" id="overview">
                    <div class="section-header">
                        <span class="section-title">&#128202; Overview</span>
                    </div>

                    <!-- Row 1: 4 stat cards -->
                    <div class="grid-4" style="margin-bottom: 14px;">
                        <div class="stat-card">
                            <div class="stat-card-label">Total Kudos</div>
                            <div class="stat-card-value success" id="user-kudos-total">-</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-card-label">Kudos / Hour</div>
                            <div class="stat-card-value accent" id="kudos-per-hour">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-card-label">Jobs Popped</div>
                            <div class="stat-card-value accent" id="jobs-popped">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-card-label">Jobs Completed</div>
                            <div class="stat-card-value success" id="jobs-completed">0</div>
                        </div>
                    </div>

                    <!-- Row 2: 3 stat cards -->
                    <div class="grid-3 grid-3-popped" style="margin-bottom: 14px;">
                        <div class="stat-card">
                            <div class="stat-card-label">Jobs Queued</div>
                            <div class="stat-card-value" id="jobs-queued">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-card-label">Jobs Recovered</div>
                            <div class="stat-card-value warning" id="processes-recovered">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-card-label">Jobs Faulted</div>
                            <div class="stat-card-value error" id="jobs-faulted">0</div>
                        </div>
                    </div>

                    <!-- Horde Info + Queue/Models -->
                    <div class="grid-2">
                        <div class="card">
                            <div class="card-header">
                                <span class="card-title">&#127760; Horde Info</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Worker Name</span>
                                <span class="stat-value" id="worker-name">-</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Username</span>
                                <span class="stat-value" id="horde-username">-</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Status</span>
                                <span id="horde-info-status-badge">-</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Uptime</span>
                                <span class="stat-value" id="horde-info-uptime">-</span>
                            </div>
                        </div>

                        <div class="card">
                            <div class="card-header">
                                <span class="card-title">&#128230; Job Queue &amp; Models</span>
                            </div>
                            <div style="margin-bottom: 14px;">
                                <div style="font-size:0.75rem;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:7px;">
                                    Queue (<span id="queue-count">0</span>)
                                </div>
                                <div id="job-queue" class="scrollable">
                                    <div class="empty-state">Queue is empty</div>
                                </div>
                            </div>
                            <div>
                                <div style="font-size:0.75rem;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:7px;">
                                    Active Models
                                </div>
                                <div id="models-loaded" class="model-list">
                                    <span style="color:#94a3b8;font-size:0.83rem;">No models loaded</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Current Job + Last Image -->
                    <div class="grid-2" style="margin-top: 14px;">
                        <div class="card">
                            <div class="card-header">
                                <span class="card-title">&#9889; Current Job</span>
                            </div>
                            <div id="overview-current-job">
                                <div class="empty-state">
                                    <span class="empty-state-icon">&#9203;</span>
                                    No job in progress
                                </div>
                            </div>
                        </div>
                        <div class="card">
                            <div class="card-header">
                                <span class="card-title">&#128444; Last Image</span>
                            </div>
                            <div style="font-size:0.75rem;color:#94a3b8;margin-bottom:10px;">
                                <span id="overview-image-time">No image generated yet</span>
                            </div>
                            <div id="overview-image-container" style="display:flex;align-items:center;justify-content:center;min-height:120px;">
                                <div class="empty-state">
                                    <span class="empty-state-icon">&#128444;</span>
                                    No image generated yet
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Resources + Processes -->
                    <div class="grid-2" style="margin-top: 14px;">
                        <div class="card">
                            <div class="card-header">
                                <span class="card-title">&#128190; Resources</span>
                            </div>
                            <div class="stat-row" style="margin-bottom: 14px;">
                                <span class="stat-label">RAM Usage</span>
                                <span class="stat-value" id="ram-usage">-</span>
                            </div>
                            <div class="progress-section">
                                <div class="progress-header">
                                    <span class="progress-label" id="cpu-label">CPU</span>
                                    <span class="progress-value" id="cpu-progress-text">0%</span>
                                </div>
                                <div class="progress-bar-container">
                                    <div class="progress-bar" id="cpu-progress" style="width:0%"></div>
                                </div>
                            </div>
                            <div class="progress-section">
                                <div class="progress-header">
                                    <span class="progress-label">GPU</span>
                                    <span class="progress-value" id="gpu-progress-text">0%</span>
                                </div>
                                <div class="progress-bar-container">
                                    <div class="progress-bar" id="gpu-progress" style="width:0%"></div>
                                </div>
                            </div>
                            <div class="progress-section">
                                <div class="progress-header">
                                    <span class="progress-label" id="vram-label">VRAM</span>
                                    <span class="progress-value" id="vram-progress-text">0%</span>
                                </div>
                                <div class="progress-bar-container">
                                    <div class="progress-bar" id="vram-progress" style="width:0%"></div>
                                </div>
                            </div>
                        </div>
                        <div class="card">
                            <div class="card-header">
                                <span class="card-title">&#9881; Processes</span>
                                <span class="section-count" id="process-count">0</span>
                            </div>
                            <div id="processes" class="scrollable-tall">
                                <div class="empty-state">
                                    <span class="empty-state-icon">&#9881;</span>
                                    No process info
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                <!-- IMAGES -->
                <section class="section" id="images-section">
                    <div class="section-header">
                        <span class="section-title">&#128444; Last Generated Image(s)</span>
                    </div>
                    <div class="card">
                        <div style="font-size:0.78rem;color:#94a3b8;margin-bottom:12px;">
                            <span id="last-image-time">No image generated yet</span>
                        </div>
                        <div id="last-image-container" class="last-image-container">
                            <div class="empty-state">
                                <span class="empty-state-icon">&#128444;</span>
                                No image generated yet
                            </div>
                        </div>
                    </div>
                </section>

                <!-- LOGS (Console + Faulted Jobs + Errors combined) -->
                <section class="section" id="logs-section">
                    <div class="section-header" style="margin-bottom: 0;">
                        <span class="section-title">&#128203; Logs</span>
                    </div>
                    <div class="log-tabs">
                        <button class="log-tab active" id="tab-console" onclick="showLogTab('console')">&#128203; Console</button>
                        <button class="log-tab" id="tab-faulted" onclick="showLogTab('faulted')">&#9888; Faulted Jobs <span class="tab-count" id="faulted-jobs-count">0</span></button>
                        <button class="log-tab" id="tab-errors" onclick="showLogTab('errors')">&#10060; Errors <span class="tab-count" id="errors-count">0</span></button>
                    </div>
                    <div class="card" style="border-top-left-radius: 0; border-top-right-radius: 0; border-top: none;">
                        <!-- Console tab -->
                        <div id="log-panel-console">
                            <div id="console-logs" class="console-container">
                                <div style="text-align:center;color:#475569;padding:18px;">No logs available</div>
                            </div>
                        </div>
                        <!-- Faulted Jobs tab -->
                        <div id="log-panel-faulted" style="display:none;">
                            <div id="faulted-jobs" class="faulted-jobs-list scrollable-tall">
                                <div class="empty-state">
                                    <span class="empty-state-icon">&#10003;</span>
                                    No faulted jobs
                                </div>
                            </div>
                        </div>
                        <!-- Errors tab -->
                        <div id="log-panel-errors" style="display:none;">
                            <div id="errors-history" class="errors-list">
                                <div class="empty-state">
                                    <span class="empty-state-icon">&#10003;</span>
                                    No errors
                                </div>
                            </div>
                            <div class="pagination-controls" id="errors-pagination" style="display: none;">
                                <button id="errors-prev" onclick="errorsChangePage(-1)" disabled>&#8249; Prev</button>
                                <span class="pagination-info" id="errors-page-info">Page 1 of 1</span>
                                <button id="errors-next" onclick="errorsChangePage(1)">Next &#8250;</button>
                            </div>
                        </div>
                    </div>
                </section>

            </div><!-- /#content -->
        </div><!-- /.content-area -->
    </div><!-- /.main-content -->

    <!-- Full resolution image overlay -->
    <div id="image-overlay" class="image-overlay">
        <div class="image-overlay-content">
            <button class="image-overlay-close" onclick="closeImageOverlay()">&#10005; Close</button>
            <img id="overlay-image" src="" alt="Full resolution image" />
        </div>
    </div>

    <script>
        // ---- Sidebar / mobile ----
        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('open');
            document.getElementById('sidebar-overlay').classList.toggle('active');
        }

        function closeSidebar() {
            document.getElementById('sidebar').classList.remove('open');
            document.getElementById('sidebar-overlay').classList.remove('active');
        }

        function escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function scrollToSection(sectionId, navEl) {
            const section = document.getElementById(sectionId);
            if (section) {
                const offset = window.innerWidth < 768 ? 62 : 20;
                const top = section.getBoundingClientRect().top + window.scrollY - offset;
                window.scrollTo({ top: top, behavior: 'smooth' });
            }
            document.querySelectorAll('.nav-item').forEach(function(item) { item.classList.remove('active'); });
            if (navEl) navEl.classList.add('active');
            if (window.innerWidth < 768) closeSidebar();
        }

        // ---- Log tabs ----
        function showLogTab(tab) {
            ['console', 'faulted', 'errors'].forEach(function(t) {
                document.getElementById('log-panel-' + t).style.display = t === tab ? '' : 'none';
                document.getElementById('tab-' + t).classList.toggle('active', t === tab);
            });
        }

        // ---- Theme toggle ----
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

        // ---- Image overlay ----
        function openImageOverlay(imageSrc) {
            const overlay = document.getElementById('image-overlay');
            const overlayImage = document.getElementById('overlay-image');
            overlayImage.src = imageSrc;
            overlay.classList.add('active');
        }

        function closeImageOverlay() {
            const overlay = document.getElementById('image-overlay');
            overlay.classList.remove('active');
        }

        document.getElementById('image-overlay').addEventListener('click', function(e) {
            if (e.target === this) {
                closeImageOverlay();
            }
        });

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeImageOverlay();
            }
        });

        // ---- Utility functions ----
        function formatUptime(seconds) {
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = Math.floor(seconds % 60);
            return `${hours}h ${minutes}m ${secs}s`;
        }

        function formatBytes(bytes) {
            if (bytes === 0) return '0 MB';
            const mb = bytes / (1024 * 1024);
            return mb.toFixed(1) + ' MB';
        }

        function formatTimeAgo(timestamp) {
            if (!timestamp || timestamp === 0) {
                return 'No image generated yet';
            }
            const now = Date.now() / 1000; // Convert to seconds
            const secondsAgo = Math.floor(now - timestamp);

            if (secondsAgo < 60) {
                return `Last submission: ${secondsAgo} second${secondsAgo !== 1 ? 's' : ''} ago`;
            } else if (secondsAgo < 3600) {
                const minutes = Math.floor(secondsAgo / 60);
                return `Last submission: ${minutes} minute${minutes !== 1 ? 's' : ''} ago`;
            } else if (secondsAgo < 86400) {
                const hours = Math.floor(secondsAgo / 3600);
                return `Last submission: ${hours} hour${hours !== 1 ? 's' : ''} ago`;
            } else {
                const days = Math.floor(secondsAgo / 86400);
                return `Last submission: ${days} day${days !== 1 ? 's' : ''} ago`;
            }
        }

        // Constants for UI behavior
        const SCROLL_TOLERANCE_PX = 1; // Pixel tolerance for scroll position detection

        // Errors pagination state
        const ERRORS_PAGE_SIZE = 10;
        let errorsCurrentPage = 1;
        let errorsData = [];

        function renderErrorsPage() {
            const errorsDiv = document.getElementById('errors-history');
            const pageInfo = document.getElementById('errors-page-info');
            const prevBtn = document.getElementById('errors-prev');
            const nextBtn = document.getElementById('errors-next');
            const pagination = document.getElementById('errors-pagination');

            if (errorsData.length === 0) {
                errorsDiv.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#10003;</span>No errors</div>';
                pagination.style.display = 'none';
                return;
            }

            const totalPages = Math.max(1, Math.ceil(errorsData.length / ERRORS_PAGE_SIZE));
            errorsCurrentPage = Math.min(Math.max(1, errorsCurrentPage), totalPages);

            const start = (errorsCurrentPage - 1) * ERRORS_PAGE_SIZE;
            const pageItems = errorsData.slice(start, start + ERRORS_PAGE_SIZE);

            errorsDiv.innerHTML = pageItems.map(err => `<div class="error-item">${escapeHtml(err)}</div>`).join('');
            pageInfo.textContent = `Page ${errorsCurrentPage} of ${totalPages}`;
            prevBtn.disabled = errorsCurrentPage <= 1;
            nextBtn.disabled = errorsCurrentPage >= totalPages;
            pagination.style.display = 'flex';
        }

        function errorsChangePage(delta) {
            const totalPages = Math.max(1, Math.ceil(errorsData.length / ERRORS_PAGE_SIZE));
            errorsCurrentPage = Math.min(Math.max(1, errorsCurrentPage + delta), totalPages);
            renderErrorsPage();
        }

        // Helper function to check if element is scrolled to bottom
        function isScrolledToBottom(element, tolerance) {
            return element.scrollHeight - element.clientHeight <= element.scrollTop + tolerance;
        }

        // Helper function to escape HTML to prevent XSS
        function escapeHtml(str) {
            if (str === null || str === undefined) { return ''; }
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }

        // ANSI color code to HTML converter
        function ansiToHtml(text) {
            // Escape HTML first to prevent XSS
            text = escapeHtml(text);

            // ANSI color codes mapping
            const colors = {
                '30': '#000000', '31': '#cd3131', '32': '#0dbc79', '33': '#e5e510',
                '34': '#2472c8', '35': '#bc3fbc', '36': '#11a8cd', '37': '#e5e5e5',
                '90': '#666666', '91': '#f14c4c', '92': '#23d18b', '93': '#f5f543',
                '94': '#3b8eea', '95': '#d670d6', '96': '#29b8db', '97': '#ffffff',
                // Bold+color combinations for loguru compatibility
                '1;30': '#666666', '1;31': '#f14c4c', '1;32': '#23d18b', '1;33': '#f5f543',
                '1;34': '#3b8eea', '1;35': '#d670d6', '1;36': '#29b8db', '1;37': '#ffffff',
            };

            const bgColors = {
                '40': '#000000', '41': '#cd3131', '42': '#0dbc79', '43': '#e5e510',
                '44': '#2472c8', '45': '#bc3fbc', '46': '#11a8cd', '47': '#e5e5e5',
                '100': '#666666', '101': '#f14c4c', '102': '#23d18b', '103': '#f5f543',
                '104': '#3b8eea', '105': '#d670d6', '106': '#29b8db', '107': '#ffffff',
            };

            let result = '';
            let currentStyles = [];

            // Split by ANSI escape sequences
            const parts = text.split(/\x1b\[([0-9;]+)m/);

            for (let i = 0; i < parts.length; i++) {
                if (i % 2 === 0) {
                    // Regular text
                    if (currentStyles.length > 0) {
                        result += '<span style="' + currentStyles.join(';') + '">' + parts[i] + '</span>';
                    } else {
                        result += parts[i];
                    }
                } else {
                    // ANSI code - process codes cumulatively
                    const codes = parts[i].split(';');

                    for (const code of codes) {
                        if (code === '0' || code === '') {
                            // Reset all styles
                            currentStyles = [];
                        } else if (code === '1') {
                            // Bold
                            if (!currentStyles.some(s => s.startsWith('font-weight:'))) {
                                currentStyles.push('font-weight:bold');
                            }
                        } else if (code === '2') {
                            // Dim/faint
                            if (!currentStyles.some(s => s.startsWith('opacity:'))) {
                                currentStyles.push('opacity:0.6');
                            }
                        } else if (code === '3') {
                            // Italic
                            if (!currentStyles.some(s => s.startsWith('font-style:'))) {
                                currentStyles.push('font-style:italic');
                            }
                        } else if (code === '4') {
                            // Underline
                            if (!currentStyles.some(s => s.startsWith('text-decoration:'))) {
                                currentStyles.push('text-decoration:underline');
                            }
                        } else if (colors[code]) {
                            // Foreground color
                            currentStyles = currentStyles.filter(s => !s.startsWith('color:'));
                            currentStyles.push('color:' + colors[code]);
                        } else if (bgColors[code]) {
                            // Background color
                            currentStyles = currentStyles.filter(s => !s.startsWith('background-color:'));
                            currentStyles.push('background-color:' + bgColors[code]);
                        }
                    }
                }
            }

            return result;
        }

        // AbortController for cancelling in-flight requests
        let statusAbortController = null;
        let statusFetchInProgress = false;
        let consecutiveErrors = 0;
        const MAX_CONSECUTIVE_ERRORS = 5;

        function updateStatus() {
            // Prevent multiple simultaneous requests
            if (statusFetchInProgress) {
                return;
            }

            // Cancel any pending request
            if (statusAbortController) {
                statusAbortController.abort();
            }

            // Create new abort controller for this request
            statusAbortController = new AbortController();
            statusFetchInProgress = true;

            fetch('/api/status', { signal: statusAbortController.signal })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    // Reset error counter on success
                    consecutiveErrors = 0;

                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('content').style.display = 'block';

                    // Worker identity
                    const workerName = data.worker_name || 'Unknown';
                    document.getElementById('worker-name').textContent = workerName;
                    document.getElementById('horde-username').textContent = data.horde_username;
                    document.getElementById('topbar-worker-name').textContent = workerName;
                    document.getElementById('topbar-worker-sub').textContent = `@${data.horde_username}`;

                    // Status badge
                    const badgeHtml = data.maintenance_mode
                        ? '<span class="status-badge status-maintenance">Maintenance</span>'
                        : '<span class="status-badge status-active">Active</span>';
                    document.getElementById('worker-status-badge').innerHTML = badgeHtml;
                    document.getElementById('horde-info-status-badge').innerHTML = badgeHtml;
                    document.getElementById('mobile-status-badge').innerHTML = data.maintenance_mode
                        ? '<span class="status-badge status-maintenance" style="font-size:0.68rem;padding:2px 7px;">Maint.</span>'
                        : '<span class="status-badge status-active" style="font-size:0.68rem;padding:2px 7px;">Active</span>';

                    // Uptime
                    const uptimeStr = formatUptime(data.uptime);
                    document.getElementById('uptime').textContent = uptimeStr;
                    document.getElementById('horde-info-uptime').textContent = uptimeStr;

                    // Kudos
                    document.getElementById('user-kudos-total').textContent =
                        data.user_kudos_total ? data.user_kudos_total.toLocaleString(undefined, {maximumFractionDigits: 2}) : '-';
                    document.getElementById('kudos-per-hour').textContent =
                        data.kudos_per_hour.toLocaleString(undefined, {maximumFractionDigits: 2});

                    // Session Stats
                    document.getElementById('jobs-popped').textContent = data.jobs_popped;
                    document.getElementById('jobs-completed').textContent = data.jobs_completed;
                    document.getElementById('jobs-faulted').textContent = data.jobs_faulted;
                    document.getElementById('processes-recovered').textContent = data.processes_recovered;
                    document.getElementById('jobs-queued').textContent = data.jobs_queued;

                    // Resources
                    document.getElementById('ram-usage').textContent = formatBytes(data.ram_usage_mb * 1024 * 1024);

                    const cpuPercent = Math.min(100, Math.round(data.cpu_usage_percent));
                    const cpuProgress = document.getElementById('cpu-progress');
                    cpuProgress.style.width = cpuPercent + '%';
                    document.getElementById('cpu-progress-text').textContent = cpuPercent + '%';

                    // Update CPU label with cores count
                    const cpuLabel = document.getElementById('cpu-label');
                    const cpuCoresText = data.cpu_cores_count > 0 ? ` (${data.cpu_cores_count} cores)` : '';
                    cpuLabel.textContent = `CPU${cpuCoresText}`;

                    const gpuPercent = Math.min(100, Math.round(data.gpu_usage_percent));
                    const gpuProgress = document.getElementById('gpu-progress');
                    gpuProgress.style.width = gpuPercent + '%';
                    document.getElementById('gpu-progress-text').textContent = gpuPercent + '%';

                    const vramPercent = data.total_vram_mb > 0
                        ? Math.min(100, Math.round((data.vram_usage_mb / data.total_vram_mb) * 100))
                        : 0;
                    const vramProgress = document.getElementById('vram-progress');
                    vramProgress.style.width = vramPercent + '%';
                    document.getElementById('vram-progress-text').textContent = vramPercent + '%';

                    // Update VRAM label with absolute usage
                    const vramLabel = document.getElementById('vram-label');
                    const vramUsed = formatBytes(data.vram_usage_mb * 1024 * 1024);
                    const vramTotal = formatBytes(data.total_vram_mb * 1024 * 1024);
                    vramLabel.textContent = `VRAM: ${vramUsed} / ${vramTotal}`;

                    // Header resource chips (topbar + mobile)
                    document.getElementById('topbar-cpu').textContent = `CPU ${cpuPercent}%`;
                    document.getElementById('topbar-gpu').textContent = `GPU ${gpuPercent}%`;
                    document.getElementById('topbar-vram').textContent = `VRAM ${vramPercent}%`;
                    document.getElementById('mobile-cpu').textContent = `CPU ${cpuPercent}%`;
                    document.getElementById('mobile-gpu').textContent = `GPU ${gpuPercent}%`;
                    document.getElementById('mobile-vram').textContent = `VRAM ${vramPercent}%`;

                    // Current Job (rendered in overview card)
                    const overviewJobDiv = document.getElementById('overview-current-job');
                    if (data.current_job) {
                        const job = data.current_job;
                        const stateDisplay = escapeHtml(job.state || 'N/A');
                        const progressValue = (job.progress !== null && job.progress !== undefined) ? job.progress : 0;

                        overviewJobDiv.innerHTML = `
                            <div class="stat-row">
                                <span class="stat-label">Job ID:</span>
                                <span class="stat-value" style="font-family:monospace;font-size:0.8rem;">${escapeHtml(job.id || 'N/A')}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Model:</span>
                                <span class="stat-value">${escapeHtml(job.model || 'N/A')}</span>
                            </div>
                            ${job.batch_size !== null && job.batch_size !== undefined ? `
                            <div class="stat-row">
                                <span class="stat-label">Batch Size:</span>
                                <span class="stat-value">${escapeHtml(job.batch_size)}x</span>
                            </div>
                            ` : ''}
                            ${job.steps !== null && job.steps !== undefined ? `
                            <div class="stat-row">
                                <span class="stat-label">Steps:</span>
                                <span class="stat-value">${escapeHtml(job.steps)}</span>
                            </div>
                            ` : ''}
                            ${job.width !== null && job.width !== undefined && job.height !== null && job.height !== undefined ? `
                            <div class="stat-row">
                                <span class="stat-label">Image Size:</span>
                                <span class="stat-value">${escapeHtml(job.width)}x${escapeHtml(job.height)}</span>
                            </div>
                            ` : ''}
                            ${job.sampler !== null && job.sampler !== undefined ? `
                            <div class="stat-row">
                                <span class="stat-label">Sampler:</span>
                                <span class="stat-value">${escapeHtml(job.sampler)}</span>
                            </div>
                            ` : ''}
                            ${job.loras !== null && job.loras !== undefined && job.loras.length > 0 ? `
                            <div class="stat-row">
                                <span class="stat-label">LoRAs:</span>
                                <span class="stat-value">${job.loras.map(lora => escapeHtml(lora.name || 'Unknown')).join(', ')}</span>
                            </div>
                            ` : ''}
                            <div class="stat-row">
                                <span class="stat-label">State:</span>
                                <span class="job-state-badge">${stateDisplay}</span>
                            </div>
                            <div style="margin-top:14px;">
                                <div class="progress-header">
                                    <span class="progress-label">Progress</span>
                                    <span class="progress-value">${escapeHtml(progressValue)}%</span>
                                </div>
                                <div class="progress-bar-container" style="height:12px;">
                                    <div class="progress-bar" style="width:${escapeHtml(progressValue)}%;height:100%;border-radius:6px;"></div>
                                </div>
                            </div>
                        `;
                    } else {
                        overviewJobDiv.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#9203;</span>No job in progress</div>';
                    }

                    // Overview: last image thumbnail
                    document.getElementById('overview-image-time').textContent = formatTimeAgo(data.last_image_submission_timestamp);
                    const overviewImgContainer = document.getElementById('overview-image-container');
                    if (data.last_image_base64 && data.last_image_base64.length > 0) {
                        const oImgSrc = `data:image/png;base64,${data.last_image_base64[0]}`;
                        overviewImgContainer.innerHTML = `
                            <img src="${oImgSrc}"
                                 style="max-width:100%;max-height:200px;width:auto;height:auto;object-fit:contain;border-radius:8px;cursor:pointer;display:block;margin:0 auto;"
                                 alt="Last generated image"
                                 data-fullsize="${oImgSrc}" />
                        `;
                        overviewImgContainer.querySelector('img[data-fullsize]').onclick = function() {
                            openImageOverlay(this.getAttribute('data-fullsize'));
                        };
                    } else {
                        overviewImgContainer.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#128444;</span>No image generated yet</div>';
                    }

                    // Job Queue
                    const queueDiv = document.getElementById('job-queue');
                    const queueCount = document.getElementById('queue-count');
                    queueCount.textContent = data.job_queue.length;

                    if (data.job_queue.length > 0) {
                        queueDiv.innerHTML = data.job_queue.map(job => {
                            const batchInfo = job.batch_size && job.batch_size > 1 ? ` (${escapeHtml(job.batch_size)}x batch)` : '';
                            return `
                                <div class="job-item">
                                    <span class="job-id">${escapeHtml(job.id || 'N/A')}</span>: ${escapeHtml(job.model || 'Unknown model')}${batchInfo}
                                </div>
                            `;
                        }).join('');
                    } else {
                        queueDiv.innerHTML = '<div class="empty-state">Queue is empty</div>';
                    }

                    // Models
                    const modelsDiv = document.getElementById('models-loaded');
                    if (data.models_loaded.length > 0) {
                        modelsDiv.innerHTML = data.models_loaded.map(model =>
                            `<div class="model-badge">${escapeHtml(model)}</div>`
                        ).join('');
                    } else {
                        modelsDiv.innerHTML = '<span style="color:#94a3b8;font-size:0.83rem;">No models loaded</span>';
                    }

                    // Processes
                    const processesDiv = document.getElementById('processes');
                    const processCount = document.getElementById('process-count');
                    processCount.textContent = data.processes.length;

                    if (data.processes.length > 0) {
                        processesDiv.innerHTML = data.processes.map(proc => {
                            // Build second line with model, batch size, and progress
                            let secondLine = [];
                            if (proc.model) {
                                secondLine.push(`Model: ${escapeHtml(proc.model)}`);
                            }
                            if (proc.batch_size !== null && proc.batch_size !== undefined) {
                                secondLine.push(`Batch: ${escapeHtml(proc.batch_size)}x`);
                            }
                            if (proc.progress !== null && proc.progress !== undefined) {
                                secondLine.push(`Progress: ${escapeHtml(proc.progress)}%`);
                            }
                            const secondLineText = secondLine.length > 0 ? secondLine.join(' | ') : 'Idle';

                            return `
                            <div class="process-item">
                                <div class="process-id-row">
                                    <span class="process-id">Process #${escapeHtml(proc.id)}</span>
                                    <span class="process-type-badge">${escapeHtml(proc.type)}</span>
                                    <span class="process-state-badge">${escapeHtml(proc.state)}</span>
                                </div>
                                <div class="process-detail-text">${secondLineText}</div>
                            </div>
                        `;
                        }).join('');
                    } else {
                        processesDiv.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#9881;</span>No process info</div>';
                    }

                    // Faulted Jobs
                    const faultedJobsDiv = document.getElementById('faulted-jobs');
                    const faultedJobsCount = document.getElementById('faulted-jobs-count');
                    if (data.faulted_jobs_history && data.faulted_jobs_history.length > 0) {
                        faultedJobsCount.textContent = data.faulted_jobs_history.length;
                        faultedJobsDiv.innerHTML = data.faulted_jobs_history.map(job => {
                            // Validate and format timestamp
                            let timeStr = 'Unknown time';
                            if (job.time_faulted && !isNaN(job.time_faulted)) {
                                const faultedTime = new Date(job.time_faulted * 1000);
                                if (!isNaN(faultedTime.getTime())) {
                                    timeStr = faultedTime.toLocaleString();
                                }
                            }

                            let detailsHtml = '<div class="faulted-job-details">';

                            // Model
                            detailsHtml += `
                                <div class="faulted-job-detail">
                                    <span class="faulted-job-label">Model</span>
                                    <span class="faulted-job-value">${escapeHtml(job.model)}</span>
                                </div>
                            `;

                            // Fault Phase
                            if (job.fault_phase) {
                                detailsHtml += `
                                    <div class="faulted-job-detail">
                                        <span class="faulted-job-label">Fault Phase</span>
                                        <span class="faulted-job-value" style="color:#ef4444;font-weight:600;">${escapeHtml(job.fault_phase)}</span>
                                    </div>
                                `;
                            }

                            // Size
                            if (job.width && job.height) {
                                detailsHtml += `
                                    <div class="faulted-job-detail">
                                        <span class="faulted-job-label">Size</span>
                                        <span class="faulted-job-value">${job.width}x${job.height}</span>
                                    </div>
                                `;
                            }

                            // Steps
                            if (job.steps) {
                                detailsHtml += `
                                    <div class="faulted-job-detail">
                                        <span class="faulted-job-label">Steps</span>
                                        <span class="faulted-job-value">${job.steps}</span>
                                    </div>
                                `;
                            }

                            // Sampler
                            if (job.sampler) {
                                detailsHtml += `
                                    <div class="faulted-job-detail">
                                        <span class="faulted-job-label">Sampler</span>
                                        <span class="faulted-job-value">${escapeHtml(job.sampler)}</span>
                                    </div>
                                `;
                            }

                            // Batch Size (only if > 1)
                            if (job.batch_size && job.batch_size > 1) {
                                detailsHtml += `
                                    <div class="faulted-job-detail">
                                        <span class="faulted-job-label">Batch Size</span>
                                        <span class="faulted-job-value">${job.batch_size}x</span>
                                    </div>
                                `;
                            }

                            detailsHtml += '</div>';

                            // LoRAs
                            let lorasHtml = '';
                            if (job.loras && job.loras.length > 0) {
                                lorasHtml = '<div class="faulted-job-section">';
                                lorasHtml += '<span class="faulted-job-label faulted-job-section-label">LoRAs:</span>';
                                job.loras.forEach(lora => {
                                    const loraName = lora.name || 'Unknown';
                                    lorasHtml += `<span class="faulted-job-lora">${escapeHtml(loraName)}</span>`;
                                });
                                lorasHtml += '</div>';
                            }

                            // ControlNet
                            let controlnetHtml = '';
                            if (job.controlnet) {
                                controlnetHtml = `
                                    <div class="faulted-job-section">
                                        <span class="faulted-job-label faulted-job-section-label">ControlNet:</span>
                                        <span class="faulted-job-controlnet">${escapeHtml(job.controlnet)}</span>
                                    </div>
                                `;
                            }

                            return `
                                <div class="faulted-job-item">
                                    <div class="faulted-job-header">
                                        <span class="faulted-job-id">${escapeHtml(job.job_id)}</span>
                                        <span class="faulted-job-time">${timeStr}</span>
                                    </div>
                                    ${detailsHtml}
                                    ${lorasHtml}
                                    ${controlnetHtml}
                                </div>
                            `;
                        }).join('');
                    } else {
                        faultedJobsCount.textContent = '0';
                        faultedJobsDiv.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#10003;</span>No faulted jobs</div>';
                    }

                    // Errors History
                    const errorsCount = document.getElementById('errors-count');
                    if (data.errors_history && data.errors_history.length > 0) {
                        errorsCount.textContent = data.errors_history.length;
                        errorsData = data.errors_history;
                    } else {
                        errorsCount.textContent = '0';
                        errorsData = [];
                        errorsCurrentPage = 1;
                    }
                    renderErrorsPage();

                    // Last Generated Images
                    const lastImageContainer = document.getElementById('last-image-container');
                    const lastImageTime = document.getElementById('last-image-time');

                    // Update time display
                    lastImageTime.textContent = formatTimeAgo(data.last_image_submission_timestamp);

                    if (data.last_image_base64 && data.last_image_base64.length > 0) {
                        if (data.last_image_base64.length === 1) {
                            // Single image - display in centered layout
                            const imageSrc = `data:image/png;base64,${data.last_image_base64[0]}`;
                            lastImageContainer.innerHTML = `
                                <img src="${imageSrc}"
                                     class="single-image"
                                     alt="Last generated image"
                                     data-fullsize="${imageSrc}" />
                            `;
                        } else {
                            // Multiple images (batch job) - display in grid
                            const gridHtml = data.last_image_base64.map((imageBase64, index) => {
                                const imageSrc = `data:image/png;base64,${imageBase64}`;
                                return `
                                    <div class="image-grid-item">
                                        <img src="${imageSrc}"
                                             alt="Generated image ${index + 1}"
                                             data-fullsize="${imageSrc}" />
                                    </div>
                                `;
                            }).join('');
                            lastImageContainer.innerHTML = `<div class="image-grid">${gridHtml}</div>`;
                        }

                        // Add click handlers to all images
                        lastImageContainer.querySelectorAll('img[data-fullsize]').forEach(img => {
                            img.onclick = function() {
                                openImageOverlay(this.getAttribute('data-fullsize'));
                            };
                        });
                    } else {
                        lastImageContainer.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#128444;</span>No image generated yet</div>';
                    }

                    // Console Logs
                    const consoleLogsDiv = document.getElementById('console-logs');
                    if (data.console_logs && data.console_logs.length > 0) {
                        const wasScrolledToBottom = isScrolledToBottom(consoleLogsDiv, SCROLL_TOLERANCE_PX);
                        consoleLogsDiv.innerHTML = data.console_logs.map(log => {
                            const coloredLog = ansiToHtml(log);
                            return `<div style="margin: 2px 0; white-space: pre-wrap; word-break: break-word;">${coloredLog}</div>`;
                        }).join('');
                        // Auto-scroll to bottom if was already at bottom
                        if (wasScrolledToBottom) {
                            consoleLogsDiv.scrollTop = consoleLogsDiv.scrollHeight;
                        }
                    } else {
                        consoleLogsDiv.innerHTML = '<div style="text-align:center;color:#475569;padding:18px;">No logs available</div>';
                    }

                    // Update time
                    const nowStr = new Date().toLocaleTimeString();
                    document.getElementById('update-time').textContent = 'Last updated: ' + nowStr;
                    document.getElementById('sidebar-update-time').textContent = 'Last updated: ' + nowStr;
                })
                .catch(error => {
                    // Ignore aborted requests (these are intentional cancellations)
                    if (error.name === 'AbortError') {
                        return;
                    }

                    consecutiveErrors++;
                    console.error('Error fetching status:', error);

                    // If too many consecutive errors, show warning
                    if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
                        console.warn(
                            `Failed to fetch status ${consecutiveErrors} times in a row. Check server connection.`,
                        );
                    }
                })
                .finally(() => {
                    // Always reset the in-progress flag and controller reference
                    statusFetchInProgress = false;
                    statusAbortController = null;
                });
        }

        // Constants
        const DEFAULT_UPDATE_INTERVAL_MS = 1000;

        // Fetch config and start updates
        async function initializeUpdates() {
            try {
                const configResponse = await fetch('/api/config');
                const config = await configResponse.json();
                const updateInterval = config.update_interval_ms || DEFAULT_UPDATE_INTERVAL_MS;

                // Update immediately
                updateStatus();

                // Then set interval based on config
                setInterval(updateStatus, updateInterval);
            } catch (error) {
                console.error('Error fetching config:', error);
                // Fallback to default interval
                updateStatus();
                setInterval(updateStatus, DEFAULT_UPDATE_INTERVAL_MS);
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
            jobs_queued: Total number of jobs (jobs total) this session
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
