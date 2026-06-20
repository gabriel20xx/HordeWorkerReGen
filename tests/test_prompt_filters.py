"""Tests for the prompt-filter helper used to rewrite prompts before local inference."""

from horde_worker_regen.process_management.process_manager import _apply_prompt_filters


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
