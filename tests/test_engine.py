"""Integration tests against a real GNU Backgammon process.

These are the tests that cannot be faked: they pin the facts about gnubg's
API that the rest of the code is built on.  Skipped when gnubg is absent.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bgcoach.engine import GnubgSession, find_gnubg
from bgcoach.record import build_decisions
from bgcoach.review import analyse

pytestmark = pytest.mark.skipif(find_gnubg() is None,
                                reason="GNU Backgammon is not installed")


@pytest.fixture(scope="module")
def engine():
    with GnubgSession() as session:
        yield session


def test_new_match_starts_from_the_real_position(engine):
    state = engine.new_match(length=5, seed=11)
    assert state["gamestate"] == "playing"
    assert state["match_to"] == 5
    assert state["cube"] == 1
    # One side has already opened, so exactly one is still on 167.
    assert 167 in (state["on_roll_pips"], state["opponent_pips"])


def test_hint_ranks_moves_by_equity(engine):
    state = engine.new_match(length=5, seed=11)
    if tuple(state["dice"]) == (0, 0):
        engine.roll()
    hint = engine.hint()
    assert hint["hinttype"] == "chequer"
    moves = hint["hint"]
    assert len(moves) > 1
    # The leading candidates are searched at 2 ply and the tail pruned to
    # 0 ply, so only the top of the list is strictly ordered.
    top = [m["equity"] for m in moves[:5]]
    assert top == sorted(top, reverse=True)
    assert moves[0]["eqdiff"] == pytest.approx(0.0)
    assert all(m["eqdiff"] <= 0 for m in moves)
    assert moves[-1]["eqdiff"] < 0


def test_player_zero_appears_as_x_in_the_record(engine):
    """The mapping the whole analysis depends on, verified against gnubg
    rather than assumed: moves submitted as player 0 must come back as X."""
    engine.new_match(length=1, seed=5)
    submitted = []
    for _ in range(3):
        state = engine.state()
        if state["gamestate"] != "playing" or state["turn"] != 0:
            break
        if tuple(state["dice"]) == (0, 0):
            engine.roll()
        hint = engine.hint()
        if hint.get("hinttype") != "chequer" or not hint["hint"]:
            break
        worst = hint["hint"][-1]["move"]      # unmistakable: rank last
        submitted.append(worst)
        engine.move(worst)

    assert submitted, "no moves were submitted"
    match = engine.match(analyse=False)
    x_moves = [a for g in match["games"] for a in g["game"]
               if a.get("player") == "X" and a.get("action") == "move"]
    assert len(x_moves) >= len(submitted)
    # Our deliberately worst moves must not be ranked best.
    ranks = [(a.get("analysis") or {}).get("imove") for a in x_moves[:len(submitted)]]
    assert any(r for r in ranks if r), "player 0's bad moves were not seen as X"


def test_a_played_match_analyses_end_to_end(engine):
    """The full chain: play, re-analyse, decode, aggregate."""
    engine.new_match(length=1, seed=17)
    for _ in range(60):
        state = engine.state()
        if state.get("match_over") or state["gamestate"] != "playing":
            break
        if state["turn"] != 0:
            break
        if state["doubled"]:
            engine.take()
            continue
        if tuple(state["dice"]) == (0, 0):
            engine.roll()
            continue
        hint = engine.hint()
        moves = hint.get("hint") or []
        if not moves:
            break
        engine.move(moves[-1]["move"])        # play badly, so there is a leak

    decisions, summary = analyse(engine, human_index=0)
    assert decisions
    human = [d for d in decisions if d.is_human]
    assert human
    assert summary["overall"]["equity_lost"] > 0, "playing the worst move must cost equity"
    assert summary["overall"]["pr"] > 0
    # Phases were decoded, not left unknown.
    assert any(d.phase != "unknown" for d in human)


def test_illegal_moves_are_refused(engine):
    engine.new_match(length=5, seed=3)
    state = engine.state()
    if tuple(state["dice"]) == (0, 0):
        engine.roll()
    # gnubg itself returns normally on an illegal move; the engine wrapper is
    # what turns it into an error, so a typo cannot pass silently.
    with pytest.raises(Exception):
        engine.move("1/2 3/4")
    assert engine.state()["gamestate"] == "playing"


def test_a_whole_match_plays_to_completion(engine):
    """The interactive loop must always terminate.

    An earlier version read "have the dice been rolled?" once from a stale
    snapshot; when that disagreed with the engine the prompt asked for a move
    forever. The prompt budget is the assertion -- a wedged loop blows it.
    """
    from bgcoach.play import Match

    transcript = []

    class Script:
        def __init__(self, eng):
            self.engine = eng
            self.calls = 0

        def __call__(self, prompt):
            self.calls += 1
            if self.calls > 400:
                return "q"
            state = self.engine.state()
            if state["doubled"]:
                return "t"
            if tuple(state["dice"]) == (0, 0):
                return ""
            moves = self.engine.hint().get("hint") or []
            return moves[min(2, len(moves) - 1)]["move"] if moves else ""

    script = Script(engine)
    match = Match(engine, length=1, level="world_class",
                  out=transcript.append, ask=script)
    match.run()

    assert script.calls < 400, "the play loop did not terminate"
    text = "\n".join(str(line) for line in transcript)
    assert "Match over" in text
    # The result must be a real score, not the pre-game 0-0 that gnubg's
    # cubeinfo still reports at the moment a game ends.
    assert "you 0 - 0 bot" not in text.split("Match over")[-1]
