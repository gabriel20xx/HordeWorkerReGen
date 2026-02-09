# Job Retry and Status Visibility Enhancement

## Problem Statement

When users reported seeing logs like:
```
2026-02-09 08:50:19.087 | INFO     | Process 3 (MODEL_PRELOADED) (Nova Anime XL stable_diffusion_xl)) 
                                     [last message: 209.42 secs ago: START_INFERENCE heartbeat delta: 209.43]
2026-02-09 08:50:19.087 | INFO     | Jobs:
2026-02-09 08:50:19.087 | INFO     |   
```

They asked: **"What happened here? Did it even retry the jobs?"**

The issue was that the status logging made it impossible to answer this question because:
1. The "Jobs:" section only showed pending jobs, not jobs currently in progress
2. When jobs were retried, the logging wasn't clear enough to see if the retry actually happened

## Root Cause

The process was likely stuck on an inference job (Process 3 shows START_INFERENCE 209 seconds ago), but:
- The timeout threshold is 600 seconds by default, so it hadn't been detected as stuck yet
- The Jobs section was empty because it only showed `jobs_pending_inference`, not `jobs_in_progress`
- The user couldn't tell if the job was still being worked on or had been lost

## Solution

### 1. Enhanced Job Status Logging

**Before:**
```
Jobs:
  No pending jobs
```

**After:**
```
Jobs:
  In Progress: <abc12345: Nova Anime XL>
  Pending: <def67890: WAI-NSFW-illustrious-SDXL>, <ghi09876: Pony Diffusion>
```

Or when there are no jobs:
```
Jobs:
  No active jobs
```

The status now clearly shows:
- **In Progress**: Jobs currently being processed by workers
- **Pending**: Jobs waiting to be assigned to a free worker
- **No active jobs**: When both lists are empty

### 2. Enhanced Job Statistics

**Before:**
```
pending: 2 (150 eMPS) | popped: 42 | done: 40 | faulted: 1 | slow: 0 | recoveries: 0 | no jobs: 0.0s
```

**After:**
```
in progress: 1 | pending: 2 (150 eMPS) | popped: 42 | done: 40 | faulted: 1 | slow: 0 | recoveries: 0 | no jobs: 0.0s
```

Now you can immediately see how many jobs are actively being processed.

### 3. Improved Retry Logging

**Before:**
```
2026-02-09 08:50:20.123 | WARNING  | Job abc12345 faulted, retrying (retry attempt 1 of 1)
2026-02-09 08:50:20.124 | INFO     | Job abc12345 re-queued for retry
```

**After:**
```
2026-02-09 08:50:20.123 | WARNING  | Job abc12345 faulted on process 3, retrying (attempt 1 of 1)
2026-02-09 08:50:20.124 | SUCCESS  | ✓ Job abc12345 successfully re-queued for retry
```

Changes:
- Added **process ID** to fault message for better debugging
- Changed retry success message to use **SUCCESS** level with **✓ checkmark** for high visibility
- More concise wording ("attempt X of Y" instead of "retry attempt X of Y")

## Understanding Stuck Job Detection

When a process appears stuck, the system will:

1. **Monitor Progress**: Track if the job is making progress (percent complete advancing)
2. **Monitor Heartbeats**: Track if the process is sending any heartbeats
3. **Trigger Timeout**: After `inference_step_timeout` seconds (default: 600s = 10 minutes):
   - Log an ERROR with detailed information about the stuck job
   - Replace the stuck process with a fresh one
   - Fault the job, which triggers retry logic
4. **Retry Job**: If retry count < MAX_JOB_RETRIES (default: 1):
   - Log WARNING about the fault
   - Remove from jobs_in_progress
   - Re-queue to jobs_pending_inference
   - Log SUCCESS with ✓ when successfully re-queued

## Example Scenarios

### Scenario 1: Job Stuck But Not Timed Out Yet

**Logs:**
```
INFO | Process 3 (MODEL_PRELOADED) [last message: 209.42 secs ago: START_INFERENCE]
INFO | Jobs:
INFO |   In Progress: <abc12345: Nova Anime XL>
```

**What's happening:**
- Job is still in progress (209 seconds < 600 second timeout)
- System is waiting for timeout before declaring it stuck
- No action taken yet

### Scenario 2: Job Detected As Stuck and Retried

**Logs:**
```
ERROR | HordeProcessInfo(process_id=3) seems to be stuck mid inference - 
        Last heartbeat: 2.3s ago, Last progress change: 605.0s ago, 
        Progress: 42%, Job: abc12345
WARNING | Job abc12345 faulted on process 3, retrying (attempt 1 of 1)
SUCCESS | ✓ Job abc12345 successfully re-queued for retry
INFO | Replacing inference process 3
INFO | Jobs:
INFO |   Pending: <abc12345: Nova Anime XL>
```

**What's happening:**
- Job exceeded timeout (605s > 600s)
- Process 3 was stuck at 42% progress
- Job was faulted and successfully re-queued for retry
- Process 3 was replaced with a fresh process
- Job is now pending, waiting for a free process

### Scenario 3: Job Exhausted Retries

**Logs:**
```
ERROR | HordeProcessInfo(process_id=3) seems to be stuck mid inference - Job: abc12345
WARNING | Job abc12345 faulted on process 3, retrying (attempt 1 of 1)
SUCCESS | ✓ Job abc12345 successfully re-queued for retry
... (later) ...
ERROR | HordeProcessInfo(process_id=2) seems to be stuck mid inference - Job: abc12345
ERROR | Job abc12345 faulted after 1 retry attempt, marking as permanently faulted
```

**What's happening:**
- Job was retried but failed again on a different process
- Job has exhausted all retry attempts (MAX_JOB_RETRIES = 1)
- Job is now permanently faulted and won't be retried again

## Configuration

### Adjust Timeout Threshold

If you see too many stuck job detections, increase the timeout in `bridgeData.yaml`:

```yaml
inference_step_timeout: 900  # Increase from default 600 (10 minutes to 15 minutes)
```

Recommended settings:
- **High-end GPUs** (RTX 4090, A100): 300-600 seconds
- **Mid-range GPUs** (RTX 3080, 4070): 600-900 seconds
- **Low-end GPUs** (GTX 1660, RTX 3060): 900-1200 seconds

### Adjust Retry Count

To allow more retry attempts, change `MAX_JOB_RETRIES` in the code (currently hardcoded to 1):

```python
MAX_JOB_RETRIES = 1  # Number of retries for faulted jobs
```

## Benefits

1. **Better Visibility**: Can now see at a glance which jobs are in progress vs pending
2. **Clearer Debugging**: Process ID in fault messages helps identify problematic processes
3. **Obvious Success**: Green SUCCESS messages with ✓ make successful retries unmissable
4. **Complete Picture**: Job statistics now include in-progress count for full visibility

## Impact on Your Question

For your specific log snippet showing Process 3 stuck at 209 seconds:

**Before this fix:**
- You couldn't tell if a job was in progress
- Impossible to know if retries happened
- Had to dig through logs to find answers

**After this fix:**
- You'll see "In Progress: <job_id: model_name>" if a job is being worked on
- You'll see "Pending: <job_id: model_name>" if the job was re-queued for retry
- You'll see SUCCESS messages with ✓ when retries happen
- You'll see "in progress: X" in the statistics line

If the job was stuck for less than 600 seconds (like your 209 seconds), you'll see it in the "In Progress" section, confirming the system is still waiting for it to complete or timeout.

---

**Version**: 1.0  
**Date**: 2026-02-09
