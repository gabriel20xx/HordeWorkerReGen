"""Utilities for configuring the logger with a standardized format."""

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger


def create_level_format_function(time_format: str = "YYYY-MM-DD HH:mm:ss.SSS") -> Callable[[dict[str, Any]], str]:
    """Create a format function for console output with level-based colors.

    Returns a callable suitable for ``logger.add(format=...)``.  The timestamp
    is never colored so it is always easy to parse.  Only the level indicator
    and message body are colored.

    Args:
        time_format: Loguru time format string.  Defaults to millisecond precision.
    """
    level_formats = {
        "TRACE": (
            f"{{time:{time_format}}} <dim>|</dim>"
            f" <dim><cyan>{{level: <8}}</cyan></dim> <dim>|</dim> <dim>{{message}}</dim>"
        ),
        "DEBUG": f"{{time:{time_format}}} <dim>|</dim> <blue>{{level: <8}}</blue> <dim>|</dim> {{message}}",
        "INFO": (
            f"{{time:{time_format}}} <dim>|</dim>"
            f" <bold><cyan>{{level: <8}}</cyan></bold> <dim>|</dim> {{message}}"
        ),
        "SUCCESS": (
            f"{{time:{time_format}}} <dim>|</dim>"
            f" <bold><green>{{level: <8}}</green></bold> <dim>|</dim> <bold><green>{{message}}</green></bold>"
        ),
        "WARNING": (
            f"{{time:{time_format}}} <dim>|</dim>"
            f" <bold><yellow>{{level: <8}}</yellow></bold> <dim>|</dim> <bold><yellow>{{message}}</yellow></bold>"
        ),
        "ERROR": (
            f"{{time:{time_format}}} <dim>|</dim>"
            f" <bold><red>{{level: <8}}</red></bold> <dim>|</dim> <bold><red>{{message}}</red></bold>"
        ),
        "CRITICAL": (
            f"{{time:{time_format}}} <dim>|</dim>"
            f" <bold><fg #8B0000><u>{{level: <8}}</u></fg #8B0000></bold>"
            f" <dim>|</dim> <bold><fg #8B0000>{{message}}</fg #8B0000></bold>"
        ),
    }

    def format_record(record: dict[str, Any]) -> str:
        level_name = record["level"].name
        if level_name in level_formats:
            return level_formats[level_name] + "\n{exception}"
        return (
            f"{{time:{time_format}}} <dim>|</dim> <bold>{{level: <8}}</bold>"
            f" <dim>|</dim> {{message}}\n{{exception}}"
        )

    return format_record


def create_plain_format_function(time_format: str = "YYYY-MM-DD HH:mm:ss.SSS") -> Callable[[dict[str, Any]], str]:
    """Create a plain-text format function for file output.

    Identical layout to the console format but contains no ANSI escape codes,
    no loguru color tags, and includes the source location
    (``module:function:line``) as a fourth field.  This makes log files
    readable in any text editor or ``grep`` without stray color characters.

    Format::

        2026-06-19 10:30:00.123 | INFO     | some.module:my_func:42 | message text

    Args:
        time_format: Loguru time format string.  Defaults to millisecond precision.
    """
    fmt = f"{{time:{time_format}}} | {{level: <8}} | {{name}}:{{function}}:{{line}} | {{message}}\n{{exception}}"

    def format_record(_record: dict[str, Any]) -> str:
        return fmt

    return format_record


_LOGS_DIR = Path("logs")

# Loguru substitutes {time:...} tokens anywhere in the sink path — including directory
# components — when it opens or rotates a file.  Using {time:YYYY-MM-DD} as a folder
# segment means each calendar day gets its own subdirectory automatically.
_DATE_SUBDIR = "{time:YYYY-MM-DD}"

# Rotation/retention policy:
#   bridge/ and trace/ — keep 7 days; crash/ — keep 30 days (crash logs are rare and valuable).
_LOG_ROTATION = "00:00"        # midnight: one file per day
_LOG_RETENTION = "7 days"
_TRACE_RETENTION = "7 days"
_CRASH_RETENTION = "30 days"
_CRASH_ROTATION = "00:00"

# Module-name prefixes whose INFO/DEBUG messages are suppressed on the console.
# These are ComfyUI internals and low-level hordelib plumbing that produce high-volume
# status lines (device placement, attention mode, VAE dtype …) that belong in log files
# but clutter the terminal.  WARNING and above always pass through so real problems
# remain visible.
_CONSOLE_SUPPRESSED_PREFIXES: tuple[str, ...] = (
    "comfy",          # ComfyUI core (comfy.model_management, comfy.ldm.*, …)
    "nodes",          # ComfyUI custom-node modules
    "execution",      # ComfyUI prompt-executor
    "folder_paths",   # ComfyUI path helpers
    "hordelib.comfy", # hordelib's thin ComfyUI wrappers
)


def _make_console_filter(warn_level_no: int) -> Any:
    """Return a loguru filter that suppresses noisy ComfyUI modules below WARNING."""
    prefixes = _CONSOLE_SUPPRESSED_PREFIXES

    def _filter(record: dict[str, Any]) -> bool:
        if record["level"].no >= warn_level_no:
            return True  # always show WARNING / ERROR / CRITICAL
        name: str = record["name"] or ""
        for prefix in prefixes:
            if name == prefix or name.startswith(prefix + "."):
                return False
        return True

    return _filter


def _install_excepthook() -> None:
    """Install sys.excepthook and threading.excepthook to capture unhandled exceptions.

    Any exception that escapes without being caught is logged at CRITICAL level
    so it appears in both ``trace.log`` and ``crash.log`` before the process
    exits.  KeyboardInterrupt and SystemExit are passed through to the default
    handler unchanged.
    """

    def _handle_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: Any,
    ) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.opt(exception=(exc_type, exc_value, exc_tb)).critical(
            "Unhandled exception — process will exit"
        )

    sys.excepthook = _handle_exception

    def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is None or issubclass(args.exc_type, SystemExit):
            return
        thread_name = args.thread.name if args.thread is not None else "<unknown>"
        try:
            logger.opt(exception=(args.exc_type, args.exc_value, args.exc_tb)).critical(
                f"Unhandled exception in thread '{thread_name}'"
            )
        except Exception:
            # Last-resort: if loguru itself fails, print to stderr so the exception
            # is not silently swallowed (e.g. during process shutdown).
            print(
                f"CRITICAL (logger unavailable): unhandled exception in thread '{thread_name}':"
                f" {args.exc_type.__name__}: {args.exc_value}",
                file=sys.stderr,
            )

    threading.excepthook = _handle_thread_exception


def configure_logger_format(process_id: int | None = None, *, enable_stderr: bool = True) -> None:
    """Configure the logger with a standardized format: timestamp | level | source | message.

    Call this after ``HordeLog.initialise()`` to replace the default format with
    a consistent pattern that works across the main process and all subprocesses.

    Log directory layout
    --------------------
    Files are written under ``logs/YYYY-MM-DD/`` — a new date directory is created
    automatically at midnight when the sinks rotate.  Within each date directory there
    is one subdirectory per log *type*::

        logs/
          2026-06-22/
            bridge/          ← full operational log; all messages at the configured level
            │  bridge.log    ← main process
            │  bridge_1.log  ← subprocess 1
            │  bridge_2.log  ← subprocess 2 …
            trace/           ← ERROR and above; full backtraces
            │  trace.log     ← main process
            │  trace_1.log   ← subprocess 1 …
            crash/           ← CRITICAL only; diagnose=True  (main process only)
            │  crash.log
            webui/           ← horde_worker_regen.webui module only  (main process only)
               webui.log

    Retention: ``bridge/`` and ``trace/`` → 7 days; ``crash/`` → 30 days.

    File format (plain text, no color characters)::

        2026-06-19 10:30:00.123 | INFO     | module:function:line | message

    Console format uses level-based ANSI colors but is otherwise identical
    (source location omitted to keep the console concise).

    Environment variables
    ---------------------
    ``AIWORKER_LOG_LEVEL``
        Set the log level (TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL).
        Default: INFO.
    ``AIWORKER_DEBUG``
        Legacy flag: set to ``1``, ``true``, or ``yes`` to force DEBUG level.

    Args:
        process_id: Optional subprocess identifier.  ``None`` (default) → main
            process files.  Subprocesses pass their integer ID so output goes to
            dedicated files (e.g. ``bridge_1.log`` / ``trace_1.log``).
        enable_stderr: When ``True`` (default) a stderr console sink is added.
            Pass ``False`` when console logging is disabled (``--no-logging``).
    """
    logger.remove()

    log_level = os.getenv("AIWORKER_LOG_LEVEL", "INFO").upper()
    valid_levels = ["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
    if log_level not in valid_levels:
        print(f"Warning: Invalid AIWORKER_LOG_LEVEL '{log_level}', defaulting to INFO")
        log_level = "INFO"

    if os.getenv("AIWORKER_DEBUG", "").lower() in ("1", "true", "yes"):
        log_level = "DEBUG"

    console_format = create_level_format_function(time_format="YYYY-MM-DD HH:mm:ss.SSS")
    file_format = create_plain_format_function(time_format="YYYY-MM-DD HH:mm:ss.SSS")

    if enable_stderr:
        _warn_level_no = logger.level("WARNING").no
        logger.add(
            sys.stderr,
            format=console_format,
            level=log_level,
            colorize=True,
            filter=_make_console_filter(_warn_level_no),
        )

    # Build per-type sink paths.  The {time:YYYY-MM-DD} token in the date directory
    # component is replaced by loguru when it opens or rotates a file, so each calendar
    # day gets its own subdirectory automatically.
    date_dir = _LOGS_DIR / _DATE_SUBDIR

    if process_id is None:
        bridge_log = date_dir / "bridge" / "bridge.log"
        trace_log  = date_dir / "trace"  / "trace.log"
    else:
        bridge_log = date_dir / "bridge" / f"bridge_{process_id}.log"
        trace_log  = date_dir / "trace"  / f"trace_{process_id}.log"

    # logs/ root is created here; loguru creates the date and type subdirectories itself.
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # bridge/ — full operational log: all messages at the configured level.
    logger.add(
        bridge_log,
        format=file_format,
        level=log_level,
        colorize=False,
        rotation=_LOG_ROTATION,
        retention=_LOG_RETENTION,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
        delay=True,
    )

    # trace/ — error trace log: ERROR and above with full backtraces.
    # diagnose=True only for the main process: subprocesses run GPU/ML code and
    # introspecting CUDA tensors after an OOM or hardware fault is unsafe.
    logger.add(
        trace_log,
        format=file_format,
        level="ERROR",
        colorize=False,
        rotation=_LOG_ROTATION,
        retention=_TRACE_RETENTION,
        encoding="utf-8",
        backtrace=True,
        diagnose=process_id is None,
        delay=True,
    )

    # crash/ and webui/ are main-process-only sinks.
    if process_id is None:
        # crash/ — CRITICAL only: first place to look when the worker dies.
        logger.add(
            date_dir / "crash" / "crash.log",
            format=file_format,
            level="CRITICAL",
            colorize=False,
            rotation=_CRASH_ROTATION,
            retention=_CRASH_RETENTION,
            encoding="utf-8",
            backtrace=True,
            diagnose=True,
            delay=True,
        )

        # webui/ — scoped to the webui module so its traffic stays out of bridge/.
        def _webui_filter(record: dict[str, Any]) -> bool:
            return record["name"].startswith("horde_worker_regen.webui")

        logger.add(
            date_dir / "webui" / "webui.log",
            format=file_format,
            level=log_level,
            colorize=False,
            rotation=_LOG_ROTATION,
            retention=_LOG_RETENTION,
            encoding="utf-8",
            filter=_webui_filter,
            backtrace=True,
            diagnose=False,
            delay=True,
        )

    _install_excepthook()

    if log_level != "INFO":
        logger.info(f"Log level: {log_level}")

    pid = os.getpid()
    if process_id is None:
        from datetime import date  # noqa: PLC0415

        today_log_dir = (_LOGS_DIR / str(date.today())).resolve()
        logger.info(f"{'=' * 60}")
        logger.info(f"  Worker main process started (PID={pid})")
        logger.info(f"  Logs root  : {_LOGS_DIR.resolve()}")
        logger.info(f"  Today      : {today_log_dir}")
        logger.info(f"    bridge/  — all messages ({log_level}+)")
        logger.info(f"    trace/   — ERROR+ with backtraces")
        logger.info(f"    crash/   — CRITICAL only")
        logger.info(f"    webui/   — webui module only")
        logger.info(f"{'=' * 60}")
    else:
        logger.info(f"--- Subprocess {process_id} started (PID={pid}) ---")
