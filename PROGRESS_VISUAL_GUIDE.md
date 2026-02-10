# Granular Progress Bar - Visual Guide

## Progress Breakdown

```
0%                    20%                70%       80%       90%      100%
|---------------------|-------------------|---------|---------|---------|
|   Model Loading     |    Inference      | Post-Pr.| Safety  |  Submit |
|                     |                   |         |  Check  |         |
|   (Models/LoRAs)    | (Image Generation)|         |         |         |
```

## Detailed Stage Flow

### Stage 1: Model Loading (0-20%)
```
0%  -> JOB_RECEIVED
10% -> DOWNLOADING_MODEL, MODEL_LOADING, DOWNLOADING_AUX_MODEL (LoRAs)
20% -> MODEL_LOADED
```

### Stage 2: Inference (20-70%)
```
20% -> INFERENCE_STARTING (0% inference)
25% -> INFERENCE_PROCESSING (10% inference)
30% -> INFERENCE_PROCESSING (20% inference)
35% -> INFERENCE_PROCESSING (30% inference)
40% -> INFERENCE_PROCESSING (40% inference)
45% -> INFERENCE_PROCESSING (50% inference)
50% -> INFERENCE_PROCESSING (60% inference)
55% -> INFERENCE_PROCESSING (70% inference)
60% -> INFERENCE_PROCESSING (80% inference)
65% -> INFERENCE_PROCESSING (90% inference)
70% -> INFERENCE_PROCESSING (100% inference)
```

Formula: `overall_progress = 20 + (inference_progress × 0.5)`

### Stage 3: Post-Processing (70-80%)
```
70% -> INFERENCE_POST_PROCESSING (0% post-proc)
75% -> INFERENCE_POST_PROCESSING (50% post-proc)
79% -> INFERENCE_POST_PROCESSING (99% post-proc)
80% -> INFERENCE_COMPLETE
```

Formula: `overall_progress = 70 + (post_proc_progress × 0.1)`

### Stage 4: Safety Check (80-90%)
```
85% -> SAFETY_STARTING, SAFETY_EVALUATING
90% -> SAFETY_COMPLETE
```

### Stage 5: Submission (90-100%)
```
92% -> IMAGE_SAVING
95% -> IMAGE_SAVED
97% -> IMAGE_SUBMITTING
100% -> IMAGE_SUBMITTED
```

## Example Job Flow

A typical job progresses through these stages:

```
Time    State                           Progress  Stage
------  ------------------------------- --------  -------------------
0.0s    JOB_RECEIVED                    0%        Received
0.5s    DOWNLOADING_AUX_MODEL           10%       Model Loading
2.0s    MODEL_LOADED                    20%       Model Ready
2.5s    INFERENCE_STARTING              20%       Starting Inference
3.0s    INFERENCE_PROCESSING (10%)      25%       Inference
4.0s    INFERENCE_PROCESSING (30%)      35%       Inference
5.0s    INFERENCE_PROCESSING (50%)      45%       Inference
6.0s    INFERENCE_PROCESSING (70%)      55%       Inference
7.0s    INFERENCE_PROCESSING (90%)      65%       Inference
8.0s    INFERENCE_POST_PROCESSING       75%       Post-Processing
8.5s    INFERENCE_COMPLETE              80%       Complete
9.0s    SAFETY_EVALUATING               85%       Safety Check
9.5s    SAFETY_COMPLETE                 90%       Safety OK
10.0s   IMAGE_SAVING                    92%       Saving
10.2s   IMAGE_SAVED                     95%       Saved
10.5s   IMAGE_SUBMITTING                97%       Submitting
11.0s   IMAGE_SUBMITTED                 100%      Done!
```

## WebUI Display

The WebUI shows both the progress bar and the current state:

```
┌─────────────────────────────────────────────┐
│ Current Job                                 │
├─────────────────────────────────────────────┤
│ Job ID: abc12345                            │
│ Model: stable_diffusion_xl_base_1.0         │
│ Batch Size: 1x                              │
│ Steps: 30                                   │
│ State: Inference Processing                 │
│                                             │
│ Progress:                                   │
│ ████████████████████░░░░░░░░  45%          │
└─────────────────────────────────────────────┘
```

## Benefits Over Previous Implementation

### Before (Old)
```
0%                                           100%
|---------------------------------------------|
|              Inference Only                 |
```
- Only showed inference step progress
- Safety checks appeared instant (0% → 100%)
- Model loading not visible
- Submission not visible

### After (New)
```
0%    20%             70%    80%    90%    100%
|-----|---------------|------|------|------|
| Load|   Inference   | Post | Safe | Sub  |
```
- All stages visible
- Smooth progress through entire job
- Better time estimates
- Clear status at each stage
