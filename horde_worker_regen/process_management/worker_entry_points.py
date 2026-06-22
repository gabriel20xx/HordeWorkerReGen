import contextlib
import os
import sys
from collections.abc import Generator

# ! IMPORTANT: Start of own code
try:
    from multiprocessing.connection import PipeConnection as Connection  # type: ignore
except (ImportError, AttributeError):
    # PipeConnection not available on all platforms, fall back to Connection
    from multiprocessing.connection import Connection  # type: ignore
# ! IMPORTANT: End of own code
from multiprocessing.synchronize import Lock, Semaphore

from loguru import logger

from horde_worker_regen.process_management._aliased_types import ProcessQueue

_HORDELIB_VERBOSITY = 5


@contextlib.contextmanager
def _suppress_cuda_init_noise() -> Generator[None, None, None]:
    """Redirect C-level fd 2 to /dev/null to silence NVIDIA CUDA driver init noise.

    The driver prints "ERROR: driverInitFileInfo ... result=11" directly to fd 2,
    bypassing Python's sys.stderr, so env-var mitigations (CUDA_CACHE_DISABLE) are
    not always sufficient.  This suppresses that noise only for the duration of the
    initial hordelib import; loguru's own sink is unaffected because it writes through
    sys.stderr, which is restored before any logging occurs.
    """
    saved_fd2 = os.dup(2)
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, 2)
        finally:
            os.close(devnull_fd)
        yield
    finally:
        os.dup2(saved_fd2, 2)
        os.close(saved_fd2)


def _initialize_horde_logging(process_id: int) -> None:
    """Initialize HordeLog and configure the standardized log format for a worker process."""
    from hordelib.utils.logger import HordeLog

    # setup_logging=False: skip hordelib's own file sinks — configure_logger_format()
    # owns all file sink setup and would remove them immediately anyway via logger.remove().
    HordeLog.initialise(
        setup_logging=False,
        process_id=process_id,
        verbosity_count=_HORDELIB_VERBOSITY,
    )

    from horde_worker_regen.logger_config import configure_logger_format

    configure_logger_format(process_id=process_id)


def start_inference_process(
    process_id: int,
    process_message_queue: ProcessQueue,
    pipe_connection: Connection,
    inference_semaphore: Semaphore,
    disk_lock: Lock,
    aux_model_lock: Lock,
    vae_decode_semaphore: Semaphore,
    process_launch_identifier: int,
    *,
    low_memory_mode: bool = False,
    high_memory_mode: bool = False,
    very_high_memory_mode: bool = False,
    amd_gpu: bool = False,
    directml: int | None = None,
    vram_heavy_models: bool = False,
) -> None:
    """Start an inference process.

    Args:
        process_id (int): The ID of the process. This is not the same as the PID.
        process_message_queue (ProcessQueue): The queue to send messages to the main process.
        pipe_connection (Connection): Receives `HordeControlMessage`s from the main process.
        inference_semaphore (Semaphore): The semaphore to use to limit concurrent inference.
        disk_lock (Lock): The lock to use for disk access.
        aux_model_lock (Lock): The lock to use for auxiliary model downloading.
        vae_decode_semaphore (Semaphore): The semaphore to use to limit concurrent VAE decoding.
        process_launch_identifier (int): The unique identifier for this launch.
        low_memory_mode (bool, optional): If true, the process will attempt to use less memory. Defaults to True.
        high_memory_mode (bool, optional): If true, the process will attempt to use more memory. Defaults to False.
        very_high_memory_mode (bool, optional): If true, the process will attempt to use even more memory.
            Defaults to False.
        amd_gpu (bool, optional): If true, the process will attempt to use AMD GPU-specific optimisations.
            Defaults to False.
        directml (int | None, optional): If not None, the process will attempt to use DirectML \
            with the specified device
        vram_heavy_models (bool, optional): If true, the process will attempt to reserve more VRAM. Defaults to False.
    """
    logger.remove()

    # Prevent ONNX Runtime from attempting to set CPU thread affinity, which fails in containers
    # and restricted environments with error: "pthread_setaffinity_np failed ... Invalid argument"
    # Default to 1 to avoid oversubscribing CPU threads when multiple inference processes run concurrently.
    os.environ.setdefault("OMP_NUM_THREADS", "1")

    try:
        with _suppress_cuda_init_noise():
            import hordelib

        _initialize_horde_logging(process_id)

        logger.debug(
            f"Initialising hordelib with process_id={process_id}, "
            f"process_launch_identifier={process_launch_identifier}, "
            f"high_memory_mode={high_memory_mode} "
            f"and amd_gpu={amd_gpu}, low_memory_mode={low_memory_mode}, "
            f"very_high_memory_mode={very_high_memory_mode}",
        )

        extra_comfyui_args = ["--disable-smart-memory"]

        if amd_gpu:
            extra_comfyui_args.append("--use-pytorch-cross-attention")

        if directml is not None:
            extra_comfyui_args.append(f"--directml={directml}")

        models_not_to_force_load = ["flux"]

        if very_high_memory_mode:
            extra_comfyui_args.append("--gpu-only")
        elif high_memory_mode:
            models_not_to_force_load.extend(
                [
                    "cascade",
                ],
            )
        elif low_memory_mode:
            extra_comfyui_args.append("--novram")
            models_not_to_force_load.extend(
                [
                    "sdxl",
                    "cascade",
                ],
            )
        elif not vram_heavy_models:
            logger.info("Reserving 1.4GB VRAM.")
            extra_comfyui_args.extend(["--reserve-vram", "1.4"])

        if high_memory_mode and vram_heavy_models:
            logger.info("High memory mode and vram heavy models are both enabled. Reserving 6GB VRAM.")
            extra_comfyui_args.extend(["--reserve-vram", "6"])

        if "--reserve-vram" not in extra_comfyui_args:
            logger.warning("No VRAM reservation specified.")

        with logger.catch(reraise=True):
            logger.debug(f"Using extra comfyui args: {extra_comfyui_args}")
            hordelib.initialise(
                setup_logging=False,  # we own all sinks; False prevents hordelib from
                                      # calling logger.remove() and recreating root log files
                process_id=process_id,
                logging_verbosity=0,
                force_normal_vram_mode=False,
                models_not_to_force_load=models_not_to_force_load,
                extra_comfyui_args=extra_comfyui_args,
            )

    except Exception as e:
        logger.critical(f"Failed to initialise hordelib: {type(e).__name__} {e}")
        sys.exit(1)

    from horde_worker_regen.process_management.inference_process import HordeInferenceProcess

    worker_process = HordeInferenceProcess(
        process_id=process_id,
        process_message_queue=process_message_queue,
        pipe_connection=pipe_connection,
        inference_semaphore=inference_semaphore,
        disk_lock=disk_lock,
        aux_model_lock=aux_model_lock,
        vae_decode_semaphore=vae_decode_semaphore,
        process_launch_identifier=process_launch_identifier,
    )

    worker_process.main_loop()


def start_safety_process(
    process_id: int,
    process_message_queue: ProcessQueue,
    pipe_connection: Connection,
    disk_lock: Lock,
    process_launch_identifier: int,
    cpu_only: bool = True,
    *,
    high_memory_mode: bool = False,
    amd_gpu: bool = False,
    directml: int | None = None,
) -> None:
    """Start a safety process.

    Args:
        process_id (int): The ID of the process. This is not the same as the PID of the system.
        process_message_queue (ProcessQueue): The queue to send messages to the main process.
        pipe_connection (Connection): Receives `HordeControlMessage`s from the main process.
        disk_lock (Lock): The lock to use for disk access.
        process_launch_identifier (int): The unique identifier for this launch.
        cpu_only (bool, optional): If true, the process will not use the GPU. Defaults to True.
        high_memory_mode (bool, optional): If true, the process will attempt to use more memory. Defaults to False.
        amd_gpu (bool, optional): If true, the process will attempt to use AMD GPU-specific optimizations.
            Defaults to False.
        directml (int | None, optional): If not None, the process will attempt to use DirectML \
            with the specified device
    """
    logger.remove()

    try:
        _initialize_horde_logging(process_id)

        logger.debug(f"Initialising hordelib with process_id={process_id} and high_memory_mode={high_memory_mode}")

        extra_comfyui_args = ["--disable-smart-memory"]

        if amd_gpu:
            extra_comfyui_args.append("--use-pytorch-cross-attention")

        if directml is not None:
            extra_comfyui_args.append(f"--directml={directml}")

    except Exception as e:
        logger.critical(f"Failed to initialise: {type(e).__name__} {e}")
        sys.exit(1)

    from horde_worker_regen.process_management.safety_process import HordeSafetyProcess

    logger.debug(
        f"Initialising hordelib with process_id={process_id}, "
        f"process_launch_identifier={process_launch_identifier}, "
        f"cpu_only={cpu_only}, high_memory_mode={high_memory_mode} "
        f"and amd_gpu={amd_gpu}",
    )
    worker_process = HordeSafetyProcess(
        process_id=process_id,
        process_message_queue=process_message_queue,
        pipe_connection=pipe_connection,
        disk_lock=disk_lock,
        process_launch_identifier=process_launch_identifier,
        cpu_only=cpu_only,
    )

    worker_process.main_loop()
