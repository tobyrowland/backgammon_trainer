"""Analysing a match that the engine currently holds."""

from .analysis import summarise
from .record import build_decisions, match_meta


def analyse(engine, human_index=0, reanalyse=True):
    """Full-strength analysis of the match loaded in the engine.

    During play gnubg prunes the also-rans to a 0-ply evaluation, which is
    enough to pick a move but too coarse to tell a player what a mistake
    cost.  Re-analysing first is what makes the numbers trustworthy.
    """
    match = engine.match(analyse=reanalyse)

    ids = []
    for game in match.get("games") or []:
        for action in game.get("game") or []:
            if action.get("board"):
                ids.append(action["board"])
    boards = {}
    if ids:
        decoded = engine.decode(list(dict.fromkeys(ids)))
        boards = {k: v for k, v in decoded.items() if v}

    decisions = build_decisions(match, human_index=human_index, boards=boards)
    summary = summarise(decisions, match_meta(match, human_index=human_index))
    return decisions, summary
