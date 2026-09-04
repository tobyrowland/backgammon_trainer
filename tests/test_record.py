"""Parsing gnubg's match record.

The X/O mapping test is the important one here.  gnubg's match-info names do
not reliably follow `set player N name`, so identity is carried only by the
X/O token -- and reading it backwards would silently attribute every one of
the human's errors to the bot, producing a coaching report about mistakes
the player never made.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bgcoach.record import (BLUNDER, HUMAN_TOKEN, build_decisions, classify_skill,
                            contact, cube_actions, match_meta, on_bar, phase_of)


def _move_action(player, dice, move, moves, imove, board="B", luck=0.0):
    return {
        "action": "move", "player": player, "dice": dice, "move": move,
        "board": board,
        "analysis": {"moves": moves, "imove": imove, "luck-value": luck},
    }


def _cand(move, score):
    return {"type": "eval", "move": move, "score": score,
            "probs": [0.5, 0.1, 0.0, 0.1, 0.0]}


def test_player_zero_is_x():
    assert HUMAN_TOKEN[0] == "X"
    assert HUMAN_TOKEN[1] == "O"


def test_human_attribution_follows_the_token():
    match = {"games": [{"info": {}, "game": [
        _move_action("X", (3, 1), ((8, 5), (6, 5)), [_cand(((8, 5), (6, 5)), 0.1)], 0),
        _move_action("O", (6, 5), ((24, 18), (18, 13)), [_cand(((24, 18), (18, 13)), 0.2)], 0),
    ]}]}
    as_x = build_decisions(match, human_index=0)
    assert [d.is_human for d in as_x] == [True, False]
    as_o = build_decisions(match, human_index=1)
    assert [d.is_human for d in as_o] == [False, True]


def test_error_is_best_minus_played():
    moves = [_cand(((8, 5), (6, 5)), 0.100), _cand(((13, 10), (13, 11)), -0.050)]
    match = {"games": [{"info": {}, "game": [
        _move_action("X", (3, 1), ((13, 10), (13, 11)), moves, 1)]}]}
    d = build_decisions(match, 0)[0]
    assert d.rank == 1
    assert d.error == pytest.approx(0.150)
    assert d.skill == "blunder"
    assert d.played == "13/10 13/11"
    assert d.best == "8/5 6/5"


def test_playing_the_best_move_costs_nothing():
    moves = [_cand(((8, 5), (6, 5)), 0.1), _cand(((13, 11),), 0.0)]
    match = {"games": [{"info": {}, "game": [
        _move_action("X", (3, 1), ((8, 5), (6, 5)), moves, 0)]}]}
    d = build_decisions(match, 0)[0]
    assert d.error == 0.0 and d.skill == "ok" and d.rank == 0


def test_error_never_goes_negative():
    """Pruned evaluations can round a played move above the list head."""
    moves = [_cand(((8, 5),), 0.10), _cand(((6, 5),), 0.11)]
    match = {"games": [{"info": {}, "game": [
        _move_action("X", (3, 1), ((6, 5),), moves, 1)]}]}
    assert build_decisions(match, 0)[0].error == 0.0


def test_infinite_luck_is_treated_as_zero():
    """gnubg writes -Infinity for luck it could not compute."""
    match = {"games": [{"info": {}, "game": [
        _move_action("X", (3, 1), ((8, 5),), [_cand(((8, 5),), 0.1)], 0,
                     luck=float("-inf"))]}]}
    assert build_decisions(match, 0)[0].luck == 0.0


# ------------------------------------------------------------------ the cube

def test_double_is_worth_the_worse_of_take_and_pass():
    """The opponent picks their best reply, so the doubler gets the worse one."""
    assert cube_actions(0.4, 0.5)["double"] == pytest.approx(0.5)
    # dt above 1.0 means the opponent would pass, capping the double at +1
    assert cube_actions(0.4, 1.6)["double"] == pytest.approx(1.0)


def test_missed_double_is_recorded_from_a_move_action():
    """Rolling on is an implicit no-double, and gnubg attaches the cube
    equities to the move -- so the decision is recoverable."""
    action = _move_action("X", (3, 1), ((8, 5),), [_cand(((8, 5),), 0.1)], 0)
    action["analysis"]["nd-cubeful-eq"] = 0.500
    action["analysis"]["dt-cubeful-eq"] = 0.700
    decisions = build_decisions({"games": [{"info": {}, "game": [action]}]}, 0)
    cube = [d for d in decisions if d.kind == "cube"]
    assert len(cube) == 1
    assert cube[0].played == "no double" and cube[0].best == "double"
    assert cube[0].error == pytest.approx(0.200)


def test_correct_no_double_is_not_a_decision():
    """Positions where rolling on is right must not be counted, or the error
    rate is diluted towards zero by thousands of non-decisions."""
    action = _move_action("X", (3, 1), ((8, 5),), [_cand(((8, 5),), 0.1)], 0)
    action["analysis"]["nd-cubeful-eq"] = 0.500
    action["analysis"]["dt-cubeful-eq"] = 0.300
    decisions = build_decisions({"games": [{"info": {}, "game": [action]}]}, 0)
    assert [d for d in decisions if d.kind == "cube"] == []


def test_take_is_judged_from_the_doublers_numbers():
    """gnubg records no analysis on a take; it lives on the double."""
    double = {"action": "double", "player": "O", "board": "B",
              "analysis": {"nd-cubeful-eq": 0.4, "dt-cubeful-eq": 1.3}}
    take = {"action": "take", "player": "X", "board": "B"}
    decisions = build_decisions({"games": [{"info": {}, "game": [double, take]}]}, 0)
    reply = [d for d in decisions if d.kind == "take"][0]
    # dt 1.3 for the doubler means taking is worth -1.3 to us; passing -1.0.
    assert reply.best == "pass"
    assert reply.error == pytest.approx(0.3)


def test_pass_when_take_was_right_is_an_error():
    double = {"action": "double", "player": "O", "board": "B",
              "analysis": {"nd-cubeful-eq": 0.4, "dt-cubeful-eq": 0.6}}
    drop = {"action": "drop", "player": "X", "board": "B"}
    decisions = build_decisions({"games": [{"info": {}, "game": [double, drop]}]}, 0)
    reply = [d for d in decisions if d.kind == "take"][0]
    assert reply.best == "take"
    assert reply.error == pytest.approx(0.4)


# ----------------------------------------------------------------- geometry

def _empty():
    return [[0] * 25, [0] * 25]


def test_contact_and_phases():
    start = _empty()
    for side in start:
        side[5], side[7], side[12], side[23] = 5, 3, 5, 2
    assert contact(start) is True
    assert phase_of(start, 1) == "opening"
    assert phase_of(start, 20) == "middle game"

    raced = _empty()
    raced[0][9] = 15
    raced[1][9] = 15          # backmost 10 + 10 < 25, they have passed
    assert contact(raced) is False
    assert phase_of(raced, 30) == "race"

    home = _empty()
    home[0][1] = 15
    home[1][2] = 15
    assert phase_of(home, 40) == "bearoff"


def test_back_game_needs_two_deep_anchors():
    board = _empty()
    board[1][22] = 2          # 23 point
    board[1][23] = 2          # 24 point
    board[1][5] = 11
    board[0][5] = 15
    assert phase_of(board, 20) == "back game"


def test_on_bar_is_a_tag_not_a_phase():
    board = _empty()
    board[1][24] = 1
    board[1][5] = 14
    board[0][5] = 15
    assert on_bar(board) is True
    assert phase_of(board, 20) != "on the bar"


def test_skill_thresholds():
    assert classify_skill(BLUNDER) == "blunder"
    assert classify_skill(0.05) == "error"
    assert classify_skill(0.03) == "doubtful"
    assert classify_skill(0.001) == "ok"


def test_final_score_comes_from_games_won_and_is_capped():
    """The last game's info holds the score going *into* it, and a gammon can
    be worth more than the points still needed."""
    match = {"match-info": {"match-length": 3},
             "games": [{"info": {"score-X": 0, "score-O": 0,
                                 "winner": "O", "points-won": 4}, "game": []}]}
    meta = match_meta(match, human_index=0)
    assert meta["score_human"] == 0
    assert meta["score_bot"] == 3        # capped at the match length, not 4
    assert meta["games"] == 1
