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


def test_bridge_data_data_retention_days_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that data_retention_days defaults to 7."""
    monkeypatch.delenv("AIWORKER_DATA_RETENTION_DAYS", raising=False)
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.data_retention_days == 7


def test_bridge_data_data_retention_days_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that AIWORKER_DATA_RETENTION_DAYS overrides data_retention_days."""
    monkeypatch.setenv("AIWORKER_DATA_RETENTION_DAYS", "30")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.data_retention_days == 30


def test_bridge_data_data_retention_days_env_var_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that a non-integer AIWORKER_DATA_RETENTION_DAYS value is ignored."""
    monkeypatch.setenv("AIWORKER_DATA_RETENTION_DAYS", "not_a_number")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.data_retention_days == 7


def test_bridge_data_data_retention_days_env_var_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that AIWORKER_DATA_RETENTION_DAYS=0 (out of range) is ignored."""
    monkeypatch.setenv("AIWORKER_DATA_RETENTION_DAYS", "0")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.data_retention_days == 7


def test_bridge_data_data_retention_days_env_var_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that a negative AIWORKER_DATA_RETENTION_DAYS value is ignored."""
    monkeypatch.setenv("AIWORKER_DATA_RETENTION_DAYS", "-1")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.data_retention_days == 7


def test_bridge_data_data_retention_days_env_var_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that an out-of-range AIWORKER_DATA_RETENTION_DAYS value (> 3650) is ignored."""
    monkeypatch.setenv("AIWORKER_DATA_RETENTION_DAYS", "3651")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.data_retention_days == 7


def test_bridge_data_data_retention_days_env_var_boundary_min(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that AIWORKER_DATA_RETENTION_DAYS=1 (minimum valid) is accepted."""
    monkeypatch.setenv("AIWORKER_DATA_RETENTION_DAYS", "1")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.data_retention_days == 1


def test_bridge_data_data_retention_days_env_var_boundary_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that AIWORKER_DATA_RETENTION_DAYS=3650 (maximum valid) is accepted."""
    monkeypatch.setenv("AIWORKER_DATA_RETENTION_DAYS", "3650")
    bridge_data = reGenBridgeData.model_validate({})
    assert bridge_data.data_retention_days == 3650


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


def test_resolve_meta_instructions_defaults_to_all_when_no_models_configured() -> None:
    """When no models_to_load are configured, _resolve_meta_instructions defaults to all known models."""
    from unittest.mock import MagicMock, patch

    from horde_worker_regen.bridge_data.load_config import BridgeDataLoader

    bridge_data = reGenBridgeData.model_validate({})
    # Confirm no models were configured
    assert bridge_data.image_models_to_load == []
    assert bridge_data.meta_load_instructions is None

    mock_ref_manager = MagicMock()
    known_models = {"Model A", "Model B", "Model C"}

    with patch(
        "horde_worker_regen.bridge_data.load_config.ImageModelLoadResolver"
    ) as MockResolver:
        instance = MockResolver.return_value
        instance.resolve_all_model_names.return_value = known_models
        instance.remove_large_models.side_effect = lambda models: models
        instance.resolve_meta_instructions.return_value = None

        result = BridgeDataLoader._resolve_meta_instructions(bridge_data, mock_ref_manager)

    assert set(result) == known_models, "Should default to all known models"


def test_resolve_meta_instructions_respects_skip_in_default() -> None:
    """When defaulting to all models, image_models_to_skip is still applied."""
    from unittest.mock import MagicMock, patch

    from horde_worker_regen.bridge_data.load_config import BridgeDataLoader

    bridge_data = reGenBridgeData.model_validate({"models_to_skip": ["Model B"]})
    assert bridge_data.image_models_to_load == []

    mock_ref_manager = MagicMock()
    known_models = {"Model A", "Model B", "Model C"}

    with patch(
        "horde_worker_regen.bridge_data.load_config.ImageModelLoadResolver"
    ) as MockResolver:
        instance = MockResolver.return_value
        instance.resolve_all_model_names.return_value = known_models
        instance.remove_large_models.side_effect = lambda models: models
        instance.resolve_meta_instructions.return_value = None

        result = BridgeDataLoader._resolve_meta_instructions(bridge_data, mock_ref_manager)

    assert "Model B" not in result, "Skipped model should not be in default set"
    assert {"Model A", "Model C"} == set(result)


def test_resolve_meta_instructions_does_not_override_explicit_empty_config() -> None:
    """When models_to_load is explicitly set but resolves to nothing, do not default to all models."""
    from unittest.mock import MagicMock, patch

    from horde_worker_regen.bridge_data.load_config import BridgeDataLoader

    bridge_data = reGenBridgeData.model_validate({"models_to_load": ["NonExistentModel"]})
    assert bridge_data.image_models_to_load == ["NonExistentModel"]

    mock_ref_manager = MagicMock()
    known_models = {"Model A", "Model B"}

    with patch(
        "horde_worker_regen.bridge_data.load_config.ImageModelLoadResolver"
    ) as MockResolver:
        instance = MockResolver.return_value
        instance.resolve_all_model_names.return_value = known_models
        instance.remove_large_models.side_effect = lambda models: models
        instance.resolve_meta_instructions.return_value = None

        result = BridgeDataLoader._resolve_meta_instructions(bridge_data, mock_ref_manager)

    # The user asked for a specific (invalid) model — we should NOT fall back to all models
    assert result == [], "Explicit (but invalid) model list should not be replaced with default"


def test_resolve_meta_instructions_with_retry_recovers_from_transient_error() -> None:
    """A transient error (e.g., a Cloudflare 522) should be retried and succeed without raising."""
    from unittest.mock import MagicMock, patch

    with patch("horde_worker_regen.bridge_data.load_config.time.sleep") as mock_sleep:
        mock_resolver = MagicMock()
        mock_resolver.resolve_meta_instructions.side_effect = [
            Exception("Error getting stats for models: "),
            {"Model A"},
        ]

        result = BridgeDataLoader._resolve_meta_instructions_with_retry(
            mock_resolver,
            ["top 1"],
            MagicMock(),
            retry_delay_seconds=0,
        )

    assert result == {"Model A"}
    assert mock_resolver.resolve_meta_instructions.call_count == 2
    mock_sleep.assert_called_once()


def test_resolve_meta_instructions_with_retry_gives_up_after_max_attempts() -> None:
    """After repeated failures, the retry helper should give up and return an empty set instead of raising."""
    from unittest.mock import MagicMock, patch

    with patch("horde_worker_regen.bridge_data.load_config.time.sleep"):
        mock_resolver = MagicMock()
        mock_resolver.resolve_meta_instructions.side_effect = Exception("Error getting stats for models: ")

        result = BridgeDataLoader._resolve_meta_instructions_with_retry(
            mock_resolver,
            ["top 1"],
            MagicMock(),
            max_attempts=3,
            retry_delay_seconds=0,
        )

    assert result == set()
    assert mock_resolver.resolve_meta_instructions.call_count == 3


def test_bridge_data_deprecated_lora_cache_size_remap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that deprecated lora_cache_size remaps to max_lora_cache_size, is removed from extras, and emits a warning."""
    warning_messages: list[str] = []
    deprecated_warning = (
        "The `lora_cache_size` parameter is deprecated. Please rename it to `max_lora_cache_size` "
        "in your bridge data file."
    )

    def _capture_warning(message: str, *args: object, **kwargs: object) -> None:
        warning_messages.append(message)

    import horde_worker_regen.bridge_data.data_model as _data_model_module

    monkeypatch.setattr(_data_model_module.logger, "warning", _capture_warning)

    bridge_data = reGenBridgeData.model_validate({"lora_cache_size": 10})
    assert bridge_data.max_lora_cache_size == 10
    assert bridge_data.model_extra is None or "lora_cache_size" not in bridge_data.model_extra
    assert deprecated_warning in warning_messages


def test_bridge_data_deprecated_lora_cache_size_dropped_when_both_keys_present() -> None:
    """Test that deprecated lora_cache_size is dropped when max_lora_cache_size is also provided."""
    bridge_data = reGenBridgeData.model_validate({"lora_cache_size": 10, "max_lora_cache_size": 12})
    assert bridge_data.max_lora_cache_size == 12
    assert bridge_data.model_extra is None or "lora_cache_size" not in bridge_data.model_extra


def test_bridge_data_deprecated_lora_cache_size_does_not_warn_when_new_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that deprecation warning is skipped when max_lora_cache_size is already set."""
    warning_messages: list[str] = []
    deprecated_warning = (
        "The `lora_cache_size` parameter is deprecated. Please rename it to `max_lora_cache_size` "
        "in your bridge data file."
    )

    def _capture_warning(message: str, *args: object, **kwargs: object) -> None:
        warning_messages.append(message)

    import horde_worker_regen.bridge_data.data_model as _data_model_module

    monkeypatch.setattr(_data_model_module.logger, "warning", _capture_warning)

    bridge_data = reGenBridgeData.model_validate({"lora_cache_size": 10, "max_lora_cache_size": 12})

    assert bridge_data.max_lora_cache_size == 12
    assert deprecated_warning not in warning_messages
