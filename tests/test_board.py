"""Board geometry and move notation."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bgcoach.board import absolute, pip_counts, render, TOP
from bgcoach.notation import format_dice, format_move


def _start_side():
    side = [0] * 25
    side[5], side[7], side[12], side[23] = 5, 3, 5, 2
    return side


def _start_board():
    return [_start_side(), _start_side()]


def test_pip_counts_at_the_start_are_167_each():
    assert pip_counts(_start_board(), turn=0) == (167, 167)


def test_board_index_one_is_the_player_on_roll():
    """gnubg returns (opponent, on-roll).  Getting this backwards silently
    swaps the two players in every reading of the position."""
    board = [_start_side(), _start_side()]
    board[1][23] = 1          # the on-roll player has moved one chequel off the 24
    board[1][20] = 1
    human_pips, bot_pips = pip_counts(board, turn=0, human=0)
    assert human_pips == 164 and bot_pips == 167
    # When it is the bot's turn, index 1 is the bot instead.
    human_pips, bot_pips = pip_counts(board, turn=1, human=0)
    assert human_pips == 167 and bot_pips == 164


def test_absolute_frame_mirrors_the_opponent():
    """The two players count in opposite directions: my 24 is their 1."""
    abs_ = absolute(_start_board(), turn=0, human=0)
    pts = abs_["points"]
    assert pts[24] == 2       # my two back chequers
    assert pts[1] == -2       # their two, on my 1-point
    assert pts[13] == 5 and pts[12] == -5
    assert pts[6] == 5 and pts[19] == -5
    assert sum(n for n in pts if n > 0) == 15
    assert sum(-n for n in pts if n < 0) == 15


def test_borne_off_chequers_are_counted():
    board = [_start_side(), [0] * 25]
    board[1][0] = 10          # ten on the ace point, five already off
    abs_ = absolute(board, turn=0, human=0)
    assert abs_["human_off"] == 5
    assert abs_["bot_off"] == 0


def test_render_aligns_with_its_header():
    out = render(_start_board(), turn=0, score=(0, 0), match_to=5)
    body = [l for l in out.splitlines() if l.startswith(" |")]
    for line in body:
        # strip the annotation column that follows the final pipe
        drawn = line[:line.rindex("|") + 1]
        assert len(drawn) == len(TOP), repr(drawn)


def test_notation():
    assert format_move([[25, 20], [24, 18]]) == "bar/20 24/18"
    assert format_move([[13, 11], [13, 11]]) == "13/11(2)"
    assert format_move([[24, 18], [18, 13]]) == "24/18/13"          # one chequer
    assert format_move([[6, 0], [6, 0], [5, 0], [5, 0]]) == "6/off(2) 5/off(2)"
    assert format_move([]) == "(no play)"
    assert format_dice((6, 5)) == "65"
    assert format_dice((0, 0)) == "--"
