import argparse
import os
import sys

from loguru import logger

from horde_worker_regen.download_models import download_all_models
from horde_worker_regen.version_meta import do_version_check

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download all models specified in the config file.")
    parser.add_argument(
        "--purge-unused-loras",
        action="store_true",
        help="Purge unused LORAs from the cache",
    )
    parser.add_argument(
        "-e",
        "--load-config-from-env-vars",
        action="store_true",
        default=False,
        help="Load the config only from environment variables. This is useful for running the worker in a container.",
    )
    parser.add_argument(
        "--directml",
        type=int,
        default=None,
        help="Enable directml and specify device to use.",
    )

    args = parser.parse_args()

    do_version_check()

    download_all_models(
        purge_unused_loras=args.purge_unused_loras,
        load_config_from_env_vars=args.load_config_from_env_vars,
        directml=args.directml,
    )

    # download_all_models() returning means every model downloaded/validated successfully
    # (failures call exit(1) internally and never reach here). hordelib.initialise() -- called
    # inside download_all_models() to get at the model managers -- imports torch/ComfyUI, which
    # leaves behind CUDA contexts, background threads, and large cached tensors that make a normal
    # interpreter shutdown (atexit handlers, non-daemon thread joins, GC) take a long time. This is
    # a one-shot script with no further work to do and nothing left to flush, so skip that entirely
    # and exit immediately -- the bridge scripts (horde-bridge.*) just check the exit code before
    # launching run_worker.py next, so this doesn't change any observable behaviour besides speed.
    logger.complete()  # drain any loguru sinks configured with enqueue=True before the hard exit
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
