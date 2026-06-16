import pathlib
import os

import pytest
from horde_model_reference.model_reference_manager import ModelReferenceManager
from horde_sdk.generic_api.consts import ANON_API_KEY
from ruamel.yaml import YAML

from horde_worker_regen.bridge_data.data_model import reGenBridgeData
from horde_worker_regen.bridge_data.load_config import BridgeDataLoader, ConfigFormat


def test_bridge_data_yaml() -> None:
    """Test that the bridge data template file can be loaded and parsed as YAML."""
    # bridge_data_filename = "bridgeData.yaml"
    bridge_data_filename = "bridgeData_template.yaml"
    bridge_data_raw: dict | None = None

    yaml = YAML(typ="safe")

    with open(bridge_data_filename, encoding="utf-8") as f:
        bridge_data_raw = yaml.load(f)

    assert bridge_data_raw is not None

    parsed_bridge_data = reGenBridgeData.model_validate(bridge_data_raw)

    assert parsed_bridge_data is not None
    assert parsed_bridge_data.disable_terminal_ui is False
    assert parsed_bridge_data.api_key == ANON_API_KEY

    assert parsed_bridge_data.meta_load_instructions is not None
    assert len(parsed_bridge_data.meta_load_instructions) == 1


def test_bridge_data_loader_yaml_template() -> None:
    """Test that the bridge data template file can be loaded and parsed by a BridgeDataLoader."""
    bridge_data_loader = BridgeDataLoader()

    horde_model_reference_manager = ModelReferenceManager(
        download_and_convert_legacy_dbs=False,
        override_existing=False,
    )
    bridge_data = bridge_data_loader.load(
        file_path="bridgeData_template.yaml",
        file_format=ConfigFormat.yaml,
        horde_model_reference_manager=horde_model_reference_manager,
    )

    assert bridge_data is not None
    assert bridge_data.disable_terminal_ui is False
    assert bridge_data.api_key == ANON_API_KEY


def test_bridge_data_loader_yaml_local_if_present() -> None:
    """Test that the bridge data file can be loaded and parsed by a BridgeDataLoader (if present)."""
    bridge_data_loader = BridgeDataLoader()

    horde_model_reference_manager = ModelReferenceManager(
        download_and_convert_legacy_dbs=False,
        override_existing=False,
    )

    if not pathlib.Path("bridgeData.yaml").is_file():
        pytest.skip("bridgeData.yaml not found")

    bridge_data = bridge_data_loader.load(
        file_path="bridgeData.yaml",
        file_format=ConfigFormat.yaml,
        horde_model_reference_manager=horde_model_reference_manager,
    )

    assert bridge_data is not None
    assert bridge_data.api_key != ANON_API_KEY
    assert len(bridge_data.image_models_to_load) > 0


def test_bridge_data_load_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the bridge data can be loaded from environment variables."""
    monkeypatch.setenv("AIWORKER_REGEN_HORDE_URL", "https://localhost:8080")
    monkeypatch.setenv("AIWORKER_REGEN_MODELS_TO_LOAD", "['model1', 'model2']")
    monkeypatch.setenv("AIWORKER_MAX_ACTIVE_MODELS", "4")

    horde_model_reference_manager = ModelReferenceManager(
        download_and_convert_legacy_dbs=False,
        override_existing=False,
    )

    bridge_data = BridgeDataLoader.load_from_env_vars(
        horde_model_reference_manager=horde_model_reference_manager,
    )
    assert bridge_data is not None
    assert bridge_data._loaded_from_env_vars is True
    assert bridge_data.max_active_models == 4


def test_bridge_data_load_from_env_vars_auto_restart_idle_minutes_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid AIWORKER_AUTO_RESTART_IDLE_MINUTES is ignored during env-var config loading."""
    for key in list(os.environ):
        if key.startswith("AIWORKER_"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("AIWORKER_AUTO_RESTART_IDLE_MINUTES", "not_a_number")

    bridge_data = BridgeDataLoader.load_from_env_vars()

    assert bridge_data.auto_restart_on_idle_minutes == 60
    assert bridge_data.model_extra is None or "auto_restart_idle_minutes" not in bridge_data.model_extra


def test_bridge_data_auto_restart_on_idle_default() -> None:
    """Test that auto_restart_on_idle_minutes defaults to 60."""
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.auto_restart_on_idle_minutes == 60


def test_bridge_data_auto_restart_on_idle_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that AIWORKER_AUTO_RESTART_IDLE_MINUTES overrides auto_restart_on_idle_minutes."""
    monkeypatch.setenv("AIWORKER_AUTO_RESTART_IDLE_MINUTES", "120")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.auto_restart_on_idle_minutes == 120


def test_bridge_data_auto_restart_on_idle_env_var_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that AIWORKER_AUTO_RESTART_IDLE_MINUTES=0 disables auto-restart."""
    monkeypatch.setenv("AIWORKER_AUTO_RESTART_IDLE_MINUTES", "0")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.auto_restart_on_idle_minutes == 0


def test_bridge_data_auto_restart_on_idle_env_var_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that an invalid AIWORKER_AUTO_RESTART_IDLE_MINUTES value is ignored."""
    monkeypatch.setenv("AIWORKER_AUTO_RESTART_IDLE_MINUTES", "not_a_number")
    bridge_data = reGenBridgeData.model_validate({})
    # Falls back to the config/default value (60)
    assert bridge_data.auto_restart_on_idle_minutes == 60


def test_bridge_data_auto_restart_on_idle_env_var_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that a negative AIWORKER_AUTO_RESTART_IDLE_MINUTES value is ignored."""
    monkeypatch.setenv("AIWORKER_AUTO_RESTART_IDLE_MINUTES", "-5")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.auto_restart_on_idle_minutes == 60


def test_bridge_data_auto_restart_on_idle_env_var_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that an out-of-range AIWORKER_AUTO_RESTART_IDLE_MINUTES value is ignored."""
    monkeypatch.setenv("AIWORKER_AUTO_RESTART_IDLE_MINUTES", "1441")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.auto_restart_on_idle_minutes == 60


def test_bridge_data_to_dot_env_file() -> None:
    """Test that the bridge data can be written to a .env file."""
    bridge_data = reGenBridgeData.model_validate({})

    bridge_data.horde_url = "https://localhost:8080"
    bridge_data.image_models_to_load = ["model1", "model2"]

    BridgeDataLoader.write_bridge_data_as_dot_env_file(bridge_data, "bridgeData.env")
    assert pathlib.Path("bridgeData.env").is_file()


def test_load_env_vars_from_config_lora_cache_size(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that load_env_vars_from_config sets AIWORKER_LORA_CACHE_SIZE in MB (multiplied by 1024)."""
    monkeypatch.delenv("AIWORKER_LORA_CACHE_SIZE", raising=False)

    config_file = tmp_path / "bridgeData.yaml"
    config_file.write_text("max_lora_cache_size: 10\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    from horde_worker_regen.load_env_vars import load_env_vars_from_config

    load_env_vars_from_config()

    assert os.environ.get("AIWORKER_LORA_CACHE_SIZE") == str(10 * 1024), (
        "AIWORKER_LORA_CACHE_SIZE should be set in MB (GB * 1024)"
    )


def test_load_env_vars_from_config_lora_cache_size_not_overwritten(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that load_env_vars_from_config does not overwrite a pre-existing AIWORKER_LORA_CACHE_SIZE."""
    monkeypatch.setenv("AIWORKER_LORA_CACHE_SIZE", "99999")

    config_file = tmp_path / "bridgeData.yaml"
    config_file.write_text("max_lora_cache_size: 10\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    from horde_worker_regen.load_env_vars import load_env_vars_from_config

    load_env_vars_from_config()

    assert os.environ.get("AIWORKER_LORA_CACHE_SIZE") == "99999", (
        "A pre-existing AIWORKER_LORA_CACHE_SIZE should not be overwritten"
    )


def test_bridge_data_deprecated_lora_cache_size_remap() -> None:
    """Test that deprecated lora_cache_size remaps to max_lora_cache_size and is removed from extras."""
    bridge_data = reGenBridgeData.model_validate({"lora_cache_size": 10})
    assert bridge_data.max_lora_cache_size == 10
    assert bridge_data.model_extra is None or "lora_cache_size" not in bridge_data.model_extra


def test_bridge_data_deprecated_lora_cache_size_dropped_when_both_keys_present() -> None:
    """Test that deprecated lora_cache_size is dropped when max_lora_cache_size is also provided."""
    bridge_data = reGenBridgeData.model_validate({"lora_cache_size": 10, "max_lora_cache_size": 12})
    assert bridge_data.max_lora_cache_size == 12
    assert bridge_data.model_extra is None or "lora_cache_size" not in bridge_data.model_extra
