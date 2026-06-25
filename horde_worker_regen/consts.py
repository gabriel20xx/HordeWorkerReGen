"""Constants for the reGen bridge."""

BRIDGE_CONFIG_FILENAME = "bridgeData.yaml"

#: SQLite database used to persist the WebUI enabled/disabled model selections across restarts.
#:
#: The path can be overridden with the ``AIWORKER_WEBUI_MODEL_STATE_FILE`` environment variable.
#: By default the file is written to ``config/webui_model_state.db`` relative to the current working
#: directory (i.e. ``/horde-worker-reGen/config/webui_model_state.db`` inside Docker).
WEBUI_MODEL_STATE_FILENAME = "config/webui_model_state.db"

VERSION_META_REMOTE_URL = (
    "https://raw.githubusercontent.com/Haidra-Org/horde-worker-reGen/main/horde_worker_regen/_version_meta.json"
)


KNOWN_SLOW_MODELS_DIFFICULTIES = {"Stable Cascade 1.0": 6.0, "Flux.1-Schnell fp8 (Compact)": 6.0}
VRAM_HEAVY_MODELS = ["Stable Cascade 1.0", "Flux.1-Schnell fp16 (Compact)", "Flux.1-Schnell fp8 (Compact)"]
KNOWN_SLOW_WORKFLOWS = {"qr_code": 2.0}
KNOWN_CONTROLNET_WORKFLOWS = ["qr_code"]

BASE_LORA_DOWNLOAD_TIMEOUT = 45
EXTRA_LORA_DOWNLOAD_TIMEOUT = 15
MAX_LORAS = 5

TOTAL_LORA_DOWNLOAD_TIMEOUT = BASE_LORA_DOWNLOAD_TIMEOUT + (EXTRA_LORA_DOWNLOAD_TIMEOUT * MAX_LORAS)

MAX_SOURCE_IMAGE_RETRIES = 5

# Exit code the worker returns to its launch wrapper (horde-bridge.cmd / horde-bridge-directml.cmd)
# to request an automatic restart. Used on Windows, where os.execv() cannot replace the running
# process in-place (it spawns a new pid and exits the original, so the launching cmd.exe falls
# through to its `pause`). The Windows batch wrappers loop while the worker exits with this code.
# If you change this value, update the matching `if %ERRORLEVEL% EQU ...` checks in the .cmd files.
WORKER_RESTART_EXIT_CODE = 42
