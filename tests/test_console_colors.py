"""Tests verifying that the webui console output matches the normal terminal console.

Verifies:
- The loguru ANSI escape sequences produced for each log level.
- A Python simulation of ansiToHtml matches the expected CSS styles per level.
"""

import re

import pytest
from loguru import logger

from horde_worker_regen.logger_config import create_level_format_function


# ---------------------------------------------------------------------------
# Helpers – Python port of the JS ansiToHtml() function in server.py so we
# can write pure-Python assertions without spawning a browser.
# ---------------------------------------------------------------------------

# Foreground color mapping – must stay in sync with server.py
ANSI_COLORS: dict[str, str] = {
    "30": "#000000",
    "31": "#cd3131",
    "32": "#0dbc79",
    "33": "#e5e510",
    "34": "#2472c8",
    "35": "#bc3fbc",
    "36": "#11a8cd",
    "37": "#e5e5e5",
    "90": "#666666",
    "91": "#f14c4c",
    "92": "#23d18b",
    "93": "#f5f543",
    "94": "#3b8eea",
    "95": "#d670d6",
    "96": "#29b8db",
    "97": "#ffffff",
}

# Background color mapping – must stay in sync with server.py
ANSI_BG_COLORS: dict[str, str] = {
    "40": "#000000",
    "41": "#cd3131",
    "42": "#0dbc79",
    "43": "#e5e510",
    "44": "#2472c8",
    "45": "#bc3fbc",
    "46": "#11a8cd",
    "47": "#e5e5e5",
    "100": "#666666",
    "101": "#f14c4c",
    "102": "#23d18b",
    "103": "#f5f543",
    "104": "#3b8eea",
    "105": "#d670d6",
    "106": "#29b8db",
    "107": "#ffffff",
}

_ANSI_RE = re.compile(r"\x1b\[([0-9;]+)m")


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ansi_to_html(text: str) -> str:
    """Python port of the ansiToHtml() JavaScript function in server.py."""
    text = _escape_html(text)

    result = ""
    current_styles: list[str] = []
    parts = _ANSI_RE.split(text)

    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Regular text
            if current_styles:
                result += '<span style="' + ";".join(current_styles) + '">' + part + "</span>"
            else:
                result += part
        else:
            # ANSI code(s)
            for code in part.split(";"):
                if code in ("0", ""):
                    current_styles = []
                elif code == "1":
                    current_styles = [s for s in current_styles if not s.startswith("font-weight:")]
                    current_styles.append("font-weight:bold")
                elif code == "2":
                    # Dim cancels bold per ANSI spec
                    current_styles = [
                        s for s in current_styles if not s.startswith("font-weight:") and not s.startswith("opacity:")
                    ]
                    current_styles.append("opacity:0.5")
                elif code == "22":
                    current_styles = [
                        s for s in current_styles if not s.startswith("font-weight:") and not s.startswith("opacity:")
                    ]
                elif code == "3":
                    current_styles = [s for s in current_styles if not s.startswith("font-style:")]
                    current_styles.append("font-style:italic")
                elif code == "23":
                    current_styles = [s for s in current_styles if not s.startswith("font-style:")]
                elif code == "4":
                    current_styles = [s for s in current_styles if not s.startswith("text-decoration:")]
                    current_styles.append("text-decoration:underline")
                elif code == "24":
                    current_styles = [s for s in current_styles if not s.startswith("text-decoration:")]
                elif code == "39":
                    current_styles = [s for s in current_styles if not s.startswith("color:")]
                elif code == "49":
                    current_styles = [s for s in current_styles if not s.startswith("background-color:")]
                elif code in ANSI_COLORS:
                    current_styles = [s for s in current_styles if not s.startswith("color:")]
                    current_styles.append("color:" + ANSI_COLORS[code])
                elif code in ANSI_BG_COLORS:
                    current_styles = [s for s in current_styles if not s.startswith("background-color:")]
                    current_styles.append("background-color:" + ANSI_BG_COLORS[code])

    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _capture_logs_for_level(level_name: str, message: str = "Test message") -> str:
    """Return the ANSI-encoded log line that loguru produces for a given level."""
    captured: list[str] = []

    def _sink(msg: object) -> None:
        captured.append(str(msg))

    fmt = create_level_format_function(time_format="HH:mm:ss")
    handler_id = logger.add(_sink, format=fmt, colorize=True, level="TRACE")
    try:
        level_map = {
            "TRACE": logger.trace,
            "DEBUG": logger.debug,
            "INFO": logger.info,
            "SUCCESS": logger.success,
            "WARNING": logger.warning,
            "ERROR": logger.error,
            "CRITICAL": logger.critical,
        }
        level_map[level_name](message)
    finally:
        logger.remove(handler_id)

    return captured[0].rstrip("\n") if captured else ""


# ---------------------------------------------------------------------------
# Tests: ANSI sequences produced by loguru match expected codes
# ---------------------------------------------------------------------------


def test_info_ansi_sequences() -> None:
    """INFO level must produce bold + cyan (ANSI 1 then 36) for the level word."""
    log = _capture_logs_for_level("INFO")
    seqs = re.findall(r"\x1b\[([0-9;]+)m", log)
    # Bold (1) and cyan (36) must both appear, in that order
    assert "1" in seqs, "INFO level should use bold (ANSI 1)"
    assert "36" in seqs, "INFO level should use cyan (ANSI 36)"
    assert seqs.index("1") < seqs.index("36"), "bold must precede cyan for INFO"


def test_success_ansi_sequences() -> None:
    """SUCCESS level must produce bold + green (ANSI 1 then 32) for the level word
    and green (ANSI 32) for the message text."""
    log = _capture_logs_for_level("SUCCESS")
    seqs = re.findall(r"\x1b\[([0-9;]+)m", log)
    assert "1" in seqs, "SUCCESS level should use bold (ANSI 1)"
    assert "32" in seqs, "SUCCESS level should use green (ANSI 32)"
    # Green should appear at least twice: once for the level, once for the message
    assert seqs.count("32") >= 2, "SUCCESS should apply green to both level and message"


def test_warning_ansi_sequences() -> None:
    """WARNING level must produce bold + yellow (ANSI 1 then 33)."""
    log = _capture_logs_for_level("WARNING")
    seqs = re.findall(r"\x1b\[([0-9;]+)m", log)
    assert "1" in seqs, "WARNING level should use bold (ANSI 1)"
    assert "33" in seqs, "WARNING level should use yellow (ANSI 33)"


def test_error_ansi_sequences() -> None:
    """ERROR level must produce bold + red (ANSI 1 then 31)."""
    log = _capture_logs_for_level("ERROR")
    seqs = re.findall(r"\x1b\[([0-9;]+)m", log)
    assert "1" in seqs, "ERROR level should use bold (ANSI 1)"
    assert "31" in seqs, "ERROR level should use red (ANSI 31)"


def test_critical_ansi_sequences() -> None:
    """CRITICAL level must produce bold + red + underline (ANSI 1, 31, 4)."""
    log = _capture_logs_for_level("CRITICAL")
    seqs = re.findall(r"\x1b\[([0-9;]+)m", log)
    assert "1" in seqs, "CRITICAL level should use bold (ANSI 1)"
    assert "31" in seqs, "CRITICAL level should use red (ANSI 31)"
    assert "4" in seqs, "CRITICAL level should use underline (ANSI 4)"


def test_debug_ansi_sequences() -> None:
    """DEBUG level must use plain blue (ANSI 34) with no bold."""
    log = _capture_logs_for_level("DEBUG")
    seqs = re.findall(r"\x1b\[([0-9;]+)m", log)
    assert "34" in seqs, "DEBUG level should use blue (ANSI 34)"


def test_trace_ansi_sequences() -> None:
    """TRACE level must use dim (ANSI 2) and cyan (ANSI 36) for the level word
    and dim (ANSI 2) for the message."""
    log = _capture_logs_for_level("TRACE")
    seqs = re.findall(r"\x1b\[([0-9;]+)m", log)
    assert "2" in seqs, "TRACE level should use dim (ANSI 2)"
    assert "36" in seqs, "TRACE level should use cyan (ANSI 36)"


# ---------------------------------------------------------------------------
# Tests: HTML rendering from ansi_to_html() matches expected CSS
# ---------------------------------------------------------------------------


def _styles_for_text(html: str, substring: str) -> list[str]:
    """Return the list of CSS styles applied to the first span that contains *substring*.

    If *substring* is found outside any span, returns an empty list.
    """
    # Find all <span style="...">content</span> blocks
    for m in re.finditer(r'<span style="([^"]*)">(.*?)</span>', html):
        styles_str, content = m.group(1), m.group(2)
        if substring in content:
            return [s.strip() for s in styles_str.split(";") if s.strip()]
    return []


def test_html_info_level_is_bold_cyan() -> None:
    """The INFO level word in the rendered HTML must be bold and cyan."""
    log = _capture_logs_for_level("INFO")
    html = ansi_to_html(log)
    styles = _styles_for_text(html, "INFO")
    assert "font-weight:bold" in styles, f"INFO level should be bold; got styles={styles}"
    assert "color:#11a8cd" in styles, f"INFO level should be cyan (#11a8cd); got styles={styles}"
    # Message text must NOT be bold or colored
    msg_styles = _styles_for_text(html, "Test message")
    assert "font-weight:bold" not in msg_styles, "INFO message should not be bold"
    assert not any(s.startswith("color:") for s in msg_styles), "INFO message should have no foreground color"


def test_html_success_level_is_bold_green() -> None:
    """The SUCCESS level word must be bold+green; the message must be plain green."""
    log = _capture_logs_for_level("SUCCESS")
    html = ansi_to_html(log)
    level_styles = _styles_for_text(html, "SUCCESS")
    assert "font-weight:bold" in level_styles, f"SUCCESS level should be bold; got {level_styles}"
    assert "color:#0dbc79" in level_styles, f"SUCCESS level should be green (#0dbc79); got {level_styles}"
    msg_styles = _styles_for_text(html, "Test message")
    assert "color:#0dbc79" in msg_styles, f"SUCCESS message should be green; got {msg_styles}"
    assert "font-weight:bold" not in msg_styles, "SUCCESS message should not be bold"


def test_html_warning_level_is_bold_yellow() -> None:
    """The WARNING level word must be bold+yellow."""
    log = _capture_logs_for_level("WARNING")
    html = ansi_to_html(log)
    styles = _styles_for_text(html, "WARNING")
    assert "font-weight:bold" in styles, f"WARNING level should be bold; got {styles}"
    assert "color:#e5e510" in styles, f"WARNING level should be yellow (#e5e510); got {styles}"


def test_html_error_level_is_bold_red() -> None:
    """The ERROR level word must be bold+red."""
    log = _capture_logs_for_level("ERROR")
    html = ansi_to_html(log)
    styles = _styles_for_text(html, "ERROR")
    assert "font-weight:bold" in styles, f"ERROR level should be bold; got {styles}"
    assert "color:#cd3131" in styles, f"ERROR level should be red (#cd3131); got {styles}"


def test_html_critical_level_is_bold_red_underlined() -> None:
    """The CRITICAL level word must be bold, red, and underlined."""
    log = _capture_logs_for_level("CRITICAL")
    html = ansi_to_html(log)
    styles = _styles_for_text(html, "CRITICAL")
    assert "font-weight:bold" in styles, f"CRITICAL level should be bold; got {styles}"
    assert "color:#cd3131" in styles, f"CRITICAL level should be red (#cd3131); got {styles}"
    assert "text-decoration:underline" in styles, f"CRITICAL level should be underlined; got {styles}"


def test_html_debug_level_is_plain_blue() -> None:
    """The DEBUG level word must be plain blue (no bold)."""
    log = _capture_logs_for_level("DEBUG")
    html = ansi_to_html(log)
    styles = _styles_for_text(html, "DEBUG")
    assert "color:#2472c8" in styles, f"DEBUG level should be blue (#2472c8); got {styles}"
    assert "font-weight:bold" not in styles, f"DEBUG level should NOT be bold; got {styles}"


def test_html_trace_level_is_dim_cyan() -> None:
    """The TRACE level word must be dim and cyan."""
    log = _capture_logs_for_level("TRACE")
    html = ansi_to_html(log)
    styles = _styles_for_text(html, "TRACE")
    assert "opacity:0.5" in styles, f"TRACE level should be dim (opacity:0.5); got {styles}"
    assert "color:#11a8cd" in styles, f"TRACE level should be cyan (#11a8cd); got {styles}"


# ---------------------------------------------------------------------------
# Tests: ANSI code semantics (dim cancels bold, reset codes)
# ---------------------------------------------------------------------------


def test_dim_cancels_bold() -> None:
    """Per ANSI spec, dim (code 2) must cancel bold (code 1) in the rendered HTML."""
    # Build a string: bold, then dim (dim should win)
    ansi_text = "\x1b[1m\x1b[2mtext\x1b[0m"
    html = ansi_to_html(ansi_text)
    styles = _styles_for_text(html, "text")
    assert "opacity:0.5" in styles, "Dim should be applied when both bold+dim are set"
    assert "font-weight:bold" not in styles, "Bold should be cancelled by dim"


def test_bold_is_not_double_applied() -> None:
    """Applying bold twice must not corrupt the styles list."""
    ansi_text = "\x1b[1m\x1b[1mtext\x1b[0m"
    html = ansi_to_html(ansi_text)
    styles = _styles_for_text(html, "text")
    assert styles.count("font-weight:bold") == 1, "Bold must appear exactly once"


def test_code_22_resets_bold_and_dim() -> None:
    """ANSI code 22 (normal intensity) removes both bold and dim."""
    ansi_text = "\x1b[1m\x1b[22mtext\x1b[0m"
    html = ansi_to_html(ansi_text)
    styles = _styles_for_text(html, "text")
    assert "font-weight:bold" not in styles, "Code 22 should remove bold"

    ansi_text2 = "\x1b[2m\x1b[22mtext\x1b[0m"
    html2 = ansi_to_html(ansi_text2)
    styles2 = _styles_for_text(html2, "text")
    assert "opacity:0.5" not in styles2, "Code 22 should remove dim"


def test_code_39_resets_foreground_color() -> None:
    """ANSI code 39 (default foreground) must remove any set foreground color."""
    ansi_text = "\x1b[31m\x1b[39mtext\x1b[0m"
    html = ansi_to_html(ansi_text)
    styles = _styles_for_text(html, "text")
    assert not any(s.startswith("color:") for s in styles), "Code 39 should reset foreground color"


def test_code_24_resets_underline() -> None:
    """ANSI code 24 (not underlined) must remove underline."""
    ansi_text = "\x1b[4m\x1b[24mtext\x1b[0m"
    html = ansi_to_html(ansi_text)
    styles = _styles_for_text(html, "text")
    assert "text-decoration:underline" not in styles, "Code 24 should remove underline"


def test_full_reset_clears_all_styles() -> None:
    """ANSI code 0 (reset) must clear all accumulated styles."""
    ansi_text = "\x1b[1m\x1b[31m\x1b[4m\x1b[0mtext\x1b[0m"
    html = ansi_to_html(ansi_text)
    # After reset, 'text' should be plain with no styles
    styles = _styles_for_text(html, "text")
    assert styles == [], f"After full reset, text should have no styles; got {styles}"


def test_no_xss_in_message_content() -> None:
    """HTML special characters in log messages must be escaped (XSS prevention)."""
    raw = "\x1b[32mHello <script>alert(1)</script> world\x1b[0m"
    html = ansi_to_html(raw)
    assert "<script>" not in html, "Raw <script> tag must be escaped"
    assert "&lt;script&gt;" in html, "Script tag should be HTML-escaped"
    assert "Hello" in html and "world" in html


def test_combined_escape_code_handled() -> None:
    """Combined ANSI codes like ESC[1;31m (bold+red in one sequence) must work."""
    ansi_text = "\x1b[1;31mtext\x1b[0m"
    html = ansi_to_html(ansi_text)
    styles = _styles_for_text(html, "text")
    assert "font-weight:bold" in styles, "Combined 1;31 should include bold"
    assert "color:#cd3131" in styles, "Combined 1;31 should include red"


# ---------------------------------------------------------------------------
# Integration: webui and console use the same ANSI sequences
# ---------------------------------------------------------------------------


def test_webui_and_console_use_same_ansi_sequences() -> None:
    """The webui format function (HH:mm:ss) and the console format function
    (YYYY-MM-DD HH:mm:ss.SSS) must produce identical ANSI escape sequences
    so that the webui colors exactly match the normal console."""
    fmt_short = create_level_format_function(time_format="HH:mm:ss")
    fmt_full = create_level_format_function(time_format="YYYY-MM-DD HH:mm:ss.SSS")

    for level_name in ("INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"):
        short_captured: list[str] = []
        full_captured: list[str] = []

        def _sink_short(msg: object) -> None:
            short_captured.append(str(msg))

        def _sink_full(msg: object) -> None:
            full_captured.append(str(msg))

        level_map = {
            "INFO": logger.info,
            "SUCCESS": logger.success,
            "WARNING": logger.warning,
            "ERROR": logger.error,
            "CRITICAL": logger.critical,
        }

        h1 = logger.add(_sink_short, format=fmt_short, colorize=True, level="TRACE")
        h2 = logger.add(_sink_full, format=fmt_full, colorize=True, level="TRACE")
        try:
            level_map[level_name]("Test")
        finally:
            logger.remove(h1)
            logger.remove(h2)

        short_seqs = re.findall(r"\x1b\[([0-9;]+)m", short_captured[0])
        full_seqs = re.findall(r"\x1b\[([0-9;]+)m", full_captured[0])
        assert short_seqs == full_seqs, (
            f"Level {level_name}: webui and console ANSI sequences differ.\n"
            f"  webui (short): {short_seqs}\n"
            f"  console (full): {full_seqs}"
        )
