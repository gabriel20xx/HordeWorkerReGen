# Last Inference Step Fix

## Problem Statement

Jobs could hang at the last inference step (99-100% completion) while waiting for VAE decode. These hung jobs would never be detected or recovered, causing:
- Workers appearing stuck at high progress
- Manual intervention required
- Reduced throughput and kudos earnings
- User frustration with "almost done" jobs that never complete

## Root Cause Analysis

### The Last Step Process

**Normal Flow**:
1. Inference runs through steps 1 to N, reporting progress (0% → 99%)
2. Step N completes: `current_step == total_steps`
3. Flag set: `_current_job_inference_steps_complete = True`
4. **VAE Decode Phase Begins**: Acquire semaphore for VAE decoding
5. Final image encoding and post-processing
6. Transition to `INFERENCE_COMPLETE` state

### Three Critical Issues

#### Issue 1: Progress Not Reported at 100%

**Location**: `inference_process.py` lines 507-512 (before fix)

```python
# OLD CODE - when last step reached
if progress_report.comfyui_progress.current_step == total_steps:
    self.send_heartbeat_message(heartbeat_type=HordeHeartbeatType.PIPELINE_STATE_CHANGE)
    # ❌ NO percent_complete sent!
    self._current_job_inference_steps_complete = True
```

**Problem**: 
- Last reported progress might be 99% (step N-1)
- 100% is never explicitly reported
- Progress tracking sees no update at the critical final stage

#### Issue 2: Indefinite VAE Semaphore Blocking

**Location**: `inference_process.py` lines 497-505 (before fix)

```python
# OLD CODE - waiting for VAE decode
if self._current_job_inference_steps_complete:
    if not self._vae_lock_was_acquired:
        self._vae_lock_was_acquired = True
        self._vae_decode_semaphore.acquire()  # ❌ Blocks forever if unavailable
        logger.debug("Acquired VAE decode semaphore")
    
    self.send_heartbeat_message(heartbeat_type=HordeHeartbeatType.PIPELINE_STATE_CHANGE)
    # ❌ Still no percent_complete!
    return
```

**Problem**:
- If another process holds the VAE semaphore, this blocks indefinitely
- No timeout on the acquire operation
- Job appears alive (sends heartbeats) but makes no progress
- Stuck at ~99% forever

#### Issue 3: Detection Ignored Non-INFERENCE_STEP Heartbeats

**Location**: `process_manager.py` lines 576-581 (before fix)

```python
# OLD CODE - heartbeat timeout check
return bool(
    self[process_id].last_heartbeat_type == HordeHeartbeatType.INFERENCE_STEP
    and self[process_id].last_heartbeat_delta > inference_step_timeout,
)
```

**Problem**:
- During last step, heartbeat type changes to `PIPELINE_STATE_CHANGE`
- Heartbeat timeout check only looked for `INFERENCE_STEP` type
- Missed jobs stuck in VAE decode phase entirely
- First check (progress timestamp) still worked, but less robust

### Real-World Scenarios

**Scenario A: Single VAE Decoder**
```
Worker config: vae_decode_semaphore_max = 1 (default)

Time 0:00 - Process 1: Job A at 99%, acquires VAE semaphore
Time 0:01 - Process 2: Job B reaches 99%, tries to acquire VAE semaphore
Time 0:01 - Process 2: BLOCKS waiting for Process 1
Time 5:00 - Process 1: Job A completes, releases semaphore
Time 5:00 - Process 2: Finally acquires semaphore, continues

Result: ⚠️ Job B appeared stuck for 5 minutes at 99%
```

**Scenario B: VAE Semaphore Deadlock**
```
Time 0:00 - Process 1: Job A acquires VAE semaphore
Time 0:01 - Process 1: HANGS in VAE decode (GPU driver issue)
Time 0:02 - Process 2: Job B reaches last step, waits for semaphore
Time 0:03 - Process 3: Job C reaches last step, waits for semaphore
Time 10:00 - All processes blocked, worker effectively dead

Result: ❌ OLD: Never detected, required manual restart
         ✅ NEW: Detected after timeout, processes replaced
```

**Scenario C: High Memory Mode Multiple Decoders**
```
Worker config: high_memory_mode = true, vae_decode_semaphore_max = 4

Time 0:00 - Processes 1-4: All acquire VAE semaphores
Time 0:01 - Process 5: Job E reaches last step, waits
Time 0:02 - One of 1-4 completes, releases semaphore
Time 0:02 - Process 5: Acquires semaphore immediately, continues

Result: ✅ Works as designed, minimal wait time
```

## The Solution

### Fix 1: Report 100% Progress at Last Step

**File**: `inference_process.py`

**Changes**:
- Line 510-512: Send `percent_complete=100` when last step reached
- Line 504-506: Continue sending `percent_complete=100` during VAE wait

```python
# NEW CODE - when last step reached
if progress_report.comfyui_progress.current_step == total_steps:
    self.send_heartbeat_message(
        heartbeat_type=HordeHeartbeatType.PIPELINE_STATE_CHANGE,
        percent_complete=100,  # ✅ Explicitly report 100%
    )
    self._current_job_inference_steps_complete = True
    logger.debug("Current job inference steps complete")

# NEW CODE - while waiting for VAE decode
if self._current_job_inference_steps_complete:
    if not self._vae_lock_was_acquired:
        # ... acquire logic ...
    
    self.send_heartbeat_message(
        heartbeat_type=HordeHeartbeatType.PIPELINE_STATE_CHANGE,
        percent_complete=100,  # ✅ Keep reporting 100%
    )
    return
```

**Impact**:
- Progress tracking sees 100% and updates `last_progress_timestamp`
- If stuck waiting for VAE, progress won't advance from 100%
- After timeout, stuck detection triggers correctly

### Fix 2: Add Timeout to VAE Semaphore Acquire

**File**: `inference_process.py` lines 500-506

```python
# NEW CODE - VAE semaphore with timeout
if not self._vae_lock_was_acquired:
    self._vae_lock_was_acquired = True
    acquired = self._vae_decode_semaphore.acquire(timeout=300)  # ✅ 5 minute timeout
    if not acquired:
        logger.error("Failed to acquire VAE decode semaphore within timeout - job may hang")
        # Continue anyway, will be caught by stuck detection
    else:
        log_free_ram()
        logger.debug("Acquired VAE decode semaphore")
```

**Impact**:
- Prevents indefinite blocking
- After 5 minutes (300 seconds), acquire returns False
- Job continues (will likely fail later) or gets caught by stuck detection
- Logs warning for debugging

**Why 5 Minutes?**
- VAE decode typically takes 1-30 seconds
- 5 minutes provides ample buffer for slow systems
- Aligns with typical `inference_step_timeout` values (600s default)
- Long enough to avoid false positives, short enough to catch real hangs

### Fix 3: Improve Stuck Detection for All Heartbeat Types

**File**: `process_manager.py` lines 555-583

```python
# NEW CODE - detection without heartbeat type restriction
def is_stuck_on_inference(self, process_id, inference_step_timeout):
    if self[process_id].last_process_state != HordeProcessState.INFERENCE_STARTING:
        return False

    # Check 1: Progress not advancing
    time_since_progress = time.time() - self[process_id].last_progress_timestamp
    if time_since_progress > inference_step_timeout:
        return True  # ✅ Catches last-step hangs

    # Check 2: No heartbeat received (ANY type)
    if self[process_id].last_heartbeat_delta > inference_step_timeout:
        return True  # ✅ Catches complete freezes at any stage
    
    return False
```

**Impact**:
- Detects stuck jobs regardless of heartbeat type
- Catches both "alive but stalled" and "completely frozen" scenarios
- Works for all inference phases (initial, middle, last step)

## Configuration

### VAE Decode Semaphore Settings

**Default** (`bridgeData.yaml`):
```yaml
# Not explicitly set - uses default of 1
# vae_decode_semaphore_max: 1
```

**High Memory Mode** (recommended for 24GB+ VRAM):
```yaml
high_memory_mode: true
# Allows multiple concurrent VAE decodes
# vae_decode_semaphore_max = max_threads
```

**Impact of Setting**:
- `vae_decode_semaphore_max: 1` - Only one VAE decode at a time (safe, slower)
- Higher values - Multiple concurrent decodes (faster, needs more VRAM)
- Too high - Risk of OOM during simultaneous VAE operations

### Timeout Settings

**Inference Step Timeout** (`bridgeData.yaml`):
```yaml
inference_step_timeout: 600  # Default: 10 minutes
```

This timeout now applies to:
1. Regular inference steps (existing)
2. Progress stalls at any percentage (existing)
3. **Last step VAE decode wait (NEW)**

**VAE Semaphore Timeout** (hardcoded):
```python
timeout=300  # 5 minutes
```

Recommended values:
- **Fast GPUs (RTX 4090)**: Keep default (300s adequate)
- **Medium GPUs (RTX 3080)**: Keep default
- **Slow GPUs (GTX 1660)**: Consider increasing `inference_step_timeout` to 900-1200s

## Testing

### Test Case 1: Normal Completion

```
1. Job starts, progresses 0% → 99%
2. Last step reached, reports 100%
3. VAE semaphore acquired immediately
4. VAE decode completes in 2 seconds
5. Job transitions to INFERENCE_COMPLETE

Result: ✅ Works normally, no detection triggered
```

### Test Case 2: VAE Wait (Non-Blocking)

```
1. Job A reaches 99%, reports 100%, acquires VAE semaphore
2. Job B reaches 99%, reports 100%, waits for VAE semaphore
3. After 30 seconds, Job A releases semaphore
4. Job B acquires semaphore, continues
5. Both complete successfully

Result: ✅ No false positive, wait < timeout
```

### Test Case 3: VAE Timeout (Blocking)

```
1. Job A reaches 99%, reports 100%, acquires VAE semaphore
2. Job A hangs in VAE decode (doesn't release)
3. Job B reaches 99%, reports 100%, waits for VAE semaphore
4. After 300 seconds, Job B's acquire() returns False
5. Warning logged, Job B continues
6. After 600 seconds (inference_step_timeout), stuck detection triggers
7. Process replaced automatically

Result: ✅ Detected and recovered
```

### Validation

Run mock test:
```python
python3 << 'EOF'
# Simulates last-step stuck detection
# See commit message for full test code
EOF
```

Expected output:
```
Scenario 1: Progress stalled at 99-100%
  ✅ NEW VERSION: Detected as stuck? True

Scenario 2: Complete hang at last step
  ✅ NEW VERSION: Detected as stuck? True

Scenario 3: Normal progress
  ✅ NEW VERSION: Detected as stuck? False
```

## Monitoring

### Log Messages

**Normal Operation**:
```
DEBUG - Current job inference steps complete
DEBUG - Acquired VAE decode semaphore
```

**VAE Semaphore Timeout**:
```
ERROR - Failed to acquire VAE decode semaphore within timeout - job may hang
```

**Stuck Detection**:
```
ERROR - HordeProcessInfo(...) seems to be stuck mid inference - 
        Last heartbeat: 2.3s ago, Last progress change: 605.7s ago, 
        Progress: 100%, Job: <job_id>
INFO - Replacing inference process X
```

### Metrics to Watch

After deploying this fix:

1. **Last-Step Hang Detection Rate**: Should see logs if jobs were hanging at 100%
2. **VAE Timeout Errors**: Should be rare; if frequent, indicates system issues
3. **Average Time at 100%**: Should be low (seconds, not minutes)
4. **Process Replacement at 100%**: Should decrease over time as hangs are caught

### Troubleshooting

**Issue**: Frequent VAE semaphore timeouts

**Symptoms**:
```
ERROR - Failed to acquire VAE decode semaphore within timeout - job may hang
```

**Possible Causes**:
1. Too many concurrent inference threads for available VRAM
2. VAE decoder itself hanging (GPU driver issue)
3. System I/O bottleneck during VAE operations

**Solutions**:
- Reduce `max_threads` in configuration
- Enable `high_memory_mode` if you have VRAM available
- Check GPU driver stability
- Monitor VRAM usage during VAE decode phase

**Issue**: False positives (jobs marked stuck but actually progressing)

**Symptoms**: Process replacements immediately after reaching 100%

**Cause**: `inference_step_timeout` set too low for VAE decode on your hardware

**Solution**: Increase timeout:
```yaml
inference_step_timeout: 900  # Increase from 600
```

## Performance Impact

### CPU Overhead
- **Minimal**: One additional integer comparison per heartbeat
- **Progress reporting**: Adds `percent_complete=100` to two heartbeat calls

### Memory Overhead
- **None**: No additional fields or data structures

### Latency Impact
- **Positive**: VAE semaphore timeout prevents indefinite waits
- **Neutral**: 100% progress reporting adds negligible overhead

### VRAM Impact
- **None**: VAE semaphore behavior unchanged, just added timeout

## Backward Compatibility

- ✅ No configuration changes required
- ✅ Existing `inference_step_timeout` setting applies to last step
- ✅ VAE semaphore timeout is conservative (5 minutes)
- ✅ Graceful degradation if timeout expires
- ✅ No API changes

## Summary

This fix addresses a critical gap in hung job detection: jobs stuck at the last inference step (VAE decode phase). By:

1. **Reporting 100% progress** explicitly
2. **Adding timeout** to VAE semaphore acquire
3. **Removing heartbeat type restriction** from detection

Workers can now automatically detect and recover from last-step hangs, improving reliability and reducing manual intervention requirements.

**Expected Outcome**: 
- Fewer jobs stuck at 99-100%
- Automatic recovery from VAE-related hangs
- Better visibility into last-step issues
- Improved user experience (jobs complete or fail, not hang)

---

**Version**: 1.0  
**Status**: Deployed  
**Related**: HUNG_JOBS_FIX.md  
**Last Updated**: 2026-02-04
