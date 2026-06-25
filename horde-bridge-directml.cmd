@echo off
cd /d %~dp0

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
call python -s download_models.py --directml=0
if %ERRORLEVEL% NEQ 0 GOTO ABORT
echo "Model Download OK. Starting worker..."

:RUN_WORKER
call python -s run_worker.py --directml=0 %*
: Exit code 42 (consts.WORKER_RESTART_EXIT_CODE) means the worker requested a restart.
: os.execv cannot restart in-place on Windows, so the worker exits with this code and we re-run it.
if %ERRORLEVEL% EQU 42 (
    echo "Worker requested a restart. Restarting..."
    GOTO RUN_WORKER
)

GOTO END

:ABORT
echo "download_models.py exited with error code. Aborting"

:END
call micromamba deactivate >nul
call deactivate >nul
pause
