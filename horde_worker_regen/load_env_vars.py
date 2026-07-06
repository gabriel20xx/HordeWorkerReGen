"""Contains the functions to load the environment variables from the config file."""

import os
import pathlib

from loguru import logger
from ruamel.yaml import YAML


def load_dotenv(dotenv_path: str = ".env") -> None:
    """Load environment variables from a .env file into os.environ.

    Only sets variables that are not already set. Supports basic .env syntax:
    key=value, quoted values, and comment lines starting with '#'.
    """
    p = pathlib.Path(dotenv_path)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if value and value[0] in ('"', "'") and len(value) >= 2 and value[-1] == value[0]:
                value = value[1:-1]
            os.environ.setdefault(key, value)


def load_env_vars_from_config() -> None:  # FIXME: there is a dynamic way to do this
    """Load the environment variables from the config file."""
    yaml = YAML()
    config_file = "bridgeData.yaml"
    template_file = "bridgeData_template.yaml"

    if not pathlib.Path(config_file).exists():
        if pathlib.Path(template_file).exists():
            raise FileNotFoundError(f"{template_file} found. Please set variables and rename it to {config_file}.")
        raise FileNotFoundError(f"{config_file} not found")

    # Users on windows occasionally use backslashes in their paths, which causes issues on loading.
    # We're going to load the file as text and print the lines with backslashes to the user, and instruct them to
    # replace them with forward slashes.

    with open(config_file, encoding="utf-8") as f:
        lines = f.readlines()
        found_backslashes = False
        for line in lines:
            # Comment lines can legitimately contain backslashes (e.g. "# was D:\models");
            # only values are a problem, so skip full-line comments.
            if line.lstrip().startswith("#"):
                continue
            if "\\" in line:
                print(f"Backslashes found in the following line:\n{line}")
                found_backslashes = True

                print(
                    "Please replace backslashes with forward slashes in the config file, "
                    "as backslashes are not supported.",
                )

                corrected_line = line.replace("\\", "/")
                print(f"Corrected line:\n{corrected_line}")

    if found_backslashes:
        import sys

        sys.exit(1)

    with open(config_file, encoding="utf-8") as f:
        config = yaml.load(f)

    # ruamel.yaml returns None for an empty or comment-only file. Treat that as an empty config so
    # the `in config` membership checks below don't raise `TypeError: argument of type 'NoneType'
    # is not iterable`. Any genuinely-missing required fields will surface a clear error during
    # downstream config validation rather than crashing startup here.
    if config is None:
        config = {}

    # See data_model.py's `def load_env_vars(self) -> None:`
    if "cache_home" in config and config["cache_home"] is not None:
        if os.getenv("AIWORKER_CACHE_HOME") is None:
            os.environ["AIWORKER_CACHE_HOME"] = str(config["cache_home"])
        else:
            print(
                "AIWORKER_CACHE_HOME environment variable already set. "
                "This will override the value for `cache_home` in the config file.",
            )

    if "max_lora_cache_size" in config:
        if os.getenv("AIWORKER_LORA_CACHE_SIZE") is None:
            try:
                lora_cache_mb = int(config["max_lora_cache_size"]) * 1024
            except (ValueError, TypeError) as e:
                raise ValueError(
                    "max_lora_cache_size must be an integer, but is not.",
                ) from e
            os.environ["AIWORKER_LORA_CACHE_SIZE"] = str(lora_cache_mb)
        else:
            print(
                "AIWORKER_LORA_CACHE_SIZE environment variable already set. "
                "This will override the value for `max_lora_cache_size` in the config file.",
            )
    if "civitai_api_token" in config and config["civitai_api_token"] is not None:
        if os.getenv("CIVIT_API_TOKEN") is None:
            os.environ["CIVIT_API_TOKEN"] = str(config["civitai_api_token"])
        else:
            print(
                "CIVIT_API_TOKEN environment variable already set. "
                "This will override the value for `civitai_api_token` in the config file.",
            )

    # A null/empty `horde_url` means "use the default horde"; skip the block entirely so we never
    # assign a non-string (e.g. None) to os.environ, which would raise `TypeError: str expected`.
    if "horde_url" in config and config["horde_url"]:
        known_ai_horde_urls = [
            "stablehorde.net",
            "aihorde.net",
        ]

        custom_horde_url = str(config["horde_url"])
        AI_HORDE_URL = os.getenv("AI_HORDE_URL")
        if custom_horde_url and any(url in custom_horde_url for url in known_ai_horde_urls):
            if AI_HORDE_URL is None or not AI_HORDE_URL:
                logger.debug("Using default AI Horde URL.")
        else:
            logger.warning(
                f"Using custom AI Horde URL `{custom_horde_url}`. Make sure this is correct and ends in `/api/`.",
            )
            os.environ["AI_HORDE_URL"] = custom_horde_url

    if "load_large_models" in config and os.getenv("AI_HORDE_MODEL_META_LARGE_MODELS") is None:
        config_value = config["load_large_models"]
        if config_value is True:
            os.environ["AI_HORDE_MODEL_META_LARGE_MODELS"] = "1"

    if "limited_console_messages" in config and os.getenv("AIWORKER_LIMITED_CONSOLE_MESSAGES") is None:
        config_value = config["limited_console_messages"]
        if config_value is True:
            os.environ["AIWORKER_LIMITED_CONSOLE_MESSAGES"] = "1"


if __name__ == "__main__":
    load_env_vars_from_config()
    logger.info("Environment variables loaded.")
