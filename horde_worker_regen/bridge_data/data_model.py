"""The config model and initializers for the reGen configuration model."""

from __future__ import annotations

import json
import os
from typing import Any

from horde_sdk.ai_horde_worker.bridge_data import CombinedHordeBridgeData
from loguru import logger
from pydantic import BaseModel, Field, field_validator, model_validator
from ruamel.yaml import YAML

from horde_worker_regen.consts import TOTAL_LORA_DOWNLOAD_TIMEOUT
from horde_worker_regen.locale_info.regen_bridge_data_fields import BRIDGE_DATA_FIELD_DESCRIPTIONS


class PromptFilterGroup(BaseModel):
    """A named, togglable group of strings within a prompt filter type."""

    name: str = ""
    enabled: bool = True
    entries: list[str] = Field(default_factory=list)


class reGenBridgeData(CombinedHordeBridgeData):
    """The config model for reGen. Extra fields added here are specific to this worker implementation.

    See `CombinedHordeBridgeData` from the SDK for more information..
    """

    _loaded_from_env_vars: bool = False

    disable_terminal_ui: bool = Field(
        default=True,
    )

    safety_on_gpu: bool = Field(
        default=False,
    )
    """If true, the safety model will be run on the GPU."""

    _yaml_loader: YAML | None = None

    cycle_process_on_model_change: bool = Field(
        default=False,
    )
    """If true, the process will stop and restart when the model loaded changes.

    Warning: This can cause substantial delays in processing.
    """

    CIVIT_API_TOKEN: str | None = Field(
        default=None,
        alias="civitai_api_token",
    )
    """The API token for CivitAI, used for downloading LoRas and login-required models."""

    unload_models_from_vram_often: bool = Field(default=True)
    """If true, models will be unloaded from VRAM more often."""

    process_timeout: int = Field(default=180)
    """The maximum amount of time to allow a job to run before it is killed"""

    post_process_timeout: int = Field(default=60, ge=15)

    download_timeout: int = Field(default=TOTAL_LORA_DOWNLOAD_TIMEOUT + 1)
    """The maximum amount of time to allow an aux model to download before it is killed"""
    preload_timeout: int = Field(default=60, ge=15)
    """The maximum amount of time to allow a model to load before it is killed"""
    inference_step_timeout: int = Field(default=30, ge=10, le=1800)
    """The maximum amount of time (in seconds) to allow for inference progress before detecting a stuck job."""

    inference_timeout: int = Field(default=120, ge=60, le=7200)
    """Total time (seconds) allowed for all inference steps combined.

    If a process remains in an inference state longer than this, it is considered stuck and replaced,
    regardless of per-step heartbeat activity.
    """

    waiting_for_job_timeout: int = Field(default=600, ge=60, le=3600)
    """Seconds a WAITING_FOR_JOB process can be heartbeat-silent before being replaced (when local work is pending).

    The effective threshold is max(process_timeout, waiting_for_job_timeout). Default is 600s (10 min).
    """

    positive_prompt_append: list[PromptFilterGroup] = Field(default_factory=list)
    """Named groups of strings appended to every positive prompt before generation and gallery saving.
    The original unmodified prompt is preserved in the Horde submission metadata.
    """

    positive_prompt_remove: list[PromptFilterGroup] = Field(default_factory=list)
    """Named groups of strings removed from every positive prompt before generation and gallery saving."""

    positive_prompt_replace: list[PromptFilterGroup] = Field(default_factory=list)
    """Named groups of replacement rules for positive prompts in ``find==>replace`` format.
    ``find`` is matched as a whole word, case-insensitively; ``replace`` is inserted literally.
    The original unmodified prompt is preserved in the Horde submission metadata.
    """

    negative_prompt_append: list[PromptFilterGroup] = Field(default_factory=list)
    """Named groups of strings appended to every negative prompt before generation and gallery saving."""

    negative_prompt_remove: list[PromptFilterGroup] = Field(default_factory=list)
    """Named groups of strings removed from every negative prompt before generation and gallery saving."""

    negative_prompt_replace: list[PromptFilterGroup] = Field(default_factory=list)
    """Named groups of replacement rules for negative prompts in ``find==>replace`` format.
    ``find`` is matched as a whole word, case-insensitively; ``replace`` is inserted literally.
    """

    prompt_swap: list[PromptFilterGroup] = Field(default_factory=list)
    """Named groups of strings to swap between positive and negative prompts.
    If a string is found in the positive prompt it is moved to the negative prompt, and vice-versa.
    Presence is checked against the original (pre-filter) values before any modification.
    """

    @field_validator(
        "positive_prompt_append",
        "positive_prompt_remove",
        "positive_prompt_replace",
        "negative_prompt_append",
        "negative_prompt_remove",
        "negative_prompt_replace",
        "prompt_swap",
        mode="before",
    )
    @classmethod
    def _coerce_filter_groups(cls, v: Any) -> Any:
        """Accept old flat list[str] format by bundling all strings into one unnamed group."""
        if not isinstance(v, list):
            return []
        if v and all(isinstance(item, str) for item in v):
            return [{"name": "", "enabled": True, "entries": [s for s in v if s]}]
        return v

    prompt_remove_cleanup_separators: bool = True
    """When True, collapses any runs of commas/spaces left between removed strings into a single ', '.

    Example: removing ``"foo"`` and ``"bar"`` from ``"a, foo, bar, b"`` → ``"a, b"`` instead of
    ``"a, , , b"``.
    """

    prompt_append_separator: bool = True
    """When True, each appended string is joined to the running prompt with ``", "``.

    When False the string is concatenated directly (no separator inserted).
    """

    prompt_filters_enabled: bool = True
    """Master switch for all prompt filters.

    When False, no append/remove/replace operations are applied regardless of
    the individual filter lists.  Defaults to True (filters active).
    """

    positive_prompt_append_enabled: bool = True
    """When False, the positive append list is ignored even if non-empty."""

    positive_prompt_remove_enabled: bool = True
    """When False, the positive remove list is ignored even if non-empty."""

    positive_prompt_replace_enabled: bool = True
    """When False, the positive replace list is ignored even if non-empty."""

    negative_prompt_append_enabled: bool = True
    """When False, the negative append list is ignored even if non-empty."""

    negative_prompt_remove_enabled: bool = True
    """When False, the negative remove list is ignored even if non-empty."""

    negative_prompt_replace_enabled: bool = True
    """When False, the negative replace list is ignored even if non-empty."""

    prompt_swap_enabled: bool = True
    """When False, the swap list is ignored even if non-empty."""

    prompt_remove_whole_word: bool = False
    """When True, a remove entry only matches when it appears as a complete word
    (i.e. not as part of a longer word).  E.g. ``"cat"`` will not match ``"category"``.
    Implemented with ``\\b`` word-boundary anchors.
    """

    prompt_remove_case_sensitive: bool = True
    """When True (default), remove entries are matched with their exact capitalisation.
    When False, matching is case-insensitive (``"Cat"`` and ``"CAT"`` both match ``"cat"``).
    """

    minutes_allowed_without_jobs: int = Field(default=30, ge=0, lt=60 * 60)

    auto_restart_on_idle_minutes: int = Field(default=60, ge=0, le=1440, validate_default=True)
    """Automatically restart the worker program if no job has been submitted for this many minutes.

    Set to 0 to disable. The default is 60 minutes (1 hour).
    Can also be configured via the AIWORKER_AUTO_RESTART_IDLE_MINUTES environment variable.
    """

    force_restart_timeout: int = Field(default=30, ge=5, le=600, validate_default=True)
    """Maximum seconds to wait for a graceful shutdown to finish before forcing it.

    When the worker is restarting (most notably an auto-restart triggered by
    `auto_restart_on_idle_minutes`) and the graceful shutdown does not complete within this many
    seconds, the worker hard-kills its child processes and exits so the restart can proceed.
    The default is 30 seconds. Can also be configured via the AIWORKER_FORCE_RESTART_TIMEOUT
    environment variable.
    """

    horde_model_stickiness: float = Field(default=0.0, le=1.0, ge=0.0, alias="model_stickiness")
    """
    A percent chance (expressed as a decimal between 0 and 1) that the currently loaded models will
    be favored when popping a job.
    """

    high_memory_mode: bool = Field(default=True)
    """Indicates that the worker should consume more memory to improve performance."""

    very_high_memory_mode: bool = Field(default=False)
    """Indicates that the worker should consume even more memory to improve performance.

    This has data-center grade cards in mind, and is not recommended for consumer grade cards.
    """

    high_performance_mode: bool = Field(default=True)
    """If you have a 4090 or better, set this to true to enable high performance mode."""

    moderate_performance_mode: bool = Field(default=False)
    """If you have a 3080 or better, set this to true to enable moderate performance mode."""

    very_fast_disk_mode: bool = Field(default=False)
    """If you have a very fast disk, set this to true to concurrently load more models at a time from disk."""

    post_process_job_overlap: bool = Field(default=False)
    """High and moderate performance modes will skip post processing if this is set to true."""

    capture_kudos_training_data: bool = Field(default=False)

    kudos_training_data_file: str | None = Field(default=None)

    exit_on_unhandled_faults: bool = Field(default=False)
    """If true, the worker will exit if an unhandled fault occurs instead of attempting to recover."""

    purge_loras_on_download: bool = Field(default=False)

    remove_maintenance_on_init: bool = Field(default=True)
    """Automatically remove this worker from maintenance mode.

    When enabled, maintenance is cleared on startup AND continuously while the worker is running:
    whenever a job pop reports the worker is in maintenance mode, the worker automatically attempts
    to clear it (throttled), so it recovers even if maintenance is re-applied mid-run. When
    disabled, maintenance mode is left untouched.
    """

    load_large_models: bool = Field(default=True)

    custom_models: list[dict] = Field(
        default_factory=list,
    )

    limited_console_messages: bool = Field(default=False)
    """If true, the worker will only log for submit and the status message.

    Set stats_output_frequency (in seconds) for control over the status message.
    """

    enable_webui: bool = Field(default=True)
    """If true, the worker will start a web UI to display status and progress."""

    webui_port: int = Field(default=3000, ge=1024, le=65535)
    """The port to run the web UI on."""

    webui_update_interval: float = Field(default=1.0, ge=0.5, le=10.0)
    """The interval in seconds between web UI backend updates. Valid range: 0.5 to 10 seconds."""

    max_active_models: int | None = Field(default=None, ge=0)
    """Maximum number of active model slots.

    When set, this overrides the startup-derived value (max_threads + queue_size).
    A value of 0 (or ``AIWORKER_MAX_ACTIVE_MODELS=0``) is a sentinel meaning "use auto mode".
    """

    data_retention_days: int = Field(default=7, ge=1, le=3650, validate_default=True)
    """Number of days to retain errors, statistics snapshots, and gallery entries in the SQLite database.

    Can also be configured via the AIWORKER_DATA_RETENTION_DAYS environment variable.
    """

    @model_validator(mode="before")
    @classmethod
    def handle_deprecated_fields(cls, values: Any) -> Any:
        """Remap deprecated/renamed field keys before validation."""
        if isinstance(values, dict) and "lora_cache_size" in values:
            values = values.copy()
            lora_cache_size = values.pop("lora_cache_size")
            if "max_lora_cache_size" not in values:
                logger.warning(
                    "The `lora_cache_size` parameter is deprecated. Please rename it to `max_lora_cache_size` "
                    "in your bridge data file.",
                )
                values["max_lora_cache_size"] = lora_cache_size
        return values

    @model_validator(mode="after")
    def validate_performance_modes(self) -> reGenBridgeData:
        """Validate the performance modes and set the appropriate values.

        Returns:
            reGenBridgeData: The config model with the performance modes set appropriately.
        """
        if self.max_threads >= 2 and self.queue_size > 3:
            self.queue_size = 3
            logger.warning(
                "The queue_size value has been set to 3 because the max_threads value is 2.",
            )

        if self.high_performance_mode:
            process_timeout_changed_message = (
                "High performance mode is enabled, so the process_timeout value has "
                f"been set to 1/3 of the default value. The new value is {self.process_timeout}."
            )
            default_process_timeout = self.model_fields["process_timeout"].default

            if self.process_timeout == default_process_timeout:
                logger.debug(process_timeout_changed_message)
            else:
                logger.warning(process_timeout_changed_message)

            self.process_timeout = default_process_timeout // 3
        elif self.moderate_performance_mode:
            process_timeout_changed_message = (
                "Moderate performance mode is enabled, so the process_timeout value has "
                f"been set to 1/2 of the default value. The new value is {self.process_timeout}."
            )
            default_process_timeout = self.model_fields["process_timeout"].default

            if self.process_timeout == default_process_timeout:
                logger.debug(process_timeout_changed_message)
            else:
                logger.warning(process_timeout_changed_message)

            self.process_timeout = default_process_timeout // 2

        if self.extra_slow_worker:
            if self.high_performance_mode:
                self.high_performance_mode = False
                logger.warning(
                    "Extra slow worker is enabled, so the high_performance_mode value has been set to False.",
                )
            if self.moderate_performance_mode:
                self.moderate_performance_mode = False
                logger.warning(
                    "Extra slow worker is enabled, so the moderate_performance_mode value has been set to False.",
                )
            if self.high_memory_mode:
                self.high_memory_mode = False
                logger.warning(
                    "Extra slow worker is enabled, so the high_memory_mode value has been set to False.",
                )
            if self.very_high_memory_mode:
                self.very_high_memory_mode = False
                logger.warning(
                    "Extra slow worker is enabled, so the very_high_memory_mode value has been set to False.",
                )
            if self.queue_size > 0:
                self.queue_size = 0
                logger.warning(
                    "Extra slow worker is enabled, so the queue_size value has been set to 0. "
                    "This behavior may change in the future.",
                )
            if self.max_threads > 1:
                self.max_threads = 1
                logger.warning(
                    "Extra slow worker is enabled, so the max_threads value has been set to 1. "
                    "This behavior may change in the future.",
                )
            if self.preload_timeout < 120:
                self.preload_timeout = 120
                logger.warning(
                    "Extra slow worker is enabled, so the preload_timeout value has been set to 120. "
                    "This behavior may change in the future.",
                )

        if self.very_high_memory_mode and not self.high_memory_mode:
            self.high_memory_mode = True
            logger.debug(
                "Very high memory mode is enabled, so the high_memory_mode value has been set to True.",
            )

        if self.high_memory_mode:
            if self.queue_size == 0 and "queue_size" not in self.model_fields_set:
                logger.warning(
                    "High memory mode is enabled, you should consider setting queue_size to 1 or higher. "
                    "Increasing this value increases system memory usage. See the bridgeData_template.yaml for more "
                    "information.",
                )

            if self.unload_models_from_vram_often:
                logger.warning(
                    "High memory mode is enabled, you should consider setting unload_models_from_vram_often to False.",
                )

            if self.cycle_process_on_model_change:
                self.cycle_process_on_model_change = False
                logger.warning(
                    "High memory mode is enabled, so the cycle_process_on_model_change value has been set to False.",
                )

        return self

    @field_validator("auto_restart_on_idle_minutes", mode="after")
    @classmethod
    def validate_auto_restart_on_idle_minutes(cls, value: int) -> int:
        """Apply the environment variable override for the `auto_restart_on_idle_minutes` field."""
        env_val = os.getenv("AIWORKER_AUTO_RESTART_IDLE_MINUTES")
        if env_val is not None:
            try:
                parsed = int(env_val)
            except ValueError:
                logger.warning(
                    f"AIWORKER_AUTO_RESTART_IDLE_MINUTES environment variable has an invalid value: '{env_val}'. "
                    "It must be a non-negative integer. Ignoring.",
                )
                return value
            if parsed < 0:
                logger.warning(
                    f"AIWORKER_AUTO_RESTART_IDLE_MINUTES environment variable has a negative value: {parsed}. "
                    "It must be >= 0. Ignoring.",
                )
                return value
            if parsed > 1440:
                logger.warning(
                    f"AIWORKER_AUTO_RESTART_IDLE_MINUTES environment variable has an out-of-range value: {parsed}. "
                    "It must be <= 1440. Ignoring.",
                )
                return value
            logger.info(
                f"Config `auto_restart_on_idle_minutes` set by environment variable "
                f"`AIWORKER_AUTO_RESTART_IDLE_MINUTES` (value: {parsed}).",
            )
            return parsed
        return value

    @field_validator("force_restart_timeout", mode="after")
    @classmethod
    def validate_force_restart_timeout(cls, value: int) -> int:
        """Apply the environment variable override for the `force_restart_timeout` field."""
        env_val = os.getenv("AIWORKER_FORCE_RESTART_TIMEOUT")
        if env_val is not None:
            try:
                parsed = int(env_val)
            except ValueError:
                logger.warning(
                    f"AIWORKER_FORCE_RESTART_TIMEOUT environment variable has an invalid value: '{env_val}'. "
                    "It must be an integer between 5 and 600. Ignoring.",
                )
                return value
            if parsed < 5 or parsed > 600:
                logger.warning(
                    f"AIWORKER_FORCE_RESTART_TIMEOUT environment variable has an out-of-range value: {parsed}. "
                    "It must be between 5 and 600. Ignoring.",
                )
                return value
            logger.info(
                f"Config `force_restart_timeout` set by environment variable "
                f"`AIWORKER_FORCE_RESTART_TIMEOUT` (value: {parsed}).",
            )
            return parsed
        return value

    @field_validator("data_retention_days", mode="after")
    @classmethod
    def validate_data_retention_days(cls, value: int) -> int:
        """Apply the environment variable override for the `data_retention_days` field."""
        env_val = os.getenv("AIWORKER_DATA_RETENTION_DAYS")
        if env_val is not None:
            try:
                parsed = int(env_val)
            except ValueError:
                logger.warning(
                    f"AIWORKER_DATA_RETENTION_DAYS environment variable has an invalid value: '{env_val}'. "
                    "It must be a positive integer. Ignoring.",
                )
                return value
            if parsed < 1:
                logger.warning(
                    f"AIWORKER_DATA_RETENTION_DAYS environment variable has an out-of-range value: {parsed}. "
                    "It must be >= 1. Ignoring.",
                )
                return value
            if parsed > 3650:
                logger.warning(
                    f"AIWORKER_DATA_RETENTION_DAYS environment variable has an out-of-range value: {parsed}. "
                    "It must be <= 3650. Ignoring.",
                )
                return value
            logger.info(
                f"Config `data_retention_days` set by environment variable "
                f"`AIWORKER_DATA_RETENTION_DAYS` (value: {parsed}).",
            )
            return parsed
        return value

    @field_validator("dreamer_worker_name", mode="after")
    @classmethod
    def validate_dreamer_worker_name(cls, value: str) -> str:
        """Apply the environment variable override for the `dreamer_worker_name` field."""
        AIWORKER_DREAMER_WORKER_NAME = os.getenv("AIWORKER_DREAMER_WORKER_NAME")
        if AIWORKER_DREAMER_WORKER_NAME:
            logger.warning(
                "Config `dreamer_worker_name` set by environment variable `AIWORKER_DREAMER_WORKER_NAME`.",
            )
            return AIWORKER_DREAMER_WORKER_NAME

        return value

    def prepare_custom_models(self) -> None:
        """Prepare the custom models."""
        if os.getenv("HORDELIB_CUSTOM_MODELS"):
            logger.info(
                f"HORDELIB_CUSTOM_MODELS already set to '{os.getenv('HORDELIB_CUSTOM_MODELS')}. "
                "Doing nothing for custom models.",
            )
            return
        custom_models_dict = {}
        for model in self.custom_models:
            if not model.get("name"):
                logger.warning(f"Model name not specified for custom model entry {model}. Skipping")
                continue
            if not model.get("baseline"):
                logger.warning(f"Model baseline not specified for custom model entry {model}. Skipping")
                continue
            if not model.get("filepath"):
                logger.warning(f"Model filepath not specified for custom model entry {model}. Skipping")
                continue
            # TODO: Handle Stable Cascade models
            custom_models_dict[model["name"]] = {
                "name": model["name"],
                "baseline": model["baseline"],
                "type": "ckpt",
                "config": {"files": [{"path": model["filepath"]}]},
            }
        cwd = os.getcwd()
        if len(custom_models_dict) > 0:
            with open(f"{cwd}/custom_models.json", "w") as f:
                json.dump(custom_models_dict, f, indent=4)
        else:
            if os.path.exists(f"{cwd}/custom_models.json"):
                os.remove(f"{cwd}/custom_models.json")
        os.environ["HORDELIB_CUSTOM_MODELS"] = f"{cwd}/custom_models.json"

    @staticmethod
    def load_custom_models() -> None:
        """Load the custom models from the `custom_models.json` file."""
        cwd = os.getcwd()
        if not os.getenv("HORDELIB_CUSTOM_MODELS") and os.path.exists(f"{cwd}/custom_models.json"):
            os.environ["HORDELIB_CUSTOM_MODELS"] = f"{cwd}/custom_models.json"
            logger.debug(f"HORDELIB_CUSTOM_MODELS: {cwd}/custom_models.json")

    def load_env_vars(self) -> None:
        """Load the environment variables into the config model."""
        # See load_env_vars.py's `def load_env_vars(self) -> None:`
        if self.models_folder_parent and os.getenv("AIWORKER_CACHE_HOME") is None:
            os.environ["AIWORKER_CACHE_HOME"] = self.models_folder_parent
        if self.horde_url:
            if os.environ.get("AI_HORDE_URL"):
                logger.warning(
                    "AI_HORDE_URL environment variable already set. This will override the value for `horde_url` in "
                    "the config file.",
                )
            else:
                if os.environ.get("AI_HORDE_DEV_URL"):
                    logger.warning(
                        "AI_HORDE_DEV_URL environment variable already set. This will override the value for "
                        "`horde_url` in the config file.",
                    )
                if os.environ.get("AI_HORDE_URL") is None:
                    os.environ["AI_HORDE_URL"] = self.horde_url
                else:
                    logger.warning(
                        "AI_HORDE_URL environment variable already set. This will override the value for `horde_url` "
                        "in the config file.",
                    )

        if self.CIVIT_API_TOKEN is not None:
            os.environ["CIVIT_API_TOKEN"] = self.CIVIT_API_TOKEN

        if self.max_lora_cache_size and os.getenv("AIWORKER_LORA_CACHE_SIZE") is None:
            os.environ["AIWORKER_LORA_CACHE_SIZE"] = str(self.max_lora_cache_size * 1024)

        if self.load_large_models:
            os.environ["AI_HORDE_MODEL_META_LARGE_MODELS"] = "1"

    def save(self, file_path: str) -> None:
        """Save the config model to a file.

        Args:
            file_path (str): The path to the file to save the config model to.
        """
        if self._yaml_loader is None:
            self._yaml_loader = YAML()

        with open(file_path, "w", encoding="utf-8") as f:
            self._yaml_loader.dump(self.model_dump(), f)


# Dynamically add descriptions to the fields of the model
for field_name, field in reGenBridgeData.model_fields.items():
    if field_name in BRIDGE_DATA_FIELD_DESCRIPTIONS:
        field.description = BRIDGE_DATA_FIELD_DESCRIPTIONS[field_name]
