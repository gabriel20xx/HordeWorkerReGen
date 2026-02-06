"""Utilities for configuring the logger with a standardized format."""

import os
import sys

from loguru import logger


def create_level_format_function(time_format: str = "YYYY-MM-DD HH:mm:ss.SSS"):
    """Create a format function for log messages with consistent coloring.
    
    This function creates a format function that can be used with loguru logger.add()
    to format log messages with consistent coloring based on log level.
    
    Args:
        time_format: The format string for the timestamp. Defaults to "YYYY-MM-DD HH:mm:ss.SSS".
                    Can be customized, e.g., "HH:mm:ss" for shorter timestamps.
    
    Returns:
        A format function that can be passed to logger.add(format=...)
    
    Note: The timestamp is never colored to ensure it's always clearly visible and
    easy to parse. Only the level and message are colored based on log level.
    """
    # Define custom level colors for better visual distinction
    # Note: Timestamp is never colored to ensure it's always clearly visible
    level_formats = {
        "TRACE": f"{{time:{time_format}}} <dim>|</dim> <dim><cyan>{{level: <8}}</cyan></dim> <dim>|</dim> <dim>{{message}}</dim>",
        "DEBUG": f"{{time:{time_format}}} <dim>|</dim> <blue>{{level: <8}}</blue> <dim>|</dim> {{message}}",
        "INFO": f"{{time:{time_format}}} <dim>|</dim> <bold><cyan>{{level: <8}}</cyan></bold> <dim>|</dim> {{message}}",
        "SUCCESS": f"{{time:{time_format}}} <dim>|</dim> <bold><green>{{level: <8}}</green></bold> <dim>|</dim> <bold><green>{{message}}</green></bold>",
        "WARNING": f"{{time:{time_format}}} <dim>|</dim> <bold><yellow>{{level: <8}}</yellow></bold> <dim>|</dim> <yellow>{{message}}</yellow>",
        "ERROR": f"{{time:{time_format}}} <dim>|</dim> <bold><red>{{level: <8}}</red></bold> <dim>|</dim> <red>{{message}}</red>",
        "CRITICAL": f"{{time:{time_format}}} <dim>|</dim> <bold><red><u>{{level: <8}}</u></red></bold> <dim>|</dim> <bold><red>{{message}}</red></bold>",
    }

    def format_record(record):
        level_name = record["level"].name
        if level_name in level_formats:
            return level_formats[level_name] + "\n{exception}"
        # Fallback for unknown levels (timestamp is never colored)
        return f"{{time:{time_format}}} <dim>|</dim> <bold>{{level: <8}}</bold> <dim>|</dim> {{message}}\n{{exception}}"

    return format_record


def configure_logger_format() -> None:
    """Configure the logger with a standardized format: timestamp | level | message.

    This should be called after HordeLog.initialise() to override the default format
    with a consistent pattern across all processes with enhanced colors.

    Format: {time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}
    
    Note: The timestamp is never colored to ensure it's always clearly visible and
    easy to parse. Only the level and message are colored based on log level.

    Example output:
        2026-02-04 21:44:03.123 | INFO     | Worker starting...
        2026-02-04 21:44:05.456 | SUCCESS  | Job completed successfully
        2026-02-04 21:44:06.789 | ERROR    | Job failed with error
    
    Environment Variables:
        AIWORKER_LOG_LEVEL: Set log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                           Default: INFO
        AIWORKER_DEBUG: Legacy flag to enable DEBUG (set to 1/true/yes)
    """
    # Remove all handlers added by HordeLog
    logger.remove()

    # Determine the appropriate log level from environment variables
    # Default to INFO to reduce clutter (DEBUG is too verbose for normal operation)
    log_level = os.getenv("AIWORKER_LOG_LEVEL", "INFO").upper()
    
    # Validate log level
    valid_levels = ["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
    if log_level not in valid_levels:
        print(f"Warning: Invalid AIWORKER_LOG_LEVEL '{log_level}', defaulting to INFO")
        log_level = "INFO"
    
    # Legacy support: AIWORKER_DEBUG=1 enables DEBUG level
    if os.getenv("AIWORKER_DEBUG", "").lower() in ("1", "true", "yes"):
        log_level = "DEBUG"
    
    # Use the shared format function for consistent coloring
    format_record = create_level_format_function(time_format="YYYY-MM-DD HH:mm:ss.SSS")

    logger.add(
        sys.stderr,
        format=format_record,
        level=log_level,
        colorize=True,  # Enable ANSI colors
    )
    
    # Log the configured level for clarity (only if not INFO)
    if log_level != "INFO":
        logger.info(f"Console log level set to: {log_level}")
