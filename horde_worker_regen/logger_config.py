"""Utilities for configuring the logger with a standardized format."""

import sys

from loguru import logger


def configure_logger_format() -> None:
    """Configure the logger with a standardized format: timestamp | level | message.

    This should be called after HordeLog.initialise() to override the default format
    with a consistent pattern across all processes.

    Format: {time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}

    Example output:
        2026-02-04 21:44:03 | INFO     | Worker starting...
        2026-02-04 21:44:05 | SUCCESS  | Job completed successfully
        2026-02-04 21:44:06 | ERROR    | Job failed with error
    """
    # Remove all handlers added by HordeLog
    logger.remove()

    # Add new handler with standardized format
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG",
        colorize=True,  # Preserve ANSI colors from logger.opt(ansi=True)
    )
