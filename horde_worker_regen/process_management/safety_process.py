"""Contains the classes to form a safety process, which is responsible for evaluating the safety of images."""

import base64
import enum
import json
import os
import time
import warnings
from datetime import datetime
from enum import auto
from io import BytesIO
from typing import TYPE_CHECKING

# ! IMPORTANT: Start of own code
try:
    from multiprocessing.connection import PipeConnection as Connection  # type: ignore
except (ImportError, AttributeError):
    # PipeConnection not available on all platforms, fall back to Connection
    from multiprocessing.connection import Connection  # type: ignore
# ! IMPORTANT: End of own code
from multiprocessing.synchronize import Lock

from loguru import logger
from PIL import Image
from typing_extensions import override

from horde_worker_regen import ASSETS_FOLDER_PATH
from horde_worker_regen.process_management._aliased_types import ProcessQueue
from horde_worker_regen.process_management.horde_process import HordeProcess
from horde_worker_regen.process_management.messages import (
    HordeControlFlag,
    HordeControlMessage,
    HordeProcessState,
    # ! IMPORTANT: End own code
    HordeSafetyControlMessage,
    HordeSafetyEvaluation,
    HordeSafetyResultMessage,
    # ! IMPORTANT: Start own code
    HordeSavedImageInfo,
)

if TYPE_CHECKING:
    from horde_safety.deep_danbooru_model import DeepDanbooruModel
    from horde_safety.interrogate import Interrogator
    from horde_safety.nsfw_checker_class import NSFWChecker, NSFWResult
else:

    class Interrogator:
        """Dummy class to prevent type errors."""

    class NSFWChecker:
        """Dummy class to prevent type errors."""

    class NSFWResult:
        """Dummy class to prevent type errors."""

    class DeepDanbooruModel:
        """Dummy class to prevent type errors."""


class CensorReason(enum.Enum):
    """The reason for censoring an image."""

    CSAM = auto()
    CENSORLIST = auto()
    SFW_REQUEST = auto()
    SFW_WORKER = auto()


class HordeSafetyProcess(HordeProcess):
    """The safety process, which is responsible for evaluating the safety of images."""

    _interrogator: Interrogator
    _deep_danbooru_model: DeepDanbooruModel

    _nsfw_checker: NSFWChecker

    censor_csam_image_base64: str
    censor_censorlist_image_base64: str
    censor_sfw_request_image_base64: str
    censor_sfw_worker_image_base64: str

    def __init__(
        self,
        process_id: int,
        process_message_queue: ProcessQueue,
        pipe_connection: Connection,
        disk_lock: Lock,
        process_launch_identifier: int,
        cpu_only: bool = True,
    ) -> None:
        """Initialise the safety process.

        Args:
            process_id (int): The ID of the process.
            process_message_queue (ProcessQueue): The process message queue.
            pipe_connection (Connection): The connection to the parent process.
            disk_lock (Lock): The lock to use when accessing the disk.
            process_launch_identifier (int): The unique identifier for this launch.
            cpu_only (bool, optional): Whether to only use the CPU. Defaults to True.
        """
        super().__init__(
            process_id=process_id,
            process_message_queue=process_message_queue,
            pipe_connection=pipe_connection,
            disk_lock=disk_lock,
            process_launch_identifier=process_launch_identifier,
        )

        try:
            # Suppress known warnings from dependencies
            warnings.filterwarnings("ignore", category=FutureWarning, message=".*pynvml.*")
            warnings.filterwarnings("ignore", category=UserWarning, message=".*QuickGELU.*")

            from horde_safety.deep_danbooru_model import get_deep_danbooru_model
            from horde_safety.interrogate import get_interrogator_no_blip
        except Exception as e:
            logger.error(f"Failed to import horde_safety: {type(e).__name__} {e}")
            raise

        try:
            logger.debug(f"Initialising horde_safety with cpu_only={cpu_only}")
            self._deep_danbooru_model = get_deep_danbooru_model(device="cpu" if cpu_only else "cuda")
            self._interrogator = get_interrogator_no_blip(device="cpu" if cpu_only else "cuda")
        except Exception as e:
            logger.error(f"Failed to initialise horde_safety: {type(e).__name__} {e}")
            raise

        try:
            from horde_safety.nsfw_checker_class import NSFWChecker

            self._nsfw_checker = NSFWChecker(
                self._interrogator,
                self._deep_danbooru_model,  # Optional, significantly improves results for anime images
            )
        except Exception as e:
            logger.error(f"Failed to initialise NSFWChecker: {type(e).__name__} {e}")
            raise

        try:
            self.load_censor_files()
        except Exception as e:
            logger.error(f"Failed to load censor files: {type(e).__name__} {e}")
            raise

        info_message = "Horde safety process started."

        logger.info(info_message)
        self.send_process_state_change_message(
            process_state=HordeProcessState.WAITING_FOR_JOB,
            info=info_message,
        )

        logger.info(
            "The first job will always take several seconds longer when on CPU. Subsequent jobs will be faster.",
        )

    def _set_censor_image(self, reason: CensorReason, image_base64: str) -> None:
        if reason == CensorReason.CSAM:
            self.censor_csam_image_base64 = image_base64
        elif reason == CensorReason.CENSORLIST:
            self.censor_censorlist_image_base64 = image_base64
        elif reason == CensorReason.SFW_REQUEST:
            self.censor_sfw_request_image_base64 = image_base64
        elif reason == CensorReason.SFW_WORKER:
            self.censor_sfw_worker_image_base64 = image_base64
        else:
            raise ValueError(f"Unknown censor reason: {reason}")

    def load_censor_files(self) -> None:
        """Load the censor images from disk."""
        file_lookup = {
            CensorReason.CSAM: "nsfw_censor_csam.png",
            CensorReason.CENSORLIST: "nsfw_censor_censorlist.png",
            CensorReason.SFW_REQUEST: "nsfw_censor_sfw_request.png",
            CensorReason.SFW_WORKER: "nsfw_censor_sfw_worker.png",
        }

        for reason in CensorReason:
            with open(ASSETS_FOLDER_PATH / file_lookup[reason], "rb") as f:
                self._set_censor_image(reason, base64.b64encode(f.read()).decode("utf-8"))

    @override
    def _receive_and_handle_control_message(self, message: HordeControlMessage) -> None:
        if not isinstance(message, HordeSafetyControlMessage):
            raise TypeError(f"Expected {HordeSafetyControlMessage}, got {type(message)}")

        if message.control_flag != HordeControlFlag.EVALUATE_SAFETY:
            raise ValueError(f"Expected {HordeControlFlag.EVALUATE_SAFETY}, got {message.control_flag}")

        self.send_memory_report_message(include_vram=False)

        time_start = time.time()

        logger.info(
            f"Horde safety process received job {message.job_id}. Number of images: {len(message.images_base64)}",
        )

        safety_evaluations: list[HordeSafetyEvaluation] = []

        # ! IMPORTANT: Start own code
        saved_images: list[HordeSavedImageInfo] = []

        # Set base output directory
        base_output_directory = "/output"

        # Pre-calculate the date-based output directory parts
        now = datetime.now()
        year = now.strftime("%Y")
        year_month = now.strftime("%Y-%m")
        year_month_day = now.strftime("%Y-%m-%d")

        # Construct the full output directory path: /output/YYYY/YYYY-MM/YYYY-MM-DD/
        output_directory = os.path.join(base_output_directory, year, year_month, year_month_day)

        # Build directories
        year_dir = os.path.join(base_output_directory, year)
        year_month_dir = os.path.join(year_dir, year_month)
        year_month_day_dir = os.path.join(year_month_dir, year_month_day)

        # Create all directories
        os.makedirs(year_month_day_dir, exist_ok=True)

        # Apply permissions only to the three relevant ones
        for d in [year_dir, year_month_dir, year_month_day_dir]:
            os.chmod(d, 0o777)

        for image_base64 in message.images_base64:
            # Decode the image from base64
            image_bytes = BytesIO(base64.b64decode(image_base64))

            # Generate a timestamp with milliseconds only once per image
            timestamp = now.strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3]
            output_path = os.path.join(output_directory, f"{timestamp}.png")

            # Open the image using PIL
            image_as_pil_0 = Image.open(image_bytes)

            original_prompt = message.prompt

            metadata: PngImagePlugin.PngInfo | None = None

            try:
                from PIL import PngImagePlugin

                # Create a PngInfo object to hold metadata
                metadata = PngImagePlugin.PngInfo()

                if "###" in original_prompt:
                    # Split the text at "###"
                    parts = original_prompt.split("###")

                    # Get the string before and after "###"
                    positive_prompt = parts[0]
                    negative_prompt = parts[1]
                else:
                    positive_prompt = original_prompt
                    negative_prompt = ""

                generation_metadata = message.generation_metadata or {}
                sanitized_negative_prompt = generation_metadata.get("sanitized_negative_prompt")

                # Add custom metadata
                metadata.add_text("Positive prompt", positive_prompt)
                metadata.add_text(
                    "Negative prompt",
                    sanitized_negative_prompt if sanitized_negative_prompt is not None else negative_prompt,
                )

                metadata.add_text(
                    "Created at",
                    datetime.now().isoformat(timespec="seconds"),
                )

                def _add_metadata_text(key: str, value: object) -> None:
                    if value is None:
                        metadata.add_text(key, "")
                        return
                    if isinstance(value, str):
                        metadata.add_text(key, value)
                    else:
                        metadata.add_text(key, json.dumps(value, ensure_ascii=False, default=str))

                # Explicitly add key fields when available
                _add_metadata_text("Model name", generation_metadata.get("model"))
                _add_metadata_text("Model hash", generation_metadata.get("model_hash"))
                _add_metadata_text("Sampler", generation_metadata.get("sampler_name"))
                _add_metadata_text("Seed", generation_metadata.get("seed"))
                _add_metadata_text("Seed resize from", generation_metadata.get("seed_resize_from"))
                _add_metadata_text("Seed resize from width", generation_metadata.get("seed_resize_from_width"))
                _add_metadata_text("Seed resize from height", generation_metadata.get("seed_resize_from_height"))
                _add_metadata_text("CFG scale", generation_metadata.get("cfg_scale"))
                _add_metadata_text("Denoising strength", generation_metadata.get("denoising_strength"))
                _add_metadata_text(
                    "Steps",
                    generation_metadata.get("steps")
                    if generation_metadata.get("steps") is not None
                    else generation_metadata.get("ddim_steps"),
                )
                _add_metadata_text("Version", generation_metadata.get("version"))
                post_processing = generation_metadata.get("post_processing")
                if isinstance(post_processing, list):
                    _add_metadata_text("Post processing", ", ".join(str(v) for v in post_processing))
                else:
                    _add_metadata_text("Post processing", post_processing)

                lora_descriptions = generation_metadata.get("lora_descriptions") or []
                if isinstance(lora_descriptions, list) and lora_descriptions:
                    lora_text = ", ".join(lora_descriptions)
                else:
                    lora_text = ""
                metadata.add_text("Loras", lora_text)

                lora_hashes = generation_metadata.get("lora_hashes")
                if lora_hashes is None:
                    try:
                        lora_hash_list: list[str] = []
                        loras = generation_metadata.get("loras") or []
                        for lora in loras:
                            if isinstance(lora, dict):
                                lora_hash = lora.get("hash") or lora.get("lora_hash") or lora.get("sha")
                            else:
                                lora_hash = (
                                    getattr(lora, "hash", None)
                                    or getattr(lora, "lora_hash", None)
                                    or getattr(lora, "sha", None)
                                )
                            if lora_hash is not None:
                                lora_hash_list.append(str(lora_hash))
                        lora_hashes = lora_hash_list
                    # ! IMPORTANT: Start of own code
                    except (AttributeError, KeyError, TypeError) as e:
                        # Handle cases where lora object doesn't have expected attributes
                        logger.debug(f"Failed to extract lora hash: {e}")
                        lora_hashes = None
                    # ! IMPORTANT: End of own code

                if isinstance(lora_hashes, list):
                    _add_metadata_text("LoRA hashes", ", ".join(str(v) for v in lora_hashes))
                else:
                    _add_metadata_text("LoRA hashes", lora_hashes)

                if "karras" in generation_metadata and "schedule_type" not in generation_metadata:
                    schedule_type = "karras" if generation_metadata.get("karras") else "native"
                    _add_metadata_text("Schedule type", schedule_type)

            # ! IMPORTANT: Start of own code
            except (KeyError, ValueError, TypeError) as e:
                # Handle metadata extraction errors, but continue with image processing
                logger.error(f"Failed to add metadata: {e}")
            # ! IMPORTANT: End of own code
            # ! IMPORTANT: End own code

            # ! IMPORTANT: Start of own code
            try:
                # Open the image using PIL
                image_as_pil = Image.open(image_bytes)
            except (OSError, ValueError) as e:
                # Handle PIL image open errors (corrupted images, unsupported formats)
                logger.error(f"Failed to open image: {type(e).__name__} {e}")
            # ! IMPORTANT: End of own code
                safety_evaluations.append(
                    HordeSafetyEvaluation(
                        is_nsfw=True,
                        is_csam=True,
                        replacement_image_base64=None,
                        failed=True,
                    ),
                )

                continue

            nsfw_result: NSFWResult | None = self._nsfw_checker.check_for_nsfw(
                image=image_as_pil,
                prompt=original_prompt, # ! IMPORTANT: Changed "message.prompt" to "original_prompt"
                model_info=message.horde_model_info,
            )

            if nsfw_result is None:
                raise RuntimeError("NSFW result is None")

            replacement_image_base64: str | None = None

            if nsfw_result.is_csam:
                replacement_image_base64 = self.censor_csam_image_base64
                logger.debug(f"CSAM detected in image {message.job_id}. Image is deleted.")
            elif message.sfw_worker and nsfw_result.is_nsfw:
                replacement_image_base64 = self.censor_sfw_worker_image_base64
                logger.info(f"SFW worker detected NSFW in image {message.job_id}.")
            elif message.censor_nsfw and nsfw_result.is_nsfw:
                replacement_image_base64 = self.censor_sfw_request_image_base64
                logger.info(f"Censor list detected NSFW in image {message.job_id}.")

            # ! IMPORTANT: Start own code
            if metadata is not None:
                if nsfw_result.is_csam:
                    metadata.add_text("Safety", "csam")
                elif replacement_image_base64:
                    metadata.add_text("Safety", "censored")
                elif nsfw_result.is_nsfw:
                    metadata.add_text("Safety", "nsfw")
                else:
                    metadata.add_text("Safety", "clean")

            try:
                # Save the image as a PNG file
                if metadata is not None:
                    image_as_pil_0.save(output_path, "png", pnginfo=metadata)
                else:
                    image_as_pil_0.save(output_path, "png")

                if metadata is not None:
                    logger.opt(ansi=True).info(
                        "<fg #00d9ff>"
                        f"SAVED image + embedded metadata to disk for job {message.job_id}: {output_path}"
                        "</>",
                    )
                    saved_images.append(HordeSavedImageInfo(path=output_path, metadata_embedded=True))
                else:
                    logger.opt(ansi=True).info(
                        "<fg #00d9ff>"
                        f"SAVED image to disk (no metadata) for job {message.job_id}: {output_path}"
                        "</>",
                    )
                    saved_images.append(HordeSavedImageInfo(path=output_path, metadata_embedded=False))
            except Exception as e:
                image_as_pil_0.save(output_path, "png")
                logger.warning(
                    f"Failed to save image with embedded metadata for job {message.job_id}; "
                    f"saved without metadata instead: {type(e).__name__} {e}. Path: {output_path}",
                )
                saved_images.append(HordeSavedImageInfo(path=output_path, metadata_embedded=False))
            # ! IMPORTANT: End own code

            safety_evaluations.append(
                HordeSafetyEvaluation(
                    is_nsfw=nsfw_result.is_nsfw,
                    is_csam=nsfw_result.is_csam,
                    replacement_image_base64=replacement_image_base64,
                ),
            )

        time_elapsed = time.time() - time_start

        info_message = f"Finished evaluating safety for job {message.job_id}"
        logger.info(info_message)

        self.process_message_queue.put(
            HordeSafetyResultMessage(
                process_id=self.process_id,
                process_launch_identifier=self.process_launch_identifier,
                info=info_message,
                time_elapsed=time_elapsed,
                job_id=message.job_id,
                safety_evaluations=safety_evaluations,
                # ! IMPORTANT: Start own code
                saved_images=saved_images,
                # ! IMPORTANT: End own code
            ),
        )
        self.send_process_state_change_message(HordeProcessState.WAITING_FOR_JOB, "Waiting for job")

    @override
    def cleanup_for_exit(self) -> None:
        return
