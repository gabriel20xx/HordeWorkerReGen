"""Tests for LogConsoleRewriter to ensure it doesn't corrupt tracebacks."""

import io
import sys

import pytest
import regex as re


class LogConsoleRewriter(io.StringIO):
    """Makes the console output more readable by shortening certain strings."""

    def __init__(self, original_iostream: io.TextIOBase) -> None:
        """Initialise the rewriter."""
        self.original_iostream = original_iostream
        self.in_traceback = False  # Track if we're currently printing a traceback

        pattern = r"\[36m(\d+)"

        self.line_number_pattern = re.compile(pattern)

    def write(self, message: str) -> int:
        """Rewrite the message to make it more readable where possible."""
        # Check if this message starts or continues a traceback
        traceback_start_indicators = [
            "Traceback (most recent call last)",
            "Traceback (innermost last)",
        ]

        traceback_indicators = [
            "  File ",
            "    ^",
        ]

        error_indicators = [
            "Error:",
            "Exception:",
            "Warning:",
        ]

        # Check if we're starting a traceback
        if any(indicator in message for indicator in traceback_start_indicators):
            self.in_traceback = True

        # Check if this line is part of a traceback
        is_traceback_line = any(indicator in message for indicator in traceback_indicators)

        # Check if this is an error/exception line (likely the end of a traceback)
        is_error_line = any(indicator in message for indicator in error_indicators)

        # Reset traceback mode after an empty line (common after error messages)
        if self.in_traceback and not message.strip():
            self.in_traceback = False
        # If we're in traceback mode and hit a non-traceback line, reset
        elif self.in_traceback and message.strip() and not is_traceback_line and not is_error_line:
            # Check if this looks like an exception type (e.g., "ModuleNotFoundError:", "ValueError:")
            if ":" in message and message.strip()[0].isupper():
                # Likely an exception message, keep in traceback mode
                pass
            elif message.startswith("    "):
                # Indented code snippet in traceback, keep in traceback mode
                pass
            else:
                # Definitely not traceback anymore
                self.in_traceback = False

        # Don't modify traceback or error messages
        should_modify = not self.in_traceback and not is_traceback_line and not is_error_line

        if should_modify:
            replacements = [
                ("horde_worker_regen.process_management.process_manager", "Worker"),
                ("horde_worker_regen.", ""),
                ("receive_and_handle_process_messages", "Process"),
                ("start_inference_processes", "Starting"),
                ("_start_inference_process", "Starting"),
                ("start_inference_process", "Starting"),
                ("start_safety_process", "Safety"),
                ("start_inference", "Process"),
                ("print_status_method", "Status"),
                ("log_kudos_info", "Kudos"),
                ("submit_single_generation", "Submit"),
                ("preload_models", "Loading"),
                ("api_job_pop", "New Job"),
                ("_process_control_loop", "Control"),
                ("_bridge_data_loop", "Config"),
                ("enable_performance_mode", "Performance"),
                ("replace_hung_processes", "Recovery"),
                ("handle_job_fault", "Job Fault"),
                ("api_submit_job", "Submitting"),
                ("_end_inference_process", "Stopping"),
            ]

            for old, new in replacements:
                message = message.replace(old, new)

            replacement = ""

            message = self.line_number_pattern.sub(replacement, message)

        if self.original_iostream is None:
            raise ValueError("self.original_iostream. is None!")

        return self.original_iostream.write(message)

    def flush(self) -> None:
        """Flush the buffer to the original stdout."""
        self.original_iostream.flush()


def test_log_console_rewriter_preserves_traceback():
    """Test that LogConsoleRewriter preserves traceback information."""
    # Create a StringIO to capture output
    output = io.StringIO()
    rewriter = LogConsoleRewriter(output)

    # Simulate Python printing a traceback (multiple write calls)
    rewriter.write("Traceback (most recent call last):\n")
    rewriter.write('  File "/horde-worker-reGen/run_worker.py", line 4, in <module>\n')
    rewriter.write("    from horde_worker_regen.run_worker import init\n")
    rewriter.write("ModuleNotFoundError: No module named 'something'\n")

    result = output.getvalue()

    # Verify that the traceback is preserved correctly
    assert "Traceback (most recent call last):" in result
    assert 'File "/horde-worker-reGen/run_worker.py", line 4, in <module>' in result
    assert "from horde_worker_regen.run_worker import init" in result
    assert "ModuleNotFoundError:" in result

    # The module path should NOT be shortened in the traceback
    assert "horde_worker_regen.run_worker" in result


def test_log_console_rewriter_beautifies_normal_logs():
    """Test that LogConsoleRewriter still beautifies normal log messages."""
    output = io.StringIO()
    rewriter = LogConsoleRewriter(output)

    # Write a normal log message
    rewriter.write("INFO: horde_worker_regen.process_management.process_manager starting\n")

    result = output.getvalue()

    # Verify that the module path is shortened in normal logs
    assert "horde_worker_regen.process_management.process_manager" not in result
    assert "Worker" in result


def test_log_console_rewriter_function_replacements():
    """Test that function name replacements work correctly in normal logs."""
    output = io.StringIO()
    rewriter = LogConsoleRewriter(output)

    # Write log messages with function names
    rewriter.write("INFO: horde_worker_regen.start_inference_processes called\n")
    rewriter.write("INFO: api_job_pop returned data\n")

    result = output.getvalue()

    # Verify replacements happened
    assert "start_inference_processes" not in result
    assert "Starting" in result
    assert "api_job_pop" not in result
    assert "New Job" in result


def test_log_console_rewriter_after_traceback():
    """Test that rewriter returns to normal mode after a traceback."""
    output = io.StringIO()
    rewriter = LogConsoleRewriter(output)

    # Print a traceback
    rewriter.write("Traceback (most recent call last):\n")
    rewriter.write('  File "/test.py", line 1, in <module>\n')
    rewriter.write("    test()\n")
    rewriter.write("ValueError: Test error\n")
    rewriter.write("\n")

    # Print a normal log message after the traceback
    rewriter.write("INFO: horde_worker_regen.process_management continuing\n")

    result = output.getvalue()

    # Verify the traceback is preserved
    assert "Traceback (most recent call last):" in result
    assert "ValueError: Test error" in result

    # Verify normal log processing resumed after the traceback
    lines = result.split("\n")
    last_log_line = [line for line in lines if "process_management" in line][-1]
    assert "horde_worker_regen.process_management" not in last_log_line
    # The module name should be stripped in the normal log line
    assert "process_management" in last_log_line


if __name__ == "__main__":
    # Run the tests
    test_log_console_rewriter_preserves_traceback()
    test_log_console_rewriter_beautifies_normal_logs()
    test_log_console_rewriter_function_replacements()
    test_log_console_rewriter_after_traceback()
    print("All tests passed!")
