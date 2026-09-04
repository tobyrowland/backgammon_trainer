"""The coaching layer's prompt and its behaviour without credentials."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bgcoach.coach import MODEL, SYSTEM, CoachUnavailable, build_prompt, coach


def test_prompt_carries_the_brief_and_the_question():
    prompt = build_prompt("PR 12.0 over 30 decisions", question="was my cube ok?",
                          history="older matches here")
    assert "PR 12.0 over 30 decisions" in prompt
    assert "was my cube ok?" in prompt
    assert "older matches here" in prompt


def test_prompt_omits_absent_sections():
    prompt = build_prompt("brief only")
    assert "brief only" in prompt
    assert "I also want to know specifically" not in prompt


def test_system_prompt_forbids_inventing_numbers():
    """The one rule that makes the split trustworthy: the model explains the
    engine's numbers, it never produces its own."""
    assert "NEVER invent" in SYSTEM
    assert "NEVER claim a move is right or wrong against the engine" in SYSTEM


def test_model_is_current():
    assert MODEL == "claude-opus-5"


def test_missing_credentials_degrade_rather_than_crash(monkeypatch):
    """A player without an API key must still get the engine analysis."""
    import anthropic

    def explode(*args, **kwargs):
        raise anthropic.AuthenticationError(
            "no key", response=None, body=None)

    monkeypatch.setattr(anthropic, "Anthropic", explode)
    with pytest.raises(CoachUnavailable):
        coach("some brief")
