"""Compatibility shim: make horde_model_reference 2.x work with hordelib from horde_engine 2.x.

hordelib (shipped inside horde_engine~=2.22.2) was written against the horde_model_reference 0.x API.
horde_sdk~=0.18.0 requires horde_model_reference>=2.0.0.

This module patches the installed horde_model_reference 2.x package at runtime so that the four
symbols/aliases hordelib depends on are available:

  1. ``MODEL_REFERENCE_CATEGORY.stable_diffusion`` – aliased to ``.image_generation``
  2. ``get_model_reference_file_path``               – bound method exposed at module level
  3. ``get_model_reference_filename``                – bound method exposed at module level
  4. ``LEGACY_REFERENCE_FOLDER``                     – ``horde_model_reference_paths.legacy_path``

Import this module **before** any ``import hordelib`` or ``hordelib.initialise()`` call.
"""

from __future__ import annotations

try:
    import horde_model_reference
    import horde_model_reference.meta_consts as _meta
except ImportError:
    # If horde_model_reference or its meta_consts module is unavailable,
    # leave this shim as a no-op so that simply importing it never fails.
    horde_model_reference = None  # type: ignore[assignment]
    _meta = None  # type: ignore[assignment]


def _apply() -> None:
    if horde_model_reference is None or _meta is None:  # type: ignore[comparison-overlap]
        return

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


def _validate() -> None:
    """Basic sanity checks to ensure this compatibility shim still provides the symbols and enum alias that hordelib expects."""
    if horde_model_reference is None or _meta is None:  # type: ignore[comparison-overlap]
        return

    cat = _meta.MODEL_REFERENCE_CATEGORY

    # Ensure the stable_diffusion alias exists and points to image_generation.
    member_map = getattr(cat, "_member_map_", None)  # type: ignore[attr-defined]
    assert isinstance(member_map, dict) and "stable_diffusion" in member_map, (
        "horde_model_reference.MODEL_REFERENCE_CATEGORY is missing the "
        "'stable_diffusion' member after applying the compatibility shim"
    )
    assert member_map["stable_diffusion"] is cat.image_generation, (  # type: ignore[attr-defined]
        "horde_model_reference.MODEL_REFERENCE_CATEGORY.stable_diffusion does "
        "not alias .image_generation as expected"
    )

    # Ensure the expected module-level attributes are present.
    for attr in (
        "get_model_reference_file_path",
        "get_model_reference_filename",
        "LEGACY_REFERENCE_FOLDER",
    ):
        assert hasattr(horde_model_reference, attr), (
            f"horde_model_reference.{attr} is missing after applying the "
            "compatibility shim"
        )


_apply()
_validate()
