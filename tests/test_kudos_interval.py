"""Test kudos info display interval."""

from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager


def test_api_get_user_info_interval() -> None:
    """Test that the API get user info interval is set to a reasonable value.
    
    This interval controls how often kudos information is displayed in the console.
    The value should be 60 seconds or higher to avoid spamming the console.
    """
    assert HordeWorkerProcessManager._api_get_user_info_interval >= 60, (
        f"Expected _api_get_user_info_interval to be at least 60 seconds, "
        f"but got {HordeWorkerProcessManager._api_get_user_info_interval}"
    )
