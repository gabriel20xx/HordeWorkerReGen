"""Tests for crash resilience improvements."""

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from horde_worker_regen.process_management.messages import HordeProcessState


class TestIsProcessAlive:
    """Tests for the is_process_alive() method fix."""

    def _make_process_info(self, state: HordeProcessState, mp_is_alive: bool) -> MagicMock:
        """Create a mock HordeProcessInfo with the given state and OS-level alive status."""
        from horde_worker_regen.process_management.process_manager import HordeProcessInfo

        mock_info = MagicMock()
        mock_info.mp_process = MagicMock()
        mock_info.mp_process.is_alive.return_value = mp_is_alive
        mock_info.last_process_state = state

        # Bind the actual method
        mock_info.is_process_alive = HordeProcessInfo.is_process_alive.__get__(mock_info, HordeProcessInfo)
        return mock_info

    def test_alive_process_in_normal_state_returns_true(self) -> None:
        """A process that is alive at the OS level and in a normal state should return True."""
        for state in [
            HordeProcessState.WAITING_FOR_JOB,
            HordeProcessState.INFERENCE_PROCESSING,
            HordeProcessState.MODEL_LOADING,
            HordeProcessState.PROCESS_STARTING,
        ]:
            info = self._make_process_info(state, mp_is_alive=True)
            assert info.is_process_alive() is True, f"Expected True for state {state.name}, got False"

    def test_dead_process_always_returns_false(self) -> None:
        """A process that is dead at the OS level should always return False."""
        for state in [
            HordeProcessState.WAITING_FOR_JOB,
            HordeProcessState.INFERENCE_PROCESSING,
            HordeProcessState.PROCESS_ENDING,
            HordeProcessState.PROCESS_ENDED,
        ]:
            info = self._make_process_info(state, mp_is_alive=False)
            assert info.is_process_alive() is False, f"Expected False for dead process in state {state.name}"

    def test_process_ending_state_returns_false(self) -> None:
        """A process in PROCESS_ENDING state should be considered not alive even if OS reports it alive."""
        info = self._make_process_info(HordeProcessState.PROCESS_ENDING, mp_is_alive=True)
        assert info.is_process_alive() is False

    def test_process_ended_state_returns_false(self) -> None:
        """A process in PROCESS_ENDED state should be considered not alive even if OS reports it alive."""
        info = self._make_process_info(HordeProcessState.PROCESS_ENDED, mp_is_alive=True)
        assert info.is_process_alive() is False


class TestReplaceHungProcessesAnyReplaced:
    """Tests for the any_replaced local variable fix in replace_hung_processes."""

    def test_any_replaced_variable_is_local_not_instance(self) -> None:
        """Verify the fix: replace_hung_processes uses any_replaced local var, not self._any_replaced."""
        import ast
        import inspect

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        source = textwrap.dedent(inspect.getsource(HordeWorkerProcessManager.replace_hung_processes))
        tree = ast.parse(source)

        # Check that self._any_replaced is NOT assigned anywhere in the method
        # (before the fix, `self._any_replaced = True` was used instead of `any_replaced = True`)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        if target.attr == "_any_replaced":
                            pytest.fail(
                                "replace_hung_processes should not assign to self._any_replaced; "
                                "use the local variable any_replaced instead"
                            )


class TestBridgeDataLoopExceptionHandling:
    """Tests that the bridge data loop recovers from unexpected exceptions."""

    def test_bridge_data_loop_has_general_exception_handler(self) -> None:
        """The _bridge_data_loop method should handle general exceptions without dying."""
        import ast
        import inspect

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        source = textwrap.dedent(inspect.getsource(HordeWorkerProcessManager._bridge_data_loop))
        tree = ast.parse(source)

        # Look for try/except blocks with a general Exception handler
        found_general_except = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    found_general_except = True
                    break
                if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    found_general_except = True
                    break

        assert found_general_except, "_bridge_data_loop should have a general Exception handler"


class TestProcessControlLoopExceptionHandling:
    """Tests that the process control loop handles unexpected exceptions."""

    def test_process_control_loop_has_general_exception_handler(self) -> None:
        """The _process_control_loop method should handle general exceptions without dying."""
        import ast
        import inspect

        from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

        source = textwrap.dedent(inspect.getsource(HordeWorkerProcessManager._process_control_loop))
        tree = ast.parse(source)

        # Look for try/except blocks with a general Exception handler
        found_general_except = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    found_general_except = True
                    break
                if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    found_general_except = True
                    break

        assert found_general_except, "_process_control_loop should have a general Exception handler"


class TestWorkerCycleExceptionHandling:
    """Tests that the subprocess main loop handles worker_cycle() exceptions."""

    def test_main_loop_has_worker_cycle_exception_handling(self) -> None:
        """The main_loop should catch exceptions from worker_cycle() and end gracefully."""
        import ast
        import inspect

        from horde_worker_regen.process_management.horde_process import HordeProcess

        source = textwrap.dedent(inspect.getsource(HordeProcess.main_loop))
        tree = ast.parse(source)

        # Look for try/except blocks that wrap worker_cycle
        found_worker_cycle_try = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Attribute) and child.func.attr == "worker_cycle":
                            found_worker_cycle_try = True
                            break

        assert found_worker_cycle_try, "main_loop should wrap worker_cycle() in a try/except block"

