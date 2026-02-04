"""Utilities for configuring the logger with a standardized format."""

import sys

from loguru import logger


def configure_logger_format() -> None:
    """Configure the logger with a standardized format: timestamp | level | message.

    This should be called after HordeLog.initialise() to override the default format
    with a consistent pattern across all processes with enhanced colors.

    Format: {time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}

    Example output:
        2026-02-04 21:44:03.123 | INFO     | Worker starting...
        2026-02-04 21:44:05.456 | SUCCESS  | Job completed successfully
        2026-02-04 21:44:06.789 | ERROR    | Job failed with error
    """
    # Remove all handlers added by HordeLog
    logger.remove()

    # Define custom level colors for better visual distinction
    level_formats = {
        "TRACE": "<dim><cyan>{time:YYYY-MM-DD HH:mm:ss.SSS}</cyan></dim> <dim>│</dim> <dim><cyan>{level: <8}</cyan></dim> <dim>│</dim> <dim>{message}</dim>",
        "DEBUG": "<dim><blue>{time:YYYY-MM-DD HH:mm:ss.SSS}</blue></dim> <dim>│</dim> <blue>{level: <8}</blue> <dim>│</dim> {message}",
        "INFO": "<cyan>{time:YYYY-MM-DD HH:mm:ss.SSS}</cyan> <dim>│</dim> <bold><cyan>{level: <8}</cyan></bold> <dim>│</dim> {message}",
        "SUCCESS": "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> <dim>│</dim> <bold><green>{level: <8}</green></bold> <dim>│</dim> <bold>{message}</bold>",
        "WARNING": "<yellow>{time:YYYY-MM-DD HH:mm:ss.SSS}</yellow> <dim>│</dim> <bold><yellow>{level: <8}</yellow></bold> <dim>│</dim> <yellow>{message}</yellow>",
        "ERROR": "<red>{time:YYYY-MM-DD HH:mm:ss.SSS}</red> <dim>│</dim> <bold><red>{level: <8}</red></bold> <dim>│</dim> <red>{message}</red>",
        "CRITICAL": "<bold><red>{time:YYYY-MM-DD HH:mm:ss.SSS}</red></bold> <dim>│</dim> <bold><red><u>{level: <8}</u></red></bold> <dim>│</dim> <bold><red>{message}</red></bold>",
    }

    # Add handler with custom format function
    def format_record(record):
        level_name = record["level"].name
        if level_name in level_formats:
            return level_formats[level_name] + "\n{exception}"
        # Fallback for unknown levels
        return "<cyan>{time:YYYY-MM-DD HH:mm:ss.SSS}</cyan> <dim>│</dim> <bold>{level: <8}</bold> <dim>│</dim> {message}\n{exception}"

    logger.add(
        sys.stderr,
        format=format_record,
        level="DEBUG",
        colorize=True,  # Enable ANSI colors
    )
