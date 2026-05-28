@echo off
cd /d %~dp0

: Prevent NVIDIA driver file-cache init errors
if not defined CUDA_CACHE_DISABLE set CUDA_CACHE_DISABLE=1
: Defer CUDA module loading to reduce startup errors with mismatched driver versions
if not defined CUDA_MODULE_LOADING set CUDA_MODULE_LOADING=LAZY

: This first call to runtime activates the environment for the rest of the script
call runtime python -s -m pip -V

call python -s -m pip uninstall hordelib
call python -s -m pip install horde_sdk~=0.17.1 horde_model_reference~=0.10.0 horde_engine~=2.22.2 horde_safety~=0.3.0 -U

if %ERRORLEVEL% NEQ 0 (
    echo "Please run update-runtime.cmd."
    GOTO END
)

call python -s -m pip check
if %ERRORLEVEL% NEQ 0 (
    echo "Please run update-runtime.cmd."
    GOTO END
)

:DOWNLOAD
call python -s download_models.py
if %ERRORLEVEL% NEQ 0 GOTO ABORT
echo "Model Download OK. Starting worker..."
call python -s run_worker.py %*

GOTO END

:ABORT
echo "download_models.py exited with error code. Aborting"

:END
call "%MAMBA_ROOT_PREFIX%\condabin\micromamba.bat" deactivate >nul
call deactivate >nul
pause
