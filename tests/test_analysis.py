"""Error-rate aggregation."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bgcoach.analysis import (PR_SCALE, band, collapse_repeats, counts_as_decision,
                              format_brief, summarise)
from bgcoach.record import Decision


def mk(error=0.0, kind="checker", alternatives=5, is_human=True, game=0, ply=0,
       played="13/11", best="13/11", luck=0.0, phase="middle game"):
    return Decision(game=game, ply=ply, player="X", is_human=is_human, kind=kind,
                    dice="31", played=played, best=best, error=error,
                    skill="ok", alternatives=alternatives, luck=luck, phase=phase)


def test_bands():
    assert band(1.0) == "world class"
    assert band(4.0) == "expert"
    assert band(9.0) == "intermediate"
    assert band(40.0) == "beginner"


def test_forced_moves_are_not_decisions():
    """A move with one legal play is not a decision, and counting it would
    dilute the error rate."""
    assert counts_as_decision(mk(alternatives=1)) is False
    assert counts_as_decision(mk(alternatives=2)) is True
    assert counts_as_decision(mk(kind="cube", alternatives=0)) is True


def test_pr_is_error_rate_times_scale():
    decisions = [mk(error=0.02), mk(error=0.04), mk(error=0.0)]
    summary = summarise(decisions)
    assert summary["overall"]["decisions"] == 3
    assert summary["overall"]["equity_lost"] == pytest.approx(0.06)
    assert summary["overall"]["pr"] == pytest.approx((0.06 / 3) * PR_SCALE)


def test_forced_moves_excluded_from_the_denominator():
    decisions = [mk(error=0.06), mk(error=0.0, alternatives=1)]
    assert summarise(decisions)["overall"]["decisions"] == 1


def test_opponent_decisions_are_reported_separately():
    summary = summarise([mk(error=0.5, is_human=False), mk(error=0.0)])
    assert summary["overall"]["equity_lost"] == 0.0
    assert summary["opponent_overall"]["equity_lost"] == pytest.approx(0.5)


def test_chequer_and_cube_are_split():
    summary = summarise([mk(error=0.10), mk(error=0.30, kind="cube",
                                            played="no double", best="double")])
    assert summary["chequer"]["equity_lost"] == pytest.approx(0.10)
    assert summary["cube"]["equity_lost"] == pytest.approx(0.30)
    assert summary["missed_doubles"] == 1


def test_repeated_missed_doubles_collapse_into_one_finding():
    """Being right to double on six consecutive turns is one lesson, not six;
    listing it six times would bury everything else in the report."""
    rows = [mk(error=0.19, kind="cube", played="no double", best="double", ply=p)
            for p in (27, 29, 31, 33)]
    grouped = collapse_repeats(rows)
    assert len(grouped) == 1
    assert grouped[0]["times"] == 4
    assert grouped[0]["total_error"] == pytest.approx(0.76)


def test_separate_missed_doubles_do_not_collapse():
    rows = [mk(error=0.1, kind="cube", played="no double", best="double", ply=5),
            mk(error=0.1, kind="cube", played="no double", best="double", ply=40)]
    assert len(collapse_repeats(rows)) == 2


def test_brief_reports_luck_separately_from_skill():
    summary = summarise([mk(error=0.0, luck=-0.9)],
                        {"match_length": 5, "score_human": 2, "score_bot": 5,
                         "games": 4})
    brief = format_brief(summary)
    assert "PR 0.0" in brief
    assert "-0.900" in brief
    assert "you 2 - 5 bot" in brief
