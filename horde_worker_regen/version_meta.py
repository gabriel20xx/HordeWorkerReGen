import datetime
import json
import os
import ssl
import time
import urllib.request
from loguru import logger
from pydantic import BaseModel

import horde_worker_regen
from horde_worker_regen.consts import VERSION_META_REMOTE_URL


class RequiredVersionInfo(BaseModel):
    """Information about a required version, such as the reason for the update."""

    reason_for_update: str


class BetaVersionInfo(BaseModel):
    """Information about a beta version, such as the expiry date or the model reference branch to use."""

    horde_model_reference_branch: str
    beta_expiry_date: str


class VersionMeta(BaseModel):
    """Metadata about the current version of the worker, such as the required or recommended versions."""

    recommended_version: str
    required_min_version: str
    required_min_version_update_date: str
    beta_version_info: dict[str, BetaVersionInfo]
    required_min_version_info: dict[str, RequiredVersionInfo]


def _version_tuple(v: str) -> tuple[int, ...]:
    """Parse a version string into a tuple of integers for comparison.

    Only the first three components (MAJOR, MINOR, PATCH) are considered.
    Versions with fewer than three components return a shorter tuple.

    Args:
        v: A version string such as '10.1.2'.

    Returns:
        A tuple of up to three integers representing the version components.

    Raises:
        ValueError: If the version string contains non-numeric components.
    """
    parts = v.split(".")[:3]
    try:
        return tuple(int(x) for x in parts)
    except ValueError as e:
        raise ValueError(f"Invalid version string {v!r}: version components must be numeric") from e


def _compare_versions(a: str, b: str) -> int:
    """Compare two semver strings. Returns -1, 0, or 1."""
    va, vb = _version_tuple(a), _version_tuple(b)
    if va < vb:
        return -1
    if va > vb:
        return 1
    return 0


def get_local_version_meta() -> VersionMeta:
    """Get the local _version_meta.json file as a `VersionMeta` object."""
    with open("horde_worker_regen/_version_meta.json") as f:
        data = json.load(f)
        return VersionMeta(**data)


def get_remote_version_meta() -> VersionMeta:
    """Get the remote version meta from the `VERSION_META_REMOTE_URL` as a `VersionMeta` object."""
    ssl_ctx = ssl.create_default_context()
    with urllib.request.urlopen(VERSION_META_REMOTE_URL, context=ssl_ctx) as response:
        data = json.loads(response.read())
    return VersionMeta(**data)


def do_version_check() -> None:
    """Check if the current worker version satisfies the required and recommended versions.

    Note that this function sets environment variables to indicate if the worker version is not the required or
    recommended version. It can also change the github branch used for the model reference if the current version is a
    beta version.
    """
    version_meta: VersionMeta
    try:
        version_meta = get_remote_version_meta()
    except Exception as e:
        logger.warning(f"Failed to get remote version meta: {e}")
        logger.warning("Using local version meta instead.")
        logger.warning("If this keeps happening, please check your internet connection and try again.")
        version_meta = get_local_version_meta()

    # If the required_min_version is not satisfied, raise an error
    if not _compare_versions(horde_worker_regen.__version__, version_meta.required_min_version) >= 0:
        # Get the reason for the required update
        reason_for_update = version_meta.required_min_version_info[version_meta.required_min_version].reason_for_update

        reason_for_update_str = f"Reason for update: {reason_for_update}" if reason_for_update else ""

        # UTC time
        current_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

        # If we're before the required_version_update_date, just warn, otherwise raise an error
        if current_date < version_meta.required_min_version_update_date:
            logger.warning(
                f"Current worker version {horde_worker_regen.__version__} has a required update to "
                f"{version_meta.required_min_version}. "
                f"Please update to the required version by 00:00 {version_meta.required_min_version_update_date} UTC.",
            )
            if reason_for_update_str:
                logger.warning(reason_for_update_str)

            os.environ["AIWORKER_NOT_REQUIRED_VERSION"] = "1"

        else:
            logger.error(
                f"Current worker version {horde_worker_regen.__version__} has a required update to "
                f"{version_meta.required_min_version}. We are past the date specified by the developers to update to "
                f"{version_meta.required_min_version_update_date}. Please update to the required version "
                "by running `git pull` and `update-runtime` (or the appropriate `pip install` "
                "if you're using your own venv.)",
            )
            if reason_for_update_str:
                logger.error(reason_for_update_str)

            input("Press Enter to continue...")
            exit(1)

    if not _compare_versions(horde_worker_regen.__version__, version_meta.recommended_version) >= 0:
        logger.warning(
            f"Current worker version {horde_worker_regen.__version__} is not the recommended version. "
            f"Please consider updating to {version_meta.recommended_version}.",
        )
        os.environ["AIWORKER_NOT_RECOMMENDED_VERSION"] = "1"

    if version_meta.beta_version_info:
        major, minor, patch = _version_tuple(horde_worker_regen.__version__)
        current_version_simple = f"{major}.{minor}.{patch}"

        if current_version_simple in version_meta.beta_version_info:
            beta_info = version_meta.beta_version_info[current_version_simple]

            already_set_branch = os.getenv("HORDE_MODEL_REFERENCE_GITHUB_BRANCH")
            if already_set_branch is None and not time.strftime("%Y-%m-%d") > beta_info.beta_expiry_date:
                logger.info(
                    f"Current worker version {horde_worker_regen.__version__} is a beta version. "
                    f"Using the model reference branch {beta_info.horde_model_reference_branch}.",
                )
                os.environ["HORDE_MODEL_REFERENCE_GITHUB_BRANCH"] = beta_info.horde_model_reference_branch
