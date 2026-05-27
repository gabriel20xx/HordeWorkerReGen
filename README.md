# AI Horde Worker reGen

Welcome to the [AI Horde](https://github.com/Haidra-Org/AI-Horde), a free and open decentralized platform for collaborative AI! The AI Horde enables people from around the world to contribute their GPU power to generate images, text, and more. By running a worker on your local machine, you can earn [kudos](https://github.com/Haidra-Org/haidra-assets/blob/main/docs/kudos.md) which give you priority when making your own requests to the horde.

A worker is a piece of software that handles jobs from the AI Horde, such as generating an image from a text prompt. When your worker successfully completes a job, you are rewarded with kudos. The more kudos you have, the faster your own requests will be processed.

You can read about [kudos](https://github.com/Haidra-Org/haidra-assets/blob/main/docs/kudos.md), the reward granted to you for running a worker, including some reasons for running a worker on our [detailed kudos explanation](https://github.com/Haidra-Org/haidra-assets/blob/main/docs/kudos.md).

## Contents

- [AI Horde Worker reGen](#ai-horde-worker-regen)
  - [Contents](#contents)
  - [Before You Begin](#before-you-begin)
  - [Installation](#installation)
    - [Windows](#windows)
      - [Option 1: Using Git (Recommended)](#option-1-using-git-recommended)
      - [Option 2: Without Git](#option-2-without-git)
    - [Linux](#linux)
    - [AMD GPUs](#amd-gpus)
    - [DirectML](#directml)
  - [Configuration](#configuration)
    - [Basic Settings](#basic-settings)
    - [Suggested Settings](#suggested-settings)
    - [Important Notes](#important-notes)
  - [Running the Worker](#running-the-worker)
    - [Starting](#starting)
    - [Stopping](#stopping)
    - [Monitoring](#monitoring)
    - [Multiple GPUs](#multiple-gpus)
  - [Updating](#updating)
    - [Updating the Worker](#updating-the-worker)
    - [Updating the Runtime](#updating-the-runtime)
  - [Custom Models](#custom-models)
  - [Docker](#docker)
  - [Environment Variables](#environment-variables)
  - [Support \& Troubleshooting](#support--troubleshooting)
  - [Model Usage \& Licenses](#model-usage--licenses)

## Before You Begin

Before installing the worker:

1. Register an account on the [AI Horde website](https://aihorde.net/register).
2. Securely store the API key you receive. **Treat this key like a password**.


## Installation

### Windows

#### Option 1: Using Git (Recommended)

1. Install [git for Windows](https://gitforwindows.org/) if you haven't already.
2. Open PowerShell or Command Prompt.
3. Navigate to the folder where you want to install the worker:

    > **Warning**: Do not use spaces in the installation path. For example, `C:\horde_worker` is good, while `C:\My Workers` is not.

    ```cmd
    cd C:\path\to\install\folder
    ```

4. Clone the repository:

   ```cmd
   git clone https://github.com/Haidra-Org/horde-worker-reGen.git
   cd horde-worker-reGen
   ```

#### Option 2: Without Git

1. Download the [zipped worker files](https://github.com/Haidra-Org/horde-worker-reGen/archive/refs/heads/main.zip).
2. Extract to a folder of your choice.

### Linux

Open a terminal and run:

```bash
git clone https://github.com/Haidra-Org/horde-worker-reGen.git
cd horde-worker-reGen
```

### AMD GPUs

AMD support is experimental, and **Linux-only** for now:

- Use `horde-bridge-rocm.sh` and `update-runtime-rocm.sh` in place of the standard versions.
- [WSL support](README_advanced.md#advanced-users-amd-rocm-inside-windows-wsl) is highly experimental.
- Join the [AMD discussion on Discord](https://discord.com/channels/781145214752129095/1076124012305993768) if you're interested in trying.

### DirectML

**Experimental** Support for DirectML has been added. See [Running on DirectML](README_advanced.md#advanced-users-running-on-directml) for more information and further instructions. You can now follow this guide using  `update-runtime-directml.cmd` and `horde-bridge-directml.cmd` where appropriate. Please note that DirectML is several times slower than *ANY* other methods of running the worker.

## Configuration

### Basic Settings

1. Copy `bridgeData_template.yaml` to `bridgeData.yaml`.
2. Edit `bridgeData.yaml` following the instructions inside.
3. Set a unique `dreamer_name`
  - If the name is already taken, you'll get a "Wrong Credentials" error. The name must be unique across the entire horde network.

### Suggested Settings

Tailor settings to your GPU, following these pointers:

- **24GB+ VRAM** (e.g. 3090, 4090):

  ```yaml
  - queue_size: 1 # <32GB RAM: 0, 32GB: 1, >32GB: 2
  - safety_on_gpu: true
  - high_memory_mode: true
  - high_performance_mode: true
  - unload_models_from_vram_often: false
  - max_threads: 1 # 2 is often viable for xx90 cards
  - post_process_job_overlap: true
  - queue_size: 2 # Set to 1 if max_threads: 2
  - max_power: 64 # Reduce if max_threads: 2
  - max_batch: 8 # Increase if max_threads: 1, decrease if max_threads: 2
  - allow_sdxl_controlnet: true
  ```

- **12-16GB VRAM** (e.g. 3080 Ti, 4070 Ti, 4080):

  ```yaml
  - queue_size: 1 # <32GB RAM: 0, 32GB: 1, >32GB: 2
  - safety_on_gpu: true # Consider false if using Cascade/Flux
  - moderate_performance_mode: true
  - unload_models_from_vram_often: false
  - max_threads: 1
  - max_power: 50
  - max_batch: 4 # Or higher
  ```

- **8-10GB VRAM** (e.g. 2080, 3060, 4060, 4060 Ti):

  ```yaml
  - queue_size: 1 # <32GB RAM: 0, 32GB: 1, >32GB: 2
  - safety_on_gpu: false
  - max_threads: 1
  - max_power: 32 # No higher
  - max_batch: 4 # No higher
  - allow_post_processing: false # If using SDXL/Flux, else can be true
  - allow_sdxl_controlnet: false
  ```

  - Also minimize other VRAM-consuming apps while the worker runs.

- **Lower-end GPUs / Under-performing Workers**:
  - `extra_slow_worker: true` gives more time per job, but users must opt-in. Only use if <0.3 MPS/S or <3000 kudos/hr consistently with correct config.
  - `limit_max_steps: true` caps total steps per job based on model.
  - `preload_timeout: 120` allows longer model load times. Avoid misusing to prevent kudos loss or maintenance mode.

- **Systems with less than 32GB of System RAM**:
  - Be sure to only run SD15 models and queue_size: 0.
    - Set `load_large_models: false`
    - To your `models_to_skip` add `ALL SDXL`, `ALL SD21`, and the 'unpruned' models (see config) to prevent running out of memory

### Important Notes

- Use an SSD, especially for multiple models. HDDs should offer one model only, loading within 60s.
- Configure 8GB (preferably 16GB+) of swap space, even on Linux.
- Keep `threads` ≤2 unless using a 48GB+ VRAM data center GPU.
- Worker RAM usage scales with `queue_size`. Use 1 for <32GB RAM, and optimize further for <16GB.
- SDXL needs ~9GB free RAM consistently (32GB+ total recommended).
- Flux and Stable Cascade need ~20GB free RAM consistently (48GB+ total recommended).
- Disable sleep/power-saving modes while the worker runs.

## Running the Worker

### Starting

> **Note**: The worker is resource-intensive. Avoid gaming or other heavy tasks while it runs. Turn it off or limit to small models at reduced settings if needed.

1. Install the worker as described in the [Installation](#installation) section.
2. Run `horde-bridge.cmd` (Windows) or `horde-bridge.sh` (Linux).
   - **AMD**: Use `horde-bridge-rocm` versions.

### Stopping

- Press `Ctrl+C` in the worker's terminal.
- It will finish current jobs before exiting.

### Monitoring

#### Web UI

The worker includes a built-in web interface for monitoring status and progress:

- **Access**: Open `http://localhost:3000` in your browser (default port)
- **Real-time updates**: Status refreshes automatically every 2 seconds
- **Information displayed**:
  - Worker name and status (Active/Maintenance)
  - Session uptime and statistics
  - Current job progress with live percentage
  - Jobs total, completed, faulted, and recovered
  - Kudos earned (session and total)
  - Active models loaded
  - Process states
  - System resources (RAM/VRAM usage)

To enable/disable or configure the web UI, edit `bridgeData.yaml`:

```yaml
enable_webui: true  # Set to false to disable
webui_port: 3000    # Change if you have a port conflict
```

#### Terminal and Logs

Watch the terminal for progress, completed jobs, kudos earned, stats, and errors.

The terminal output now features:
- 🎨 **Colorful log levels** - Color-coded messages (INFO=cyan, SUCCESS=green, WARNING=yellow, ERROR=red)
- 📝 **Compact format** - Worker info, kudos, and memory on single lines
- 🔇 **Clean output** - DEBUG messages hidden by default

**Log Level Control:**

Set log level using the `AIWORKER_LOG_LEVEL` environment variable (default: `INFO`):

```bash
# For Docker
docker run -e AIWORKER_LOG_LEVEL=INFO ...

# For direct execution
export AIWORKER_LOG_LEVEL=INFO  # Default - shows INFO, SUCCESS, WARNING, ERROR, CRITICAL
export AIWORKER_LOG_LEVEL=DEBUG # Verbose - shows all messages including debug
export AIWORKER_LOG_LEVEL=WARNING # Quiet - only warnings and errors
./horde-bridge.sh
```

Valid levels: `TRACE`, `DEBUG`, `INFO`, `SUCCESS`, `WARNING`, `ERROR`, `CRITICAL`

**Legacy debug flag:**
```bash
export AIWORKER_DEBUG=1  # Equivalent to AIWORKER_LOG_LEVEL=DEBUG
./horde-bridge.sh
```

**Or use the `-v` flag for verbose output:**
```bash
./horde-bridge.sh -vvv  # Maximum verbosity
```

Detailed logs are in the `logs` directory:

- `bridge*.log`: All info
  - `bridge.log` is the main window
  - `bridge_n.log` is process-specific (`n` is the process number)
- `trace*.log`: Errors and warnings only
  - `trace.log` is the main window
  - `trace_n.log` is process-specific

### Multiple GPUs

> **Future versions won't need multiple worker instances**

For now, start a separate worker per GPU.

On Linux, specify the GPU for each instance:

```bash
CUDA_VISIBLE_DEVICES=0 ./horde-bridge.sh -n "Instance 1"
CUDA_VISIBLE_DEVICES=1 ./horde-bridge.sh -n "Instance 2"
```

**Warning**: High RAM (32-64GB+) is needed for multiple workers. `queue_size` and `max_threads` greatly impact RAM per worker.

## Updating

The worker is constantly improving. Follow development and get update notifications in our [Discord](https://discord.gg/3DxrhksKzn).

Script names below assume Windows (`.cmd`) and NVIDIA. For Linux use `.sh`, for AMD use `-rocm` versions.

### Updating the Worker

1. Stop the worker with `Ctrl+C`.
2. Update the files:
   - If you used `git clone`:
     - Open a terminal in the worker folder
     - Run `git pull`
   - If you used the zip download:
     - Delete the old `horde_worker_regen` folder
     - Download the [latest zip](https://github.com/db0/horde-worker-reGen/archive/refs/heads/main.zip)
     - Extract to the original location, overwriting existing files
3. Continue with [Updating the Runtime](#updating-the-runtime) below.

### Updating the Runtime

> **Warning**: Some antivirus software (e.g. Avast) may interfere with the update. If you get `CRYPT_E_NO_REVOCATION_CHECK` errors, disable antivirus, retry, then re-enable.

4. Run `update-runtime` for your OS to update dependencies.
   - Not all updates require this, but run it if unsure
   - **Advanced users**: see [README_advanced.md](README_advanced.md) for manual options
5. [Start the worker](#starting) again

## Custom Models

Serving custom models not in our reference requires the `customizer` role. Request it on Discord.

With the role:

1. Download your model files locally.
2. Reference them in `bridgeData.yaml`:

   ```yaml
   custom_models:
     - name: My Custom Model
       baseline: stable_diffusion_xl
       filepath: /path/to/model/file.safetensors
   ```

   Currently supported baselines:
    ```
        stable_diffusion_1
        stable_diffusion_2_768
        stable_diffusion_2_512
        stable_diffusion_xl
        stable_cascade
        flux_1
    ```
    > **Warning**: Flux.schnell series models are the only Flux models allowed; Flux.dev is *not* currently permitted. Do not attempt to offer Flux.dev, models derived from it, or models which contain data from it.
    See [`STABLE_DIFFUSION_BASELINE_CATEGORY` in horde_model_reference](https://github.com/Haidra-Org/horde-model-reference/blob/main/horde_model_reference/meta_consts.py#L86) for an up to date list.


3. Add the model `name` to your `models_to_load` list.

> Note: Do not use sexually explicit or excessively vulgar names for models.

If set up correctly, `custom_models.json` will appear in the worker directory on startup.

Notes:

- Custom model names can't match our existing model names
- The horde will treat them as SD 1.5 for kudos rewards and safety checks

## Docker

Docker images are at <https://hub.docker.com/r/tazlin/horde-worker-regen/tags>.

Detailed guide: [Dockerfiles/README.md](Dockerfiles/README.md)

Manual worker setup: [README_advanced.md](README_advanced.md)

## Environment Variables

All configuration options can be set via environment variables using the `AIWORKER_` prefix. This is useful for Docker deployments, CI/CD, or when you prefer not to use a config file.

Environment variables override values from the config file (`bridgeData.yaml`). You can also place them in a `.env` file in the worker directory.

### General / Identity

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_API_KEY` | string | `0000000000` | Your AI Horde API key |
| `AIWORKER_DREAMER_NAME` | string | `An Awesome Dreamer` | Worker name for image generation |
| `AIWORKER_WORKER_NAME` | string | `An Awesome AI Horde Worker` | Default worker name |
| `AIWORKER_CACHE_HOME` | string | `./` | Directory to store model files |
| `AIWORKER_TEMP_DIR` | string | `./tmp/` | Directory for temporary files (ideally fastest drive) |
| `AIWORKER_HORDE_URL` | string | *(default horde)* | Custom AI Horde URL (only change for private horde) |
| `AIWORKER_CIVITAI_API_TOKEN` | string | *(none)* | CivitAI API token for downloading LoRAs and login-required models |

### Capabilities

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_NSFW` | bool | `true` | Accept NSFW image jobs |
| `AIWORKER_CENSOR_NSFW` | bool | `false` | Censor NSFW content even when accepting NSFW jobs |
| `AIWORKER_ALLOW_IMG2IMG` | bool | `true` | Accept image-to-image jobs |
| `AIWORKER_ALLOW_PAINTING` | bool | `false` | Accept inpainting/painting jobs |
| `AIWORKER_ALLOW_UNSAFE_IP` | bool | `true` | Accept requests from flagged or unsafe IP addresses |
| `AIWORKER_ALLOW_POST_PROCESSING` | bool | `false` | Accept jobs with post-processing steps |
| `AIWORKER_ALLOW_CONTROLNET` | bool | `false` | Accept ControlNet jobs (requires ~12GB VRAM) |
| `AIWORKER_ALLOW_SDXL_CONTROLNET` | bool | `false` | Accept SDXL ControlNet jobs |
| `AIWORKER_ALLOW_LORA` | bool | `false` | Accept jobs that use LoRA models |
| `AIWORKER_REQUIRE_UPFRONT_KUDOS` | bool | `false` | Only accept jobs from users with enough kudos |
| `AIWORKER_LIMIT_MAX_STEPS` | bool | `false` | Cap inference steps to worker's configured max |
| `AIWORKER_EXTRA_SLOW_WORKER` | bool | `false` | Enable extra-slow-worker mode (forces conservative settings) |

### Performance

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_MAX_POWER` | int | `8` | Max resolution multiplier (64×64×8×max_power pixels) |
| `AIWORKER_MAX_BATCH` | int | `1` | Maximum images per batched inference job |
| `AIWORKER_MAX_THREADS` | int | `1` | Maximum concurrent inference threads |
| `AIWORKER_QUEUE_SIZE` | int | `1` | Number of jobs to hold in queue |
| `AIWORKER_MAX_ACTIVE_MODELS` | int | *(auto)* | Maximum active model slots (overrides auto-detection) |
| `AIWORKER_SAFETY_ON_GPU` | bool | `false` | Run safety model on GPU (~1.2 GB VRAM) |
| `AIWORKER_HIGH_MEMORY_MODE` | bool | `true` | Keep models in VRAM to reduce load times |
| `AIWORKER_VERY_HIGH_MEMORY_MODE` | bool | `false` | Aggressive VRAM retention (data-center GPUs only) |
| `AIWORKER_HIGH_PERFORMANCE_MODE` | bool | `true` | High throughput mode (RTX 4090 or better) |
| `AIWORKER_MODERATE_PERFORMANCE_MODE` | bool | `false` | Moderate performance mode (RTX 3080 or better) |
| `AIWORKER_UNLOAD_MODELS_FROM_VRAM_OFTEN` | bool | `true` | Unload models from VRAM between jobs |
| `AIWORKER_VERY_FAST_DISK_MODE` | bool | `false` | Load more models concurrently (fast SSD/NVMe) |
| `AIWORKER_POST_PROCESS_JOB_OVERLAP` | bool | `false` | Overlap post-processing with next inference job |
| `AIWORKER_CYCLE_PROCESS_ON_MODEL_CHANGE` | bool | `false` | Restart inference process on model change |
| `AIWORKER_MODEL_STICKINESS` | float | `0.0` | Chance (0–1) to prefer currently loaded models |
| `AIWORKER_RAM_TO_LEAVE_FREE` | string | `80%` | Amount of system RAM to leave free |
| `AIWORKER_VRAM_TO_LEAVE_FREE` | string | `80%` | Amount of VRAM to leave free |

### Models

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_MODELS_TO_LOAD` | list | *(empty)* | Models to load (comma-separated, or `ALL MODELS`, `top N`) |
| `AIWORKER_MODELS_TO_SKIP` | list | *(empty)* | Models to skip when using meta-instructions |
| `AIWORKER_DYNAMIC_MODELS` | bool | `false` | Auto-load models with high queue times |
| `AIWORKER_MAX_MODELS_TO_DOWNLOAD` | int | `10` | Max models to download when dynamic_models is enabled |
| `AIWORKER_NUMBER_OF_DYNAMIC_MODELS` | int | `1` | Number of dynamic models to load at a time |
| `AIWORKER_LOAD_LARGE_MODELS` | bool | `true` | Allow loading large models (Flux, SDXL, etc.) |
| `AIWORKER_MAX_LORA_CACHE_SIZE` | int | `10` | Max LoRA cache size in GB |
| `AIWORKER_DISABLE_DISK_CACHE` | bool | `false` | Disable disk cache for model spill-over |

### Timeouts

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_PROCESS_TIMEOUT` | int | `300` | Max seconds a job may run before being killed |
| `AIWORKER_POST_PROCESS_TIMEOUT` | int | `60` | Max seconds for post-processing |
| `AIWORKER_PRELOAD_TIMEOUT` | int | `80` | Max seconds to load a model |
| `AIWORKER_DOWNLOAD_TIMEOUT` | int | `121` | Max seconds for aux model download |
| `AIWORKER_INFERENCE_STEP_TIMEOUT` | int | `600` | Max seconds per inference step before stuck detection |

### Behavior

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_MINUTES_ALLOWED_WITHOUT_JOBS` | int | `30` | Minutes before warning about no jobs |
| `AIWORKER_AUTO_RESTART_ON_IDLE_MINUTES` | int | `60` | Auto-restart after N idle minutes (0=disabled, max 1440) |
| `AIWORKER_SUPPRESS_SPEED_WARNINGS` | bool | `false` | Suppress speed-related warning messages |
| `AIWORKER_EXIT_ON_UNHANDLED_FAULTS` | bool | `false` | Exit on unhandled faults instead of recovering |
| `AIWORKER_LIMITED_CONSOLE_MESSAGES` | bool | `false` | Only log submissions and status messages |
| `AIWORKER_STATS_OUTPUT_FREQUENCY` | int | `30` | Seconds between status line prints |
| `AIWORKER_PURGE_LORAS_ON_DOWNLOAD` | bool | `false` | Delete LoRA cache before downloading new LoRAs |
| `AIWORKER_REMOVE_MAINTENANCE_ON_INIT` | bool | `false` | Clear maintenance mode on startup |
| `AIWORKER_ALWAYS_DOWNLOAD` | bool | `true` | Always download models without prompting |

### Web UI

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_ENABLE_WEBUI` | bool | `true` | Enable the web UI |
| `AIWORKER_WEBUI_PORT` | int | `3000` | Port for the web UI |
| `AIWORKER_WEBUI_UPDATE_INTERVAL` | float | `1.0` | Seconds between web UI backend updates (0.5–10) |

### Logging & Debug

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_LOG_LEVEL` | string | `INFO` | Log level: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL |
| `AIWORKER_DEBUG` | flag | *(unset)* | Set to `1` for debug mode (equivalent to LOG_LEVEL=DEBUG) |
| `AIWORKER_DISABLE_TERMINAL_UI` | bool | `true` | Disable the terminal GUI |

### Other / Advanced

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AIWORKER_PRIORITY_USERNAMES` | list | *(empty)* | Additional usernames with priority access |
| `AIWORKER_BLACKLIST` | list | *(empty)* | Words that cause jobs to be rejected |
| `AIWORKER_CENSORLIST` | list | *(empty)* | Words that always trigger NSFW censor |
| `AIWORKER_EXTRA_STABLE_DIFFUSION_MODELS_FOLDERS` | list | *(empty)* | Extra folders to search for SD models |
| `AIWORKER_CAPTURE_KUDOS_TRAINING_DATA` | bool | `false` | Capture kudos training data |
| `AIWORKER_KUDOS_TRAINING_DATA_FILE` | string | *(none)* | File path for kudos training data |

> **Note:** Boolean values accept `true`/`false` (case-insensitive). List values can be comma-separated or use bracket syntax: `[item1, item2]` or `item1;item2`.



Check the [#local-workers Discord channel](https://discord.com/channels/781145214752129095/1076124012305993768) for the latest info and community support.

Common issues and fixes:

- **Download failures**: Check disk space and internet connection.
- **Job timeouts**:
  - Remove large models (Flux, Cascade, SDXL)
  - Lower `max_power`
  - Disable `allow_post_processing`, `allow_controlnet`, `allow_sdxl_controlnet`, and/or `allow_lora`
- **Out of memory**: Decrease `max_threads`, `max_batch`, or `queue_size` to reduce VRAM/RAM use. Close other intensive programs.
- **I have less kudos than I expect**: As a new user, 50% of your job reward kudos and 100% of uptime kudos are held in escrow until you become trusted after ~1 week of worker uptime. You'll then receive the escrowed kudos and earn full rewards immediately going forward.
- **My worker is in [maintenance mode](https://github.com/Haidra-Org/haidra-assets/blob/main/docs/definitions.md#maintenance)**: You can log into [artbot here](https://tinybots.net/artbot/settings) and use the [manage workers](https://tinybots.net/artbot/settings?panel=workers) page **with the worker on** and click "unpause" to take your worker out of maintenance mode.
  - **Note**: Workers are put into maintenance mode automatically by the server when the worker is failing to perform fast enough or if it is reporting that it failed too many jobs. You should investigate the [logs](logs/README.md) (search for "ERROR") to see what led to the issue. You can also [open an issue](https://github.com/Haidra-Org/horde-worker-reGen/issues) or ask in the [#local-workers channel](https://discord.com/channels/781145214752129095/1076124012305993768) in our [Discord](https://discord.gg/3DxrhksKzn).

[Open an issue](https://github.com/Haidra-Org/horde-worker-reGen/issues) to report bugs or request features. We appreciate your help!

## Model Usage & Licenses

Many bundled models use the [CreativeML OpenRAIL License](https://huggingface.co/spaces/CompVis/stable-diffusion-license). Please review it before use.
