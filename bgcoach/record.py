"""Normalise gnubg's match record into a flat list of decisions.

``gnubg.match()`` returns nested games of actions, each carrying its ranked
alternatives and ``imove`` -- the index of the alternative actually played.
A decision's cost is therefore exact and needs no re-derivation:

    error = score[best] - score[played]

Everything the coach says traces back to that number.  The language model is
never asked to judge a move; it is asked to explain a set of measured
mistakes.

Pure: no engine, no I/O.  gnubg's raw dict goes in, structured decisions
come out.
"""

from dataclasses import dataclass, field, asdict

from .notation import format_move, format_dice

#: gnubg labels player 0 as "X" and player 1 as "O" in the match record.
#: Verified in tests/test_record.py by forcing known moves as player 0 --
#: the names in match-info do not reliably track `set player N name`, and
#: reading this backwards would credit every human error to the bot.
HUMAN_TOKEN = {0: "X", 1: "O"}

#: gnubg's default skill thresholds, in equity.
BLUNDER = 0.08
ERROR = 0.04
DOUBTFUL = 0.02


def classify_skill(error):
    if error is None:
        return None
    if error >= BLUNDER:
        return "blunder"
    if error >= ERROR:
        return "error"
    if error >= DOUBTFUL:
        return "doubtful"
    return "ok"


@dataclass
class Decision:
    game: int
    ply: int
    player: str
    is_human: bool
    kind: str                      # "checker" | "cube" | "take"
    dice: str = "--"
    played: str = ""
    best: str = ""
    error: float = 0.0
    skill: str = "ok"
    rank: int = 0                  # 0 == played the best move
    alternatives: int = 0
    luck: float = 0.0
    position_id: str = ""
    phase: str = "unknown"
    win_prob: float = None
    equity: float = None
    on_bar: bool = False

    def as_dict(self):
        return asdict(self)


def _score(entry):
    """Cubeful equity for one candidate, from the mover's point of view."""
    if entry is None:
        return None
    if "score" in entry:
        return entry["score"]
    details = entry.get("details") or {}
    return details.get("score")


def _finite(value):
    """gnubg writes -Infinity for luck it could not compute."""
    if value is None:
        return 0.0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return value if value == value and abs(value) != float("inf") else 0.0


def _checker_decision(action, game_idx, ply, is_human, phase, bar=False):
    analysis = action.get("analysis") or {}
    moves = analysis.get("moves") or []
    imove = analysis.get("imove")

    played_move = action.get("move")
    played_txt = format_move(played_move)
    best_txt = format_move(moves[0].get("move")) if moves else played_txt

    # gnubg evaluates the leading candidates at 2 ply and prunes the tail to
    # 0 ply, so the list is not strictly monotonic beyond the top few.  This
    # does not affect the cost of a move: analysis re-evaluates the move
    # actually played at full depth, which is the only other term here.
    error, rank = 0.0, 0
    equity = win = None
    if moves and isinstance(imove, int) and 0 <= imove < len(moves):
        best_score = _score(moves[0])
        played_score = _score(moves[imove])
        if best_score is not None and played_score is not None:
            # Guard against sign noise: a played move can never beat the top
            # of the list, but pruned evaluations occasionally round past it.
            error = max(0.0, best_score - played_score)
        rank = imove
        equity = played_score
        probs = moves[imove].get("probs")
        if probs:
            win = probs[0]

    return Decision(
        game=game_idx, ply=ply, player=action.get("player", "?"),
        is_human=is_human, kind="checker",
        dice=format_dice(action.get("dice")),
        played=played_txt, best=best_txt,
        error=error, skill=classify_skill(error),
        rank=rank, alternatives=len(moves),
        luck=_finite(analysis.get("luck-value")),
        position_id=action.get("board", ""),
        phase=phase, win_prob=win, equity=equity, on_bar=bar,
    )


#: Doubling and having the opponent pass wins exactly the current cube
#: value, which in gnubg's normalised cubeful equity is 1.0.
PASS_EQUITY = 1.0


def cube_actions(nd_eq, dt_eq):
    """Equity of each cube action for the player on roll.

    ``nd`` is the equity of rolling on, ``dt`` of doubling and being taken.
    Doubling is worth whichever of take-or-pass the *opponent* prefers, so
    the doubler gets the worse of the two -- which is why a double is not
    simply "dt is high".
    """
    double_eq = min(dt_eq, PASS_EQUITY)
    return {"no double": nd_eq, "double": double_eq}


def _cube_decision(action, game_idx, ply, is_human, phase, bar=False):
    """An offered double: was offering it right?"""
    analysis = action.get("analysis") or {}
    nd_eq = analysis.get("nd-cubeful-eq")
    dt_eq = analysis.get("dt-cubeful-eq")

    error, best_txt = 0.0, "double"
    if nd_eq is not None and dt_eq is not None:
        options = cube_actions(nd_eq, dt_eq)
        best_txt = max(options, key=options.get)
        error = max(0.0, options[best_txt] - options["double"])

    return Decision(
        game=game_idx, ply=ply, player=action.get("player", "?"),
        is_human=is_human, kind="cube",
        dice=format_dice(action.get("dice")),
        played="double", best=best_txt,
        error=error, skill=classify_skill(error),
        luck=_finite(analysis.get("luck-value")),
        position_id=action.get("board", ""),
        phase=phase, on_bar=bar,
        equity=nd_eq,
    )


def _take_decision(action, game_idx, ply, is_human, phase, dt_eq, bar=False):
    """A take or a pass, judged from the doubler's analysis.

    gnubg records no analysis on the take itself -- the numbers live on the
    double that provoked it.  From the taker's side the equities are simply
    negated: taking is worth ``-dt``, passing exactly -1.
    """
    act = action.get("action", "take")
    if dt_eq is None:
        return Decision(
            game=game_idx, ply=ply, player=action.get("player", "?"),
            is_human=is_human, kind="take", played=act, best=act,
            error=0.0, skill="ok", position_id=action.get("board", ""),
            phase=phase, on_bar=bar,
        )

    options = {"take": -dt_eq, "pass": -PASS_EQUITY}
    best_txt = max(options, key=options.get)
    chosen = "take" if act == "take" else "pass"
    error = max(0.0, options[best_txt] - options[chosen])

    return Decision(
        game=game_idx, ply=ply, player=action.get("player", "?"),
        is_human=is_human, kind="take",
        played=chosen, best=best_txt,
        error=error, skill=classify_skill(error),
        position_id=action.get("board", ""),
        phase=phase, on_bar=bar, equity=options[chosen],
    )


def _missed_double(action, game_idx, ply, is_human, phase, bar=False):
    """The double that was never offered.

    A player who rolls has implicitly chosen not to double, and gnubg
    attaches the cube equities to the move action, so the decision is
    recoverable even though no cube action appears in the record.  Missed
    doubles are among the most expensive habits in match play and are
    invisible to anyone reviewing only their chequer play.

    Returns None when rolling on was correct -- those positions are not
    decisions in any meaningful sense and counting them would dilute the
    error rate towards zero.
    """
    analysis = action.get("analysis") or {}
    nd_eq = analysis.get("nd-cubeful-eq")
    dt_eq = analysis.get("dt-cubeful-eq")
    if nd_eq is None or dt_eq is None:
        return None

    options = cube_actions(nd_eq, dt_eq)
    best_txt = max(options, key=options.get)
    if best_txt != "double":
        return None
    error = max(0.0, options["double"] - options["no double"])
    if error <= 0:
        return None

    return Decision(
        game=game_idx, ply=ply, player=action.get("player", "?"),
        is_human=is_human, kind="cube",
        dice=format_dice(action.get("dice")),
        played="no double", best="double",
        error=error, skill=classify_skill(error),
        position_id=action.get("board", ""),
        phase=phase, on_bar=bar, equity=nd_eq,
    )


# ------------------------------------------------------------------ phases

def contact(board):
    """True while the two sides can still hit each other.

    Each side counts from its own home, so the players have passed one
    another once their furthest-back chequers sum to less than 25.
    """
    if not board:
        return True
    backmost = []
    for side in board:
        idx = [i for i, n in enumerate(side) if n]
        backmost.append((max(idx) + 1) if idx else 0)
    return (backmost[0] + backmost[1]) >= 25


def on_bar(board, mover_index=1):
    """Whether the mover has chequers on the bar.

    Kept as a tag rather than a phase.  Entering from the bar is a genuine
    coaching theme, but it happens across every stage of the game, so as a
    phase it swallowed most of the decisions and grouped nothing.
    """
    return bool(board) and bool(board[mover_index][24])


def phase_of(board, ply, mover_index=1):
    """A coarse game phase, used to group mistakes into themes.

    Grouping matters more than precision here: "you leak equity in
    no-contact races" is actionable, and a borderline position landing in
    the neighbouring bucket does not change that conclusion.
    """
    if not board:
        return "unknown"
    mover = board[mover_index]
    occupied = [i for i, n in enumerate(mover) if n]
    if not occupied:
        return "bearoff"
    back = max(occupied) + 1

    if not contact(board):
        return "bearoff" if back <= 6 else "race"
    # Two or more anchors deep in the opponent's home board.
    deep = sum(1 for i in (21, 22, 23) if mover[i] >= 2)
    if deep >= 2:
        return "back game"
    if ply < 4:
        return "opening"
    if back <= 6:
        return "bearoff"
    return "middle game"


# ------------------------------------------------------------------- build

def build_decisions(match, human_index=0, boards=None):
    """Flatten gnubg's match record into Decision rows.

    ``boards`` maps position ID -> board arrays (from the engine's decode
    method) and is optional; without it every phase reads "unknown" and the
    per-phase grouping is simply omitted from the coaching brief.
    """
    boards = boards or {}
    token = HUMAN_TOKEN[human_index]
    out = []
    for game_idx, game in enumerate(match.get("games") or []):
        pending_dt = None          # dt equity of the double awaiting a reply
        for ply, action in enumerate(game.get("game") or []):
            act = action.get("action")
            is_human = action.get("player") == token
            board = boards.get(action.get("board"))
            phase = phase_of(board, ply)
            bar = on_bar(board)

            if act == "move":
                out.append(_checker_decision(action, game_idx, ply, is_human, phase, bar))
                missed = _missed_double(action, game_idx, ply, is_human, phase, bar)
                if missed is not None:
                    out.append(missed)
            elif act == "double":
                out.append(_cube_decision(action, game_idx, ply, is_human, phase, bar))
                pending_dt = (action.get("analysis") or {}).get("dt-cubeful-eq")
            elif act in ("take", "drop"):
                out.append(_take_decision(action, game_idx, ply, is_human, phase,
                                          pending_dt, bar))
                pending_dt = None
    return out


def match_meta(match, human_index=0):
    """Match-level facts, including the true final score.

    Each game's ``info`` carries the score *going into* that game, so the
    last one is short by whatever the final game was worth.  The result is
    accumulated from the winners instead.
    """
    info = match.get("match-info") or {}
    games = match.get("games") or []
    token = HUMAN_TOKEN[human_index]

    human_pts = bot_pts = 0
    for game in games:
        ginfo = game.get("info") or {}
        winner = ginfo.get("winner")
        if not winner:
            continue
        points = ginfo.get("points-won") or ginfo.get("points") or 1
        try:
            points = int(points)
        except (TypeError, ValueError):
            points = 1
        if winner == token:
            human_pts += points
        else:
            bot_pts += points

    # A game can be worth more than the points still needed (a gammon with
    # the cube on 4 in a 3-point match); the score itself is capped.
    length = info.get("match-length") or 0
    if length:
        human_pts, bot_pts = min(human_pts, length), min(bot_pts, length)

    return {
        "match_length": info.get("match-length"),
        "games": len([g for g in games if (g.get("info") or {}).get("winner")]),
        "score_human": human_pts,
        "score_bot": bot_pts,
        "date": info.get("date"),
        "variation": info.get("variation"),
    }
