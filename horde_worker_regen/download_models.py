"""Contains the code to download all models specified in the config file. Executable as a standalone script."""

import importlib.util
import pathlib
import warnings

# Directory inside the hordelib package where annotator models used to live. Annotators are
# stored in the model cache nowadays; hordelib's preload_annotators() warns on startup for
# every model file it still finds here ("This file can be safely deleted").
_HORDELIB_LEGACY_CKPTS_DIR = ("nodes", "comfy_controlnet_preprocessors", "ckpts")

# Model files and interrupted-download leftovers (*.partial) in the legacy directory.
_HORDELIB_LEGACY_ANNOTATOR_GLOBS = [
    "*.pt",
    "*.pth",
    "*.ckpt",
    "*.safetensors",
    "*.partial",
]


def remove_legacy_annotators() -> None:
    """Delete stale annotator files that hordelib moved out of its package directory.

    hordelib warns about each of these on startup and states they can be safely deleted,
    so this silences the warnings by doing exactly that. Called both by the model download
    script and by worker startup.
    """
    spec = importlib.util.find_spec("hordelib")
    if spec is None or not spec.origin:
        return
    ckpts_dir = pathlib.Path(spec.origin).parent.joinpath(*_HORDELIB_LEGACY_CKPTS_DIR)
    if not ckpts_dir.is_dir():
        return

    removed: list[str] = []
    for pattern in _HORDELIB_LEGACY_ANNOTATOR_GLOBS:
        for legacy in ckpts_dir.glob(pattern):
            if not legacy.is_file():
                continue
            try:
                legacy.unlink()
                removed.append(legacy.name)
            except OSError:
                pass

    if removed:
        from loguru import logger

        logger.info(
            f"Removed {len(removed)} legacy annotator file(s) from the hordelib package directory: "
            f"{', '.join(sorted(removed))}",
        )


def download_all_models(
    *,
    load_config_from_env_vars: bool = False,
    purge_unused_loras: bool = False,
    directml: int | None = None,
) -> None:
    """Download all models specified in the config file."""
    from horde_worker_regen.load_env_vars import load_dotenv, load_env_vars_from_config

    load_dotenv()
    if not load_config_from_env_vars:
        load_env_vars_from_config()

    import time

    from horde_model_reference.meta_consts import MODEL_REFERENCE_CATEGORY
    from horde_model_reference.model_reference_manager import ModelReferenceManager
    from loguru import logger

    from horde_worker_regen.bridge_data.load_config import BridgeDataLoader, reGenBridgeData
    from horde_worker_regen.consts import BRIDGE_CONFIG_FILENAME

    horde_model_reference_manager = ModelReferenceManager(
        download_and_convert_legacy_dbs=False,
        override_existing=False,
    )

    while True:
        try:
            all_refs = horde_model_reference_manager.get_all_model_references(redownload_all=True)
            if not all_refs.get(MODEL_REFERENCE_CATEGORY.stable_diffusion):
                logger.error("Image generation model references not found. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                break
        except Exception as e:
            logger.error(f"Failed to download model references: ({type(e).__name__}) {e}")
            logger.error("Retrying in 5 seconds...")
            time.sleep(5)

    bridge_data: reGenBridgeData | None = None
    try:
        if not load_config_from_env_vars:
            bridge_data = BridgeDataLoader.load(
                file_path=BRIDGE_CONFIG_FILENAME,
                horde_model_reference_manager=horde_model_reference_manager,
            )
            bridge_data.load_env_vars()
            bridge_data.prepare_custom_models()
        else:
            bridge_data = BridgeDataLoader.load_from_env_vars(
                horde_model_reference_manager=horde_model_reference_manager,
            )
    except Exception as e:
        logger.error(e)
        # stdin is closed in non-interactive environments (Docker, CI) — don't crash on EOFError.
        try:
            input("Press any key to exit...")
        except EOFError:
            pass

    if bridge_data is None:
        logger.error("Failed to load bridge data")
        exit(1)

    # Suppress known warnings from dependencies
    warnings.filterwarnings("ignore", category=UserWarning, message=".*QuickGELU.*")

    import hordelib
    from horde_safety.deep_danbooru_model import download_deep_danbooru_model
    from horde_safety.interrogate import get_interrogator_no_blip

    download_deep_danbooru_model()
    get_interrogator_no_blip()

    extra_comfyui_args = []
    if directml is not None:
        extra_comfyui_args.append(f"--directml={directml}")

    hordelib.initialise(extra_comfyui_args=extra_comfyui_args)
    from hordelib.shared_model_manager import SharedModelManager

    # Validate lora.json before loading model managers. If a previous run was interrupted
    # mid-write the file may contain truncated JSON, which causes hordelib to log an ERROR
    # and fall back to a backup. Deleting the corrupted file here lets hordelib start clean
    # (it logs a WARNING instead of an ERROR when the file is simply absent).
    try:
        import json

        from horde_model_reference import LEGACY_REFERENCE_FOLDER

        lora_db_path = LEGACY_REFERENCE_FOLDER / "lora.json"
        if lora_db_path.exists():
            try:
                # We only care whether the parse succeeds, not the parsed value.
                json.loads(lora_db_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning(
                    f"Corrupted lora reference cache detected at {lora_db_path}. "
                    "Removing it so that it can be rebuilt cleanly on startup.",
                )
                lora_db_path.unlink(missing_ok=True)
    except Exception as e:
        logger.debug(f"Could not validate lora reference cache before startup: {e}")

    SharedModelManager.load_model_managers()

    if bridge_data.allow_lora:
        if SharedModelManager.manager.lora is None:
            logger.error("Failed to load LORA model manager")
            exit(1)
        SharedModelManager.manager.lora.reset_adhoc_loras()
        SharedModelManager.manager.lora.download_default_loras(bridge_data.nsfw)
        SharedModelManager.manager.lora.wait_for_downloads(600)
        SharedModelManager.manager.lora.wait_for_adhoc_reset(120)

    if purge_unused_loras or bridge_data.purge_loras_on_download:
        logger.info("Purging unused LORAs...")
        if SharedModelManager.manager.lora is None:
            logger.error("Failed to load LORA model manager")
            exit(1)
        deleted_loras = SharedModelManager.manager.lora.delete_unused_loras(30)
        logger.success(f"Purged {len(deleted_loras)} unused LORAs.")

    if bridge_data.allow_controlnet:
        if SharedModelManager.manager.controlnet is None:
            logger.error("Failed to load controlnet model manager")
            exit(1)
        for cn_model in SharedModelManager.manager.controlnet.model_reference:
            if (
                cn_model not in SharedModelManager.manager.controlnet.available_models
                and "sdxl" in cn_model.lower()
                and not bridge_data.allow_sdxl_controlnet
            ):
                logger.warning(f"Skipping download of {cn_model} because `allow_sdxl_controlnet` is false.")
                continue

            SharedModelManager.manager.controlnet.download_model(cn_model)
        remove_legacy_annotators()
        if not SharedModelManager.preload_annotators():
            logger.error("Failed to download the controlnet annotators")
            exit(1)

    if bridge_data.allow_sdxl_controlnet:
        if SharedModelManager.manager.miscellaneous is None:
            logger.error("Failed to load miscellaneous model manager")
            exit(1)
        SharedModelManager.manager.miscellaneous.download_all_models()
        for model in SharedModelManager.manager.miscellaneous.model_reference:
            if not SharedModelManager.manager.miscellaneous.validate_model(
                model,
            ) and not SharedModelManager.manager.miscellaneous.download_model(model):
                logger.error(f"Failed to download model {model}")
                exit(1)
        else:
            logger.success("Downloaded all Miscellaneous models")

    if bridge_data.allow_post_processing:
        if SharedModelManager.manager.gfpgan is None:
            logger.error("Failed to load GFPGAN model manager")
            exit(1)
        if SharedModelManager.manager.esrgan is None:
            logger.error("Failed to load ESRGAN model manager")
            exit(1)
        if SharedModelManager.manager.codeformer is None:
            logger.error("Failed to load codeformer model manager")
            exit(1)

        SharedModelManager.manager.gfpgan.download_all_models()
        for model in SharedModelManager.manager.gfpgan.model_reference:
            if not SharedModelManager.manager.gfpgan.validate_model(
                model,
            ) and not SharedModelManager.manager.gfpgan.download_model(model):
                logger.error(f"Failed to download model {model}")
                exit(1)
        else:
            logger.success("Downloaded all GFPGAN models")

        SharedModelManager.manager.esrgan.download_all_models()
        for model in SharedModelManager.manager.esrgan.model_reference:
            if not SharedModelManager.manager.esrgan.validate_model(
                model,
            ) and not SharedModelManager.manager.esrgan.download_model(model):
                logger.error(f"Failed to download model {model}")
                exit(1)
        else:
            logger.success("Downloaded all ESRGAN models")

        SharedModelManager.manager.codeformer.download_all_models()
        for model in SharedModelManager.manager.codeformer.model_reference:
            if not SharedModelManager.manager.codeformer.validate_model(
                model,
            ) and not SharedModelManager.manager.codeformer.download_model(model):
                logger.error(f"Failed to download model {model}")
                exit(1)

    if SharedModelManager.manager.compvis is None:
        logger.error("Failed to load compvis model manager")
        exit(1)

    any_compvis_model_failed_to_download = False
    for model in bridge_data.image_models_to_load:
        if not SharedModelManager.manager.compvis.download_model(model):
            logger.error(f"Failed to download model {model}")
            any_compvis_model_failed_to_download = True

        # This will check the SHA of the model and redownload it if it's corrupted or the model reference entry changed
        if not SharedModelManager.manager.compvis.validate_model(model):  # noqa: SIM102
            if not SharedModelManager.manager.compvis.download_model(model):
                logger.error(f"Failed to redownload model {model}")
                any_compvis_model_failed_to_download = True

    if any_compvis_model_failed_to_download:
        logger.error("Failed to download all models.")
        exit(1)
    else:
        logger.success("Downloaded all compvis (Stable Diffusion) models.")
