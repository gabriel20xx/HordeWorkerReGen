# Fix for Processes Stuck in PROCESS_STARTING State

## Problem Description

Worker processes 1-3 were stuck in `PROCESS_STARTING` state with continuously increasing heartbeat deltas (253s → 283s → 314s, etc.), while Process 0 (SAFETY) was working normally. This prevented the worker from accepting new jobs, causing the entire worker to stall.

### Symptoms from Logs
```
Process 1 (PROCESS_STARTING) (No model loaded) [last message: 253.67 secs ago: None heartbeat delta: 253.67]
Process 2 (PROCESS_STARTING) (No model loaded) [last message: 253.67 secs ago: None heartbeat delta: 253.67]
Process 3 (PROCESS_STARTING) (No model loaded) [last message: 253.67 secs ago: None heartbeat delta: 253.67]
```

## Root Cause

The bug was in the `replace_hung_processes()` method in `process_manager.py` (lines 6176-6177):

```python
if self._last_pop_no_jobs_available:
    continue  # Skips ALL state-specific timeout checks!
```

When `_last_pop_no_jobs_available` is `True` (meaning the API returned "no jobs available"), the code would skip checking and replacing processes stuck in `PROCESS_STARTING` state. This caused processes that failed during initialization to remain stuck indefinitely.

### Why This Happens

1. Child processes must successfully complete initialization (`__init__()`) to transition from `PROCESS_STARTING` to `WAITING_FOR_JOB`
2. If initialization fails (e.g., import errors, library issues), the state change message is never sent
3. The process remains in `PROCESS_STARTING` state indefinitely
4. When no jobs are available, the recovery mechanism was **incorrectly skipped**
5. The stuck processes could never be replaced, causing the entire worker to stall

## Solution

### Main Fix: Separate Initialization State Checks

The fix separates `PROCESS_STARTING` checks from job-related state checks:

```python
else:
    # Check PROCESS_STARTING first - this should always be checked regardless of job availability
    # since processes should complete initialization even when no jobs are available
    if self._check_and_replace_process(
        process_info,
        self.bridge_data.preload_timeout,
        HordeProcessState.PROCESS_STARTING,
        "seems to be stuck starting",
    ):
        any_replaced = True

    # Skip other state checks if no jobs are available since those states are job-related
    if self._last_pop_no_jobs_available:
        continue

    # Check job-related states that only matter when jobs are being processed
    conditions: list[tuple[float, HordeProcessState, str]] = [...]
```

**Key Changes:**
1. `PROCESS_STARTING` is checked **first** and **always**, regardless of job availability
2. Job-related states (`MODEL_PRELOADING`, `DOWNLOADING_AUX_MODEL`, `INFERENCE_POST_PROCESSING`) are only checked when jobs are available
3. This ensures processes complete initialization properly, even during periods of no job availability

### Code Quality Improvements

**Refactored `_recently_recovered` flag setting:**
- Flag is now set **once** after the loop, only if any processes were replaced
- Timer thread is started once, preventing multiple concurrent timers
- Cleaner code with no duplicated flag assignments

**Added guard clause comment:**
- Clarified that the existing guard clause prevents cascading recoveries
- Made it explicit that only one timer thread can be active at a time

## Technical Details

### Configuration
- **Timeout**: `preload_timeout` (default: 80 seconds)
- **Recovery Action**: `_replace_inference_process()` kills and restarts the stuck process
- **Protection**: `_recently_recovered` flag prevents cascading recoveries for `inference_step_timeout` seconds (default: 600 seconds)

### Process Lifecycle
1. **PROCESS_STARTING**: Initial state when process spawns
2. **Normal Path**: Process completes `__init__()` → sends state change message → transitions to `WAITING_FOR_JOB`
3. **Failure Path**: Process fails during `__init__()` → stuck in `PROCESS_STARTING` → detected after `preload_timeout` → replaced

### State Categories
- **Initialization States** (must always be checked):
  - `PROCESS_STARTING` - Process initialization
  
- **Job-Related States** (only checked when jobs are being processed):
  - `MODEL_PRELOADING` - Loading a model for a job
  - `DOWNLOADING_AUX_MODEL` - Downloading LoRAs/aux models for a job
  - `INFERENCE_POST_PROCESSING` - Post-processing job results

## Impact

### Before Fix
- Processes stuck in `PROCESS_STARTING` would **never** recover when no jobs available
- Worker would appear functional but unable to accept new jobs
- Manual restart required to recover

### After Fix
- Stuck processes are detected and replaced after `preload_timeout` (80s)
- Worker automatically recovers from initialization failures
- System remains operational during no-job periods

## Testing

### Security
✅ CodeQL analysis passed with no vulnerabilities

### Manual Verification
The fix ensures:
1. Processes stuck in `PROCESS_STARTING` are detected regardless of job availability
2. Only one recovery timer runs at a time (guard clause protection)
3. No race conditions in flag setting (single point of flag assignment)

## Files Changed

- `horde_worker_regen/process_management/process_manager.py` (lines 6115-6192)

## Related Documentation

- `HUNG_JOBS_FIX.md` - Related fix for hung inference jobs (different issue)
- `bridgeData_template.yaml` - Configuration options for timeouts

## Future Considerations

### Maintainers Should Know
1. **Initialization vs Job States**: Always distinguish between initialization states (must check always) and job-related states (only check when processing jobs)
2. **Guard Clause**: The `_recently_recovered` guard at function entry is critical for preventing cascading recoveries
3. **Timeout Values**: `preload_timeout` controls how long to wait before replacing stuck initialization processes

### If This Issue Recurs
1. Check if `preload_timeout` is set too high (should be 80-120 seconds)
2. Look for child process initialization errors in logs
3. Verify HordeLib and dependencies are properly installed
4. Check for resource exhaustion (out of memory, GPU issues)

## Summary

This fix resolves a critical bug where worker processes could become permanently stuck during initialization when no jobs were available, causing the entire worker to stall indefinitely. The solution properly distinguishes between initialization states (which must always complete) and job-related states (which only matter when processing jobs).
