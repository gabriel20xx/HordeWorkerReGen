# ComfyUI Version Information

## Summary

**HordeWorkerReGen uses ComfyUI commit: `73e04987f7e0f14bdee9baa0aafe61cf7f42a8b2`**

This corresponds to a ComfyUI commit from around **December 2024**.

## How ComfyUI is Integrated

ComfyUI is not directly installed by HordeWorkerReGen. Instead, it comes embedded within the `horde-engine` package (formerly known as `hordelib`), which serves as a wrapper around ComfyUI.

### Dependency Chain

```
HordeWorkerReGen (this project)
    └── horde-engine ~= 2.20.12 (specified in requirements.txt)
        └── ComfyUI commit 73e04987f7e0f14bdee9baa0aafe61cf7f42a8b2 (embedded)
```

## Version Details

### HordeWorkerReGen Configuration
- **File**: `/requirements.txt`
- **Dependency**: `horde_engine~=2.20.12`

### Horde-Engine Version
- **Package Name**: `horde-engine` (PyPI)
- **Version**: 2.20.12
- **Release Date**: 7 January 2025
- **GitHub**: https://github.com/Haidra-Org/hordelib

### ComfyUI Version
- **Commit Hash**: `73e04987f7e0f14bdee9baa0aafe61cf7f42a8b2`
- **Specified In**: `hordelib/consts.py` in the horde-engine v2.20.12 release
- **Variable Name**: `COMFYUI_VERSION`
- **GitHub**: https://github.com/comfyanonymous/ComfyUI

## Version History

The ComfyUI version has been updated through horde-engine releases:

- **v2.20.2** (24 Dec 2024): ComfyUI commit `73e0498`
- **v2.19.0** (22 Nov 2024): ComfyUI commit `839ed33`
- **v2.18.0** (13 Nov 2024): ComfyUI commit `3b9a6cf`
- **v2.17.0** (20 Oct 2024): ComfyUI commit `73e3a9e6`

Since HordeWorkerReGen uses horde-engine v2.20.12 (released after v2.20.2), it includes the ComfyUI commit from v2.20.2.

## How ComfyUI is Used

1. **Initialization**: ComfyUI is initialized through `hordelib.initialise()` with optional extra arguments
   - Location: `horde_worker_regen/download_models.py:68`
   - Location: `horde_worker_regen/process_management/worker_entry_points.py:128`

2. **Extra Arguments**: The worker passes various ComfyUI command-line arguments based on configuration:
   - `--disable-smart-memory`
   - `--use-pytorch-cross-attention`
   - `--directml=<device_id>` (for DirectML)
   - `--gpu-only`
   - `--novram`
   - `--reserve-vram <amount>`

3. **Callback Integration**: ComfyUI progress is tracked through callbacks
   - Location: `horde_worker_regen/process_management/inference_process.py`
   - Progress data includes current step and total steps via `comfyui_progress`

## Installation

ComfyUI is automatically installed when horde-engine is installed. The horde-engine package includes:
- Installation script: `hordelib/install_comfy.py`
- ComfyUI git repository cloning and checkout to specific commit
- Custom patches applied to ComfyUI for horde integration

## Verification

To verify the ComfyUI version in use:

1. Check horde-engine version:
   ```bash
   pip show horde-engine
   ```

2. Look up the version in horde-engine's `hordelib/consts.py`:
   ```python
   COMFYUI_VERSION = "73e04987f7e0f14bdee9baa0aafe61cf7f42a8b2"
   ```

## Additional Information

- **ComfyUI License**: GNU General Public License v3.0
- **Integration Purpose**: Enable AI Horde to run inference pipelines designed in ComfyUI GUI
- **Custom Nodes**: Horde-engine includes custom ComfyUI nodes for specific processing needs
- **Frontend Package**: horde-engine also installs `comfyui-frontend-package==1.25.11`

## References

- [ComfyUI GitHub Repository](https://github.com/comfyanonymous/ComfyUI)
- [Horde-Engine GitHub Repository](https://github.com/Haidra-Org/hordelib)
- [Horde-Engine PyPI Page](https://pypi.org/project/horde-engine/)
- [Horde-Engine Changelog](https://github.com/Haidra-Org/hordelib/blob/releases/CHANGELOG.md)
- [AI Horde Discord](https://discord.gg/3DxrhksKzn)
