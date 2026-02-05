"""Web server for the Horde Worker status UI."""

import json
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
            "uptime": 0,
            "session_start_time": time.time(),
            "jobs_popped": 0,
            "jobs_completed": 0,
            "jobs_faulted": 0,
            "kudos_earned_session": 0.0,
            "kudos_per_hour": 0.0,
            "current_job": None,
            "job_queue": [],
            "processes": [],
            "models_loaded": [],
            "ram_usage_mb": 0,
            "vram_usage_mb": 0,
            "total_vram_mb": 0,
            "maintenance_mode": False,
            "user_kudos_total": 0.0,
            "last_image_base64": None,
            "console_logs": [],
            "faulted_jobs_history": [],
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
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Horde Worker Status</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            padding: 20px;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        h1 {
            color: white;
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.15);
        }
        
        .card h2 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.3em;
            border-bottom: 2px solid #667eea;
            padding-bottom: 8px;
        }
        
        .stat {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        
        .stat:last-child {
            border-bottom: none;
        }
        
        .stat-label {
            color: #666;
            font-weight: 500;
        }
        
        .stat-value {
            color: #333;
            font-weight: 600;
            font-size: 1.1em;
        }
        
        .stat-value.success {
            color: #10b981;
        }
        
        .stat-value.warning {
            color: #f59e0b;
        }
        
        .stat-value.error {
            color: #ef4444;
        }
        
        .progress-bar-container {
            width: 100%;
            height: 30px;
            background: #f0f0f0;
            border-radius: 15px;
            overflow: hidden;
            margin: 10px 0;
            position: relative;
        }
        
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 0.9em;
        }
        
        .process-list {
            max-height: 300px;
            overflow-y: auto;
        }
        
        .process-item {
            background: #f8f9fa;
            padding: 10px;
            margin: 8px 0;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        
        .process-id {
            font-weight: 600;
            color: #667eea;
        }
        
        .process-state {
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }
        
        .job-queue {
            max-height: 200px;
            overflow-y: auto;
        }
        
        .job-item {
            background: #f8f9fa;
            padding: 8px 12px;
            margin: 6px 0;
            border-radius: 6px;
            font-size: 0.9em;
        }
        
        .job-id {
            font-family: monospace;
            color: #667eea;
            font-weight: 600;
        }
        
        .faulted-jobs-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-height: 400px;
            overflow-y: auto;
        }
        
        .faulted-job-item {
            background: #fff5f5;
            border: 1px solid #fecaca;
            border-left: 4px solid #dc2626;
            padding: 12px;
            border-radius: 6px;
            font-size: 0.9em;
        }
        
        .faulted-job-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid #fecaca;
        }
        
        .faulted-job-id {
            font-family: monospace;
            color: #dc2626;
            font-weight: 700;
            font-size: 0.95em;
        }
        
        .faulted-job-time {
            color: #666;
            font-size: 0.85em;
        }
        
        .faulted-job-details {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 8px;
            margin-top: 8px;
        }
        
        .faulted-job-detail {
            display: flex;
            flex-direction: column;
        }
        
        .faulted-job-label {
            color: #666;
            font-size: 0.8em;
            font-weight: 600;
            text-transform: uppercase;
            margin-bottom: 2px;
        }
        
        .faulted-job-value {
            color: #333;
            font-weight: 500;
        }
        
        .faulted-job-lora {
            background: #fef3c7;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.85em;
            display: inline-block;
            margin: 2px;
        }
        
        .faulted-job-controlnet {
            background: #dbeafe;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.85em;
            display: inline-block;
            color: #1e40af;
            font-weight: 600;
        }
        
        .faulted-job-section {
            margin-top: 8px;
        }
        
        .faulted-job-section-label {
            display: block;
            margin-bottom: 4px;
        }
        
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .status-active {
            background: #d1fae5;
            color: #065f46;
        }
        
        .status-maintenance {
            background: #fef3c7;
            color: #92400e;
        }
        
        .update-time {
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 0.9em;
            opacity: 0.9;
        }
        
        .model-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        
        .model-badge {
            background: #e0e7ff;
            color: #4338ca;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.85em;
            font-weight: 500;
        }
        
        .loading {
            text-align: center;
            color: white;
            font-size: 1.2em;
            margin-top: 50px;
            animation: pulse 2s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .wide-card {
            grid-column: 1 / -1;
        }
        
        .last-image-container {
            min-height: 432px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .last-image-container img {
            max-width: 100%;
            max-height: 432px;
            width: auto;
            height: auto;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: block;
        .subsection-heading {
            color: #667eea;
            font-size: 1.1em;
            margin-bottom: 10px;
            border-bottom: 1px solid #e0e7ff;
            padding-bottom: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎨 Horde Worker Status</h1>
        <div id="loading" class="loading">Loading status...</div>
        <div id="content" style="display: none;">
            <div class="grid">
                <div class="card">
                    <h2>Worker Info</h2>
                    <div class="stat">
                        <span class="stat-label">Worker Name:</span>
                        <span class="stat-value" id="worker-name">-</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Status:</span>
                        <span id="worker-status-badge">-</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Uptime:</span>
                        <span class="stat-value" id="uptime">-</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Total Kudos:</span>
                        <span class="stat-value success" id="user-kudos-total">-</span>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Session Stats</h2>
                    <div class="stat">
                        <span class="stat-label">Jobs Popped:</span>
                        <span class="stat-value" id="jobs-popped">0</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Jobs Completed:</span>
                        <span class="stat-value success" id="jobs-completed">0</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Jobs Faulted:</span>
                        <span class="stat-value error" id="jobs-faulted">0</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">Kudos/Hour:</span>
                        <span class="stat-value success" id="kudos-per-hour">0</span>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Resources</h2>
                    <div class="stat">
                        <span class="stat-label">RAM Usage:</span>
                        <span class="stat-value" id="ram-usage">-</span>
                    </div>
                    <div class="stat">
                        <span class="stat-label">VRAM Usage:</span>
                        <span class="stat-value" id="vram-usage">-</span>
                    </div>
                    <div>
                        <div style="margin-top: 15px; margin-bottom: 5px; color: #666; font-weight: 500;">VRAM:</div>
                        <div class="progress-bar-container">
                            <div class="progress-bar" id="vram-progress" style="width: 0%">0%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="grid">
                <div class="card">
                    <h2>Current Job</h2>
                    <div id="current-job">
                        <div style="text-align: center; color: #999; padding: 20px;">No job in progress</div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Job Queue & Active Models</h2>
                    <div style="margin-bottom: 20px;">
                        <h3 class="subsection-heading">
                            Job Queue (<span id="queue-count">0</span>)
                        </h3>
                        <div id="job-queue" class="job-queue">
                            <div style="text-align: center; color: #999; padding: 20px;">Queue is empty</div>
                        </div>
                    </div>
                    <div>
                        <h3 class="subsection-heading">
                            Active Models
                        </h3>
                        <div id="models-loaded" class="model-list">
                            <div style="color: #999;">No models loaded</div>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Processes (<span id="process-count">0</span>)</h2>
                    <div id="processes" class="process-list">
                        <div style="text-align: center; color: #999; padding: 20px;">No process info</div>
                    </div>
                </div>
            </div>
            
            <div class="grid">
                <div class="card">
                    <h2>Last Generated Image</h2>
                    <div id="last-image-container" class="last-image-container">
                        <div style="text-align: center; color: #999; padding: 20px;">No image generated yet</div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>Console Output</h2>
                    <div id="console-logs" style="max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 0.85em; background: #1e1e1e; color: #d4d4d4; padding: 10px; border-radius: 6px;">
                        <div style="text-align: center; color: #999; padding: 20px;">No logs available</div>
                    </div>
                </div>
            </div>
            
            <div class="grid">
                <div class="card">
                    <h2>Faulted Jobs (<span id="faulted-jobs-count">0</span>)</h2>
                    <div id="faulted-jobs" class="faulted-jobs-list">
                        <div style="text-align: center; color: #999; padding: 20px;">No faulted jobs</div>
                    </div>
                </div>
            </div>
        </div>
        <div class="update-time" id="update-time">Last updated: Never</div>
    </div>
    
    <script>
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
        
        // Constants for UI behavior
        const SCROLL_TOLERANCE_PX = 1; // Pixel tolerance for scroll position detection
        
        // Helper function to check if element is scrolled to bottom
        function isScrolledToBottom(element, tolerance) {
            return element.scrollHeight - element.clientHeight <= element.scrollTop + tolerance;
        }
        
        // Helper function to escape HTML to prevent XSS
        function escapeHtml(str) {
            return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
                            // Bold - check if not already applied
                            if (!currentStyles.some(s => s.startsWith('font-weight:'))) {
                                currentStyles.push('font-weight:bold');
                            }
                        } else if (code === '2') {
                            // Dim/faint - reduce opacity
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
                            // Foreground color - replace existing color
                            currentStyles = currentStyles.filter(s => !s.startsWith('color:'));
                            currentStyles.push('color:' + colors[code]);
                        } else if (bgColors[code]) {
                            // Background color - replace existing bg color
                            currentStyles = currentStyles.filter(s => !s.startsWith('background-color:'));
                            currentStyles.push('background-color:' + bgColors[code]);
                        }
                    }
                }
            }
            
            return result;
        }
        
        function updateStatus() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('content').style.display = 'block';
                    
                    // Worker Info
                    document.getElementById('worker-name').textContent = data.worker_name;
                    
                    const statusBadge = document.getElementById('worker-status-badge');
                    if (data.maintenance_mode) {
                        statusBadge.innerHTML = '<span class="status-badge status-maintenance">Maintenance</span>';
                    } else {
                        statusBadge.innerHTML = '<span class="status-badge status-active">Active</span>';
                    }
                    
                    document.getElementById('uptime').textContent = formatUptime(data.uptime);
                    document.getElementById('user-kudos-total').textContent = 
                        data.user_kudos_total ? data.user_kudos_total.toLocaleString(undefined, {maximumFractionDigits: 2}) : '-';
                    
                    // Session Stats
                    document.getElementById('jobs-popped').textContent = data.jobs_popped;
                    document.getElementById('jobs-completed').textContent = data.jobs_completed;
                    document.getElementById('jobs-faulted').textContent = data.jobs_faulted;
                    document.getElementById('kudos-per-hour').textContent = 
                        data.kudos_per_hour.toLocaleString(undefined, {maximumFractionDigits: 2});
                    
                    // Resources
                    document.getElementById('ram-usage').textContent = formatBytes(data.ram_usage_mb * 1024 * 1024);
                    document.getElementById('vram-usage').textContent = formatBytes(data.vram_usage_mb * 1024 * 1024);
                    
                    const vramPercent = data.total_vram_mb > 0 
                        ? Math.round((data.vram_usage_mb / data.total_vram_mb) * 100) 
                        : 0;
                    const vramProgress = document.getElementById('vram-progress');
                    vramProgress.style.width = vramPercent + '%';
                    vramProgress.textContent = vramPercent + '%';
                    
                    // Current Job
                    const currentJobDiv = document.getElementById('current-job');
                    if (data.current_job) {
                        const job = data.current_job;
                        // Format state to be more readable
                        let stateDisplay = job.state || 'N/A';
                        if (job.state === 'INFERENCE_POST_PROCESSING') {
                            stateDisplay = 'Post Processing';
                        } else if (job.state === 'INFERENCE_COMPLETE') {
                            stateDisplay = 'Finished';
                        } else if (job.state === 'INFERENCE_STARTING') {
                            stateDisplay = 'Starting';
                        } else if (job.state) {
                            // Convert snake_case to Title Case
                            stateDisplay = job.state.split('_').map(word => 
                                word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
                            ).join(' ');
                        }
                        
                        currentJobDiv.innerHTML = `
                            <div class="stat">
                                <span class="stat-label">Job ID:</span>
                                <span class="stat-value job-id">${job.id || 'N/A'}</span>
                            </div>
                            <div class="stat">
                                <span class="stat-label">Model:</span>
                                <span class="stat-value">${job.model || 'N/A'}</span>
                            </div>
                            <div class="stat">
                                <span class="stat-label">State:</span>
                                <span class="stat-value">${stateDisplay}</span>
                            </div>
                            ${job.batch_size && job.batch_size > 1 ? `
                            <div class="stat">
                                <span class="stat-label">Batch Size:</span>
                                <span class="stat-value">${job.batch_size}x</span>
                            </div>
                            ` : ''}
                            ${job.progress !== null && job.progress !== undefined ? `
                            <div style="margin-top: 10px;">
                                <div style="margin-bottom: 5px; color: #666;">Progress:</div>
                                <div class="progress-bar-container">
                                    <div class="progress-bar" style="width: ${job.progress}%">${job.progress}%</div>
                                </div>
                            </div>
                            ` : ''}
                        `;
                    } else {
                        currentJobDiv.innerHTML = '<div style="text-align: center; color: #999; padding: 20px;">No job in progress</div>';
                    }
                    
                    // Job Queue
                    const queueDiv = document.getElementById('job-queue');
                    const queueCount = document.getElementById('queue-count');
                    queueCount.textContent = data.job_queue.length;
                    
                    if (data.job_queue.length > 0) {
                        queueDiv.innerHTML = data.job_queue.map(job => {
                            const batchInfo = job.batch_size && job.batch_size > 1 ? ` (${job.batch_size}x batch)` : '';
                            return `
                                <div class="job-item">
                                    <span class="job-id">${job.id || 'N/A'}</span>: ${job.model || 'Unknown model'}${batchInfo}
                                </div>
                            `;
                        }).join('');
                    } else {
                        queueDiv.innerHTML = '<div style="text-align: center; color: #999; padding: 20px;">Queue is empty</div>';
                    }
                    
                    // Models
                    const modelsDiv = document.getElementById('models-loaded');
                    if (data.models_loaded.length > 0) {
                        modelsDiv.innerHTML = data.models_loaded.map(model => 
                            `<div class="model-badge">${model}</div>`
                        ).join('');
                    } else {
                        modelsDiv.innerHTML = '<div style="color: #999;">No models loaded</div>';
                    }
                    
                    // Processes
                    const processesDiv = document.getElementById('processes');
                    const processCount = document.getElementById('process-count');
                    processCount.textContent = data.processes.length;
                    
                    if (data.processes.length > 0) {
                        processesDiv.innerHTML = data.processes.map(proc => `
                            <div class="process-item">
                                <div class="process-id">Process #${proc.id}: ${proc.type}</div>
                                <div class="process-state">${proc.state}</div>
                                ${proc.model ? `<div class="process-state">Model: ${proc.model}</div>` : ''}
                                ${proc.progress !== null && proc.progress !== undefined ? 
                                    `<div class="process-state">Progress: ${proc.progress}%</div>` : ''}
                            </div>
                        `).join('');
                    } else {
                        processesDiv.innerHTML = '<div style="text-align: center; color: #999; padding: 20px;">No process info</div>';
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
                                        <span class="faulted-job-value" style="color: #dc2626; font-weight: 600;">${escapeHtml(job.fault_phase)}</span>
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
                        faultedJobsDiv.innerHTML = '<div style="text-align: center; color: #999; padding: 20px;">No faulted jobs</div>';
                    }
                    
                    // Last Generated Image
                    const lastImageContainer = document.getElementById('last-image-container');
                    if (data.last_image_base64) {
                        lastImageContainer.innerHTML = `
                            <img src="data:image/png;base64,${data.last_image_base64}" 
                                 alt="Last generated image" />
                        `;
                    } else {
                        lastImageContainer.innerHTML = '<div style="text-align: center; color: #999; padding: 20px;">No image generated yet</div>';
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
                        consoleLogsDiv.innerHTML = '<div style="text-align: center; color: #999; padding: 20px;">No logs available</div>';
                    }
                    
                    // Update time
                    document.getElementById('update-time').textContent = 
                        'Last updated: ' + new Date().toLocaleTimeString();
                })
                .catch(error => {
                    console.error('Error fetching status:', error);
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
        jobs_popped: int | None = None,
        jobs_completed: int | None = None,
        jobs_faulted: int | None = None,
        kudos_earned_session: float | None = None,
        kudos_per_hour: float | None = None,
        current_job: dict[str, Any] | None = None,
        job_queue: list[dict[str, Any]] | None = None,
        processes: list[dict[str, Any]] | None = None,
        models_loaded: list[str] | None = None,
        ram_usage_mb: float | None = None,
        vram_usage_mb: float | None = None,
        total_vram_mb: float | None = None,
        maintenance_mode: bool | None = None,
        user_kudos_total: float | None = None,
        last_image_base64: str | None = None,
        console_logs: list[str] | None = None,
        faulted_jobs_history: list[dict[str, Any]] | None = None,
    ) -> None:
        """Update the status data for the web UI.

        Args:
            worker_name: The name of the worker
            jobs_popped: Total number of jobs popped this session
            jobs_completed: Total number of jobs completed this session
            jobs_faulted: Total number of jobs faulted this session
            kudos_earned_session: Total kudos earned this session
            kudos_per_hour: Current kudos per hour rate
            current_job: Information about the current job being processed
            job_queue: List of jobs in the queue
            processes: List of process information
            models_loaded: List of currently loaded models
            ram_usage_mb: RAM usage in MB
            vram_usage_mb: VRAM usage in MB
            total_vram_mb: Total VRAM in MB
            maintenance_mode: Whether worker is in maintenance mode
            user_kudos_total: Total kudos accumulated by the user
            last_image_base64: Base64 encoded last generated image
            console_logs: Recent console log messages
            faulted_jobs_history: List of faulted jobs with details
        """
        if worker_name is not None:
            self.status_data["worker_name"] = worker_name
        if jobs_popped is not None:
            self.status_data["jobs_popped"] = jobs_popped
        if jobs_completed is not None:
            self.status_data["jobs_completed"] = jobs_completed
        if jobs_faulted is not None:
            self.status_data["jobs_faulted"] = jobs_faulted
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
        if maintenance_mode is not None:
            self.status_data["maintenance_mode"] = maintenance_mode
        if user_kudos_total is not None:
            self.status_data["user_kudos_total"] = user_kudos_total
        if last_image_base64 is not None:
            self.status_data["last_image_base64"] = last_image_base64
        if console_logs is not None:
            self.status_data["console_logs"] = console_logs
        if faulted_jobs_history is not None:
            self.status_data["faulted_jobs_history"] = faulted_jobs_history
        
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
