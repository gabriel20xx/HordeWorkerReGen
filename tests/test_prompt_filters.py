"""Tests for the prompt-filter helper used to rewrite prompts before local inference."""

from horde_worker_regen.process_management.process_manager import _apply_conditional_add, _apply_prompt_filters


def test_replace_matches_whole_words_only() -> None:
    """A replace rule must only match standalone words, not substrings of larger words."""
    result = _apply_prompt_filters("a cat in the category, scatter", replace=["cat==>dog"])
    assert result == "a dog in the category, scatter"


def test_replace_is_case_insensitive() -> None:
    """A replace rule matches regardless of the casing of the prompt text."""
    result = _apply_prompt_filters("CAT Cat cat", replace=["cat==>dog"])
    assert result == "dog dog dog"


def test_replace_inserts_replacement_literally() -> None:
    """Backslash/group-reference characters in the replacement are inserted literally."""
    result = _apply_prompt_filters("cat", replace=[r"cat==>x\1y"])
    assert result == r"x\1y"


def test_replace_supports_multi_word_find() -> None:
    """A multi-word find term is matched as a whole phrase."""
    result = _apply_prompt_filters("a big cat here", replace=["big cat==>tiny dog"])
    assert result == "a tiny dog here"


def test_replace_with_empty_removes_the_word() -> None:
    """An empty replacement deletes the matched whole word."""
    result = _apply_prompt_filters("blurry lowres art", replace=["lowres==>"])
    assert result == "blurry  art"


def test_replace_rules_without_separator_are_skipped() -> None:
    """Entries lacking the ``==>`` separator are ignored."""
    result = _apply_prompt_filters("cat", replace=["no-separator-here"])
    assert result == "cat"


# ── Conditional Add ──────────────────────────────────────────────────────────


def test_conditional_add_appends_when_trigger_present() -> None:
    """The add string is appended when the trigger is found in the text."""
    result = _apply_conditional_add("a cat sat here", ["cat==>high quality"])
    assert result == "a cat sat here, high quality"


def test_conditional_add_does_nothing_when_trigger_absent() -> None:
    """Nothing is appended when the trigger does not appear in the text."""
    result = _apply_conditional_add("a dog sat here", ["cat==>high quality"])
    assert result == "a dog sat here"


def test_conditional_add_is_case_insensitive() -> None:
    """Trigger matching is case-insensitive."""
    result = _apply_conditional_add("A CAT sat here", ["cat==>high quality"])
    assert result == "A CAT sat here, high quality"


def test_conditional_add_skips_entries_without_separator() -> None:
    """Entries lacking the ``==>`` separator are ignored."""
    result = _apply_conditional_add("a cat sat here", ["no-separator"])
    assert result == "a cat sat here"


def test_conditional_add_skips_entries_with_empty_trigger() -> None:
    """Entries with an empty trigger part are ignored."""
    result = _apply_conditional_add("a cat sat here", ["==>high quality"])
    assert result == "a cat sat here"


def test_conditional_add_skips_entries_with_empty_add() -> None:
    """Entries with an empty add part are ignored."""
    result = _apply_conditional_add("a cat sat here", ["cat==>"])
    assert result == "a cat sat here"


def test_conditional_add_multiple_rules_independent() -> None:
    """Each rule is evaluated against the current text independently; all matching rules fire."""
    result = _apply_conditional_add("cat dog", ["cat==>feline", "dog==>canine"])
    assert result == "cat dog, feline, canine"


def test_conditional_add_without_separator() -> None:
    """When append_separator is False the add string is concatenated directly."""
    result = _apply_conditional_add("cat", ["cat==> and dog"], append_separator=False)
    assert result == "cat and dog"
