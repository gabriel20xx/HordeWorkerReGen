# Granular Job Progress Bar Implementation

## Overview
This update enhances the job progress bar to show detailed progress across all stages of job processing, not just inference steps.

## Progress Stages

The progress bar is now divided into the following stages:

| Stage | Progress Range | Description |
|-------|----------------|-------------|
| Job Received | 0% | Job has been received but processing hasn't started |
| Model Loading | 0-20% | Downloading and loading model files, including LoRAs |
| Inference | 20-70% | Running inference (image generation) - scaled from HordeLib progress |
| Post-Processing | 70-80% | Post-processing operations after inference |
| Safety Check | 80-90% | Running safety checks (NSFW/CSAM detection) |
| Submission | 90-100% | Saving images and submitting results to API |

## Implementation Details

### Progress Calculation Method
The `_calculate_granular_progress()` method in `process_manager.py` maps `HordeProcessState` values to progress percentages:

```python
def _calculate_granular_progress(
    self,
    process_state: HordeProcessState,
    inference_progress: int | None,
) -> int:
    """Calculate overall job progress based on current stage and inference progress."""
```

### Key Features

1. **Proportional Scaling**: Inference progress (0-100%) is scaled to occupy 20-70% of the overall progress bar, reflecting that inference is the longest stage.

2. **Dynamic Progress**: The inference stage uses actual step progress from HordeLib when available, providing smooth progress updates.

3. **Safety Check Tracking**: Jobs being safety checked now show 80-90% progress instead of jumping to 100%.

4. **Submission Tracking**: Final submission stages (saving, submitting) show 90-100% progress.

5. **Failure Handling**: Failed jobs show progress at the point of failure rather than defaulting to 0%.

### State Mappings

#### Model Loading (0-20%)
- `JOB_RECEIVED`, `WAITING_FOR_JOB`, `PROCESS_STARTING`: 0%
- `DOWNLOADING_MODEL`, `DOWNLOADING_AUX_MODEL`: 10%
- `MODEL_PRELOADING`, `MODEL_LOADING`: 10%
- `DOWNLOAD_COMPLETE`, `MODEL_PRELOADED`, `MODEL_LOADED`: 20%

#### Inference (20-70%)
- `INFERENCE_STARTING`: 20%
- `INFERENCE_PROCESSING`: 20% + (inference_progress × 0.5)
  - 0% inference → 20% overall
  - 50% inference → 45% overall
  - 100% inference → 70% overall

#### Post-Processing (70-80%)
- `INFERENCE_POST_PROCESSING`, `POST_PROCESSING_STARTING`: 70% + (progress × 0.1)
- `INFERENCE_COMPLETE`, `POST_PROCESSING_COMPLETE`: 80%

#### Safety Check (80-90%)
- `SAFETY_STARTING`, `SAFETY_EVALUATING`: 85%
- `SAFETY_COMPLETE`: 90%

#### Submission (90-100%)
- `IMAGE_SAVING`: 92%
- `IMAGE_SAVED`: 95%
- `IMAGE_SUBMITTING`: 97%
- `IMAGE_SUBMITTED`: 100%

### WebUI Integration

The WebUI displays the calculated progress in the current job section:
- Progress bar shows the overall percentage
- State field shows the current stage name (e.g., "Inference Processing", "Safety Evaluating")
- Both fields update in real-time via the `/api/status` endpoint

## User Benefits

1. **Better Visibility**: Users can now see which stage their job is in, not just that it's "processing"
2. **Accurate Time Estimates**: The progress bar better reflects actual job completion time
3. **Reduced Confusion**: Jobs no longer appear to jump from 0% to 100% during safety checks
4. **Smooth Progress**: Continuous progress updates throughout all stages

## Testing

The implementation handles:
- All normal job processing states
- Failed jobs at various stages
- Jobs with and without LoRAs
- Batch jobs
- Jobs in safety check queue
- Jobs being submitted

## Compatibility

This change is backward compatible:
- No changes to message protocol
- No changes to WebUI API
- Only the progress calculation logic is enhanced
- Existing progress tracking infrastructure is reused
