"""Compatibility shim: make horde_model_reference 2.x work with hordelib from horde_engine 2.x.

hordelib (shipped inside horde_engine~=2.22.2) was written against the horde_model_reference 0.x API.
horde_sdk~=0.18.0 requires horde_model_reference>=2.0.0.

This module patches the installed horde_model_reference 2.x package at runtime so that the three
symbols hordelib depends on are importable, and so that the renamed enum member is accessible:

  1. ``MODEL_REFERENCE_CATEGORY.stable_diffusion`` – aliased to ``.image_generation``
  2. ``get_model_reference_file_path``               – bound method exposed at module level
  3. ``get_model_reference_filename``                – bound method exposed at module level
  4. ``LEGACY_REFERENCE_FOLDER``                     – ``horde_model_reference_paths.legacy_path``

Import this module **before** any ``import hordelib`` or ``hordelib.initialise()`` call.
"""

from __future__ import annotations

import horde_model_reference
import horde_model_reference.meta_consts as _meta


def _apply() -> None:
    cat = _meta.MODEL_REFERENCE_CATEGORY

    # 1. Add stable_diffusion alias so hordelib/model_manager/base.py can build _temp_reference_lookup.
    if "stable_diffusion" not in cat._member_map_:  # type: ignore[attr-defined]
        cat._member_map_["stable_diffusion"] = cat.image_generation  # type: ignore[attr-defined]

    paths = horde_model_reference.horde_model_reference_paths  # type: ignore[attr-defined]

    # 2 & 3. Expose the two path helpers as module-level callables (listed in __all__ but not imported).
    if not hasattr(horde_model_reference, "get_model_reference_file_path"):
        horde_model_reference.get_model_reference_file_path = paths.get_model_reference_file_path  # type: ignore[attr-defined]

    if not hasattr(horde_model_reference, "get_model_reference_filename"):
        horde_model_reference.get_model_reference_filename = paths.get_model_reference_filename  # type: ignore[attr-defined]

    # 4. Expose LEGACY_REFERENCE_FOLDER (was a Path constant in 0.x).
    if not hasattr(horde_model_reference, "LEGACY_REFERENCE_FOLDER"):
        horde_model_reference.LEGACY_REFERENCE_FOLDER = paths.legacy_path  # type: ignore[attr-defined]


_apply()
