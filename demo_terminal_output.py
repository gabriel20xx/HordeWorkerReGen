#!/usr/bin/env python3
"""Demo script to show the improved terminal output formatting."""

import sys
from loguru import logger

# Add the project to path
sys.path.insert(0, '/home/runner/work/HordeWorkerReGen/HordeWorkerReGen')

from horde_worker_regen.logger_config import configure_logger_format

# Configure the logger
configure_logger_format()

# Demo different log levels with the new formatting
print("\n" + "="*80)
print("DEMO: Improved Terminal Output with Colors and Emojis")
print("="*80 + "\n")

# Simulate status header
logger.opt(ansi=True).info("<fg #00d7ff>╔" + "═" * 78 + "╗</>")

# Simulate different types of messages
logger.info("Worker:📊 Status - Starting demo of improved terminal output...")
logger.opt(ansi=True).info("<b><fg #00d7ff>🔧 Processes:</></b>")
logger.info("  Process #0: INFERENCE (Model: Stable Diffusion XL) - 67% complete")
logger.info("  Process #1: WAITING_FOR_JOB")
logger.info("  Process #2: SAFETY - Checking image safety")

logger.opt(ansi=True).info("<fg #00d7ff>├" + "─" * 78 + "┤</>")

logger.opt(ansi=True).info("<b><fg #00ff87>📋 Jobs:</></b>")
logger.info("  <abc123de: Stable Diffusion XL>, <def456gh: Flux Schnell>")

logger.opt(ansi=True).info("<fg #00ff87>  pending: 2 (128 eMPS) | popped: 42 | done: 38 | faulted: 2 | slow: 1 | recoveries: 0 | no jobs: 15.3s</>")

logger.opt(ansi=True).info("<fg #00d7ff>├" + "─" * 78 + "┤</>")

logger.opt(ansi=True).info("<b><fg #5fd7ff>⚙️  Worker Config:</></b>")
logger.info("  name: DemoWorker | v3.0.0 | user: TestUser | models: 5 | power: 32 (512x512) | threads: 1 | queue: 1")
logger.info("  unload_vram: False | high_perf: True | med_perf: False | high_mem: True")

logger.opt(ansi=True).info("<fg #00d7ff>╚" + "═" * 78 + "╝</>")

print()

# Demo kudos message
logger.opt(ansi=True).info("<fg #ffd700>💰 Kudos: Session: 625.38 kudos/hr | Uptime: 2.5 hours</>")
logger.opt(ansi=True).info("<fg #ffd700>💰 Total Accumulated: 52,341.25 (all workers for TestUser)</>")

print()

# Demo different log levels with emojis
logger.success("Worker:📩 New Job - Popped job abc123de (64 eMPS)")
logger.info("Worker:📥 Loading - Process 1 is downloading extra models (LoRas, etc.)")
logger.warning("Worker:⚠️  Recovery - Process seems slow, monitoring...")
logger.error("Worker:❌ Job Fault - Job 70c50eca faulted due to process 3 crashing")
logger.info("Worker:📤 Submitting - Job completed, submitting results to horde")
logger.success("Worker:🚀 Starting - Starting inference process on PID 3")
logger.info("Worker:🛑 Stopping - Ended inference process 3")

print()

# Demo shutdown message
logger.opt(ansi=True).warning("<fg #ff5f5f>╔" + "═" * 78 + "╗</>")
logger.opt(ansi=True).warning("<fg #ff5f5f>║ 🛑 SHUTTING DOWN - Finishing current jobs...                              ║</>")
logger.opt(ansi=True).warning("<fg #ff5f5f>╚" + "═" * 78 + "╝</>")

print("\n" + "="*80)
print("Demo complete! Output is now more colorful and readable!")
print("="*80 + "\n")
