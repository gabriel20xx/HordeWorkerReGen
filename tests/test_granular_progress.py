"""Test granular progress calculation for job progress bar."""

from unittest.mock import MagicMock

import pytest

from horde_worker_regen.process_management.messages import HordeProcessState


def test_calculate_granular_progress() -> None:
    """Test the granular progress calculation method."""
    # Import here to avoid circular dependencies
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    # Create a mock ProcessManager instance to test the method
    # We only need to test the _calculate_granular_progress method
    mock_manager = MagicMock(spec=HordeWorkerProcessManager)

    # Bind the actual method to the mock
    mock_manager._calculate_granular_progress = HordeWorkerProcessManager._calculate_granular_progress.__get__(
        mock_manager, HordeWorkerProcessManager
    )

    # Define test cases: (state, inference_progress, expected_progress)
    test_cases = [
        # Job received (0%)
        (HordeProcessState.JOB_RECEIVED, None, 0),
        (HordeProcessState.WAITING_FOR_JOB, None, 0),
        # Model loading stages (0-20%)
        (HordeProcessState.DOWNLOADING_MODEL, None, 10),
        (HordeProcessState.MODEL_LOADING, None, 10),
        (HordeProcessState.MODEL_PRELOADING, None, 10),
        (HordeProcessState.MODEL_LOADED, None, 20),
        # Inference stages (20-70%)
        (HordeProcessState.INFERENCE_STARTING, None, 20),
        (HordeProcessState.INFERENCE_PROCESSING, 0, 20),  # 0% inference -> 20% overall
        (HordeProcessState.INFERENCE_PROCESSING, 50, 45),  # 50% inference -> 45% overall
        (HordeProcessState.INFERENCE_PROCESSING, 100, 70),  # 100% inference -> 70% overall
        # Post-processing stage (70-80%)
        (HordeProcessState.INFERENCE_POST_PROCESSING, None, 75),
        (HordeProcessState.INFERENCE_POST_PROCESSING, 50, 75),  # 50% post-proc -> 75% overall
        (HordeProcessState.INFERENCE_COMPLETE, None, 80),
        # Safety check stage (80-90%)
        (HordeProcessState.SAFETY_STARTING, None, 85),
        (HordeProcessState.SAFETY_EVALUATING, None, 85),
        (HordeProcessState.SAFETY_COMPLETE, None, 90),
        # Submission stage (90-100%)
        (HordeProcessState.IMAGE_SAVING, None, 92),
        (HordeProcessState.IMAGE_SAVED, None, 95),
        (HordeProcessState.IMAGE_SUBMITTING, None, 97),
        (HordeProcessState.IMAGE_SUBMITTED, None, 100),
        # Failed states
        (HordeProcessState.INFERENCE_FAILED, 30, 35),  # Failed at 30% inference
        (HordeProcessState.SAFETY_FAILED, None, 85),
    ]

    # Test each case
    for state, inference_progress, expected_progress in test_cases:
        result = mock_manager._calculate_granular_progress(state, inference_progress)
        assert (
            result == expected_progress
        ), f"Failed for state {state.name}, inference={inference_progress}: expected {expected_progress}, got {result}"


def test_inference_progress_scaling() -> None:
    """Test that inference progress is correctly scaled to 20-70% range."""
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    mock_manager = MagicMock(spec=HordeWorkerProcessManager)
    mock_manager._calculate_granular_progress = HordeWorkerProcessManager._calculate_granular_progress.__get__(
        mock_manager, HordeWorkerProcessManager
    )

    # Test boundary conditions for inference scaling
    # Formula: 20 + (inference_progress * 0.5)
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_PROCESSING, 0) == 20
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_PROCESSING, 10) == 25
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_PROCESSING, 20) == 30
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_PROCESSING, 50) == 45
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_PROCESSING, 80) == 60
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_PROCESSING, 100) == 70


def test_post_processing_progress_scaling() -> None:
    """Test that post-processing progress is correctly scaled to 70-80% range."""
    from horde_worker_regen.process_management.process_manager import HordeWorkerProcessManager

    mock_manager = MagicMock(spec=HordeWorkerProcessManager)
    mock_manager._calculate_granular_progress = HordeWorkerProcessManager._calculate_granular_progress.__get__(
        mock_manager, HordeWorkerProcessManager
    )

    # Test post-processing scaling
    # Formula: 70 + (progress * 0.1) for progress < 100
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_POST_PROCESSING, 0) == 70
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_POST_PROCESSING, 50) == 75
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_POST_PROCESSING, 99) == 79
    # At 100%, it should be at INFERENCE_COMPLETE state, but if still in POST_PROCESSING
    assert mock_manager._calculate_granular_progress(HordeProcessState.INFERENCE_POST_PROCESSING, None) == 75


if __name__ == "__main__":
    # Run tests manually for debugging
    import sys

    print("Running granular progress tests...")
    try:
        test_calculate_granular_progress()
        print("✓ test_calculate_granular_progress passed")
        test_inference_progress_scaling()
        print("✓ test_inference_progress_scaling passed")
        test_post_processing_progress_scaling()
        print("✓ test_post_processing_progress_scaling passed")
        print("\n✓ All granular progress tests passed!")
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
