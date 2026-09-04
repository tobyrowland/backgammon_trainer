"""Runs INSIDE GNU Backgammon's embedded Python interpreter.

Launched as:  gnubg -t -q -r -p bgcoach/gnubg_server.py

GNU Backgammon writes a great deal of chatter to stdout (board diagrams,
move announcements), so this speaks JSON over a unix socket instead of
stdio.  The socket path arrives via BGCOACH_SOCKET.

Protocol: newline-delimited JSON.
  request   {"id": 1, "method": "state", "params": {}}
  response  {"id": 1, "ok": true, "result": ...}
            {"id": 1, "ok": false, "error": "...", "traceback": "..."}
"""

import json
import os
import socket
import sys
import traceback

import gnubg

# gnubg resets the process cwd on startup, so never rely on relative paths.

# ---------------------------------------------------------------- helpers

#: gnubg's ``gamestate`` enum, as exposed through posinfo().
GAMESTATE = {
    0: "none",
    1: "playing",
    2: "over",
    3: "resigned",
    4: "dropped",
}

#: Difficulty presets.  Each maps to the plies searched and whether the
#: evaluation is noise-free.  Noise makes the bot fallible in a *humanlike*
#: way rather than simply shallow, which is what makes the lower levels
#: useful sparring rather than merely bad.
LEVELS = {
    "beginner":     {"plies": 0, "noise": 0.060},
    "casual":       {"plies": 0, "noise": 0.050},
    "intermediate": {"plies": 0, "noise": 0.040},
    "advanced":     {"plies": 0, "noise": 0.015},
    "expert":       {"plies": 0, "noise": 0.000},
    "world_class":  {"plies": 2, "noise": 0.000},
    "supremo":      {"plies": 2, "noise": 0.000},
    "grandmaster":  {"plies": 3, "noise": 0.000},
}


def _pip_counts():
    """Pip counts as ``(opponent, player_on_roll)``.

    gnubg.board() returns ``(anBoard[0], anBoard[1])`` where **index 1 is the
    player on roll** and index 0 is the opponent -- verified empirically, not
    assumed: after the bot opened with an 8-pip move the arrays read 159/167,
    and the untouched 167 sat at index 1 while the human was on roll.  Each
    array is that player's own numbering, index i holding the chequers (i+1)
    pips from home, with index 24 the bar.
    """
    return [sum(n * (i + 1) for i, n in enumerate(side)) for side in gnubg.board()]


def _state():
    """A snapshot of the position.

    Every gnubg accessor here raises once a game or match has ended --
    cubeinfo in particular fails with "error in SetCubeInfo" -- so each is
    guarded.  A state call must always answer, because the caller uses it to
    discover that the game is over in the first place.
    """
    try:
        pi = gnubg.posinfo()
    except Exception:
        pi = {"dice": (0, 0), "turn": -1, "resigned": 0, "doubled": 0, "gamestate": 2}
    try:
        ci = gnubg.cubeinfo()
        _LAST_GOOD.update({"score": tuple(ci["score"]), "matchto": ci["matchto"],
                           "crawford": ci["crawford"]})
    except Exception:
        ci = {"cube": 1, "cubeowner": -1,
              "score": _LAST_GOOD.get("score", (0, 0)),
              "matchto": _LAST_GOOD.get("matchto", 0),
              "crawford": _LAST_GOOD.get("crawford", 0)}
    try:
        board = [list(side) for side in gnubg.board()]
        pips = _pip_counts()
    except Exception:
        board = [[0] * 25, [0] * 25]
        pips = [0, 0]

    def _safe(fn, default=""):
        try:
            return fn()
        except Exception:
            return default

    return {
        "board": board,
        "dice": list(pi["dice"]),
        "turn": pi["turn"],
        "gamestate": GAMESTATE.get(pi["gamestate"], pi["gamestate"]),
        "doubled": pi["doubled"],
        "resigned": pi["resigned"],
        "cube": ci["cube"],
        "cube_owner": ci["cubeowner"],
        "score": list(ci["score"]),
        "match_to": ci["matchto"],
        "crawford": ci["crawford"],
        "on_roll_pips": pips[1],
        "opponent_pips": pips[0],
        "position_id": _safe(gnubg.positionid),
        "match_id": _safe(gnubg.matchid),
        "gnubg_id": _safe(gnubg.gnubgid),
        "match_over": _is_match_over(ci),
    }


#: The last cube/score reading that succeeded.  gnubg tears the cube info
#: down the moment a game ends, so a state call made *after* the final move
#: -- exactly when the caller wants to report the result -- would otherwise
#: fall back to zeros and announce a 0-0 finish to a match someone just lost.
_LAST_GOOD = {}


def _is_match_over(ci):
    target = ci.get("matchto") or 0
    if not target:
        return False
    return any(s >= target for s in ci.get("score") or ())


# ---------------------------------------------------------------- methods

def m_ping():
    return "pong"


def m_command(command):
    """Escape hatch: run a raw gnubg command."""
    gnubg.command(command)
    return _state()


def m_new_match(length=5, level="world_class", seed=None, jacoby=False):
    cfg = LEVELS.get(level, LEVELS["world_class"])
    gnubg.command("set player 0 human")
    gnubg.command("set player 0 name You")
    gnubg.command("set player 1 gnubg")
    gnubg.command("set player 1 name Bot")
    gnubg.command("set player 1 chequer evaluation plies %d" % cfg["plies"])
    gnubg.command("set player 1 chequer evaluation noise %.3f" % cfg["noise"])
    gnubg.command("set player 1 cube evaluation plies %d" % cfg["plies"])
    gnubg.command("set player 1 cube evaluation noise %.3f" % cfg["noise"])
    # Analysis must stay at full strength regardless of how weak the
    # sparring partner is set to play.
    gnubg.command("set analysis chequer evaluation plies 2")
    gnubg.command("set analysis cubedecision evaluation plies 2")
    gnubg.command("set analysis moves on")
    gnubg.command("set analysis cube on")
    gnubg.command("set analysis luck on")
    gnubg.command("set jacoby %s" % ("on" if jacoby else "off"))
    if seed is not None:
        gnubg.command("set seed %d" % int(seed))
    _LAST_GOOD.clear()
    gnubg.command("new match %d" % int(length))
    return _state()


def m_state():
    return _state()


def m_roll():
    gnubg.command("roll")
    return _state()


def m_hint():
    """Ranked candidate moves (or cube action) for the position on roll."""
    try:
        h = gnubg.hint()
    except Exception as exc:            # cube decisions raise in 1.07
        return {"hinttype": "unavailable", "reason": str(exc), "hint": []}
    out = {"hinttype": h.get("hinttype"), "gnubg_id": h.get("gnubgid"), "hint": []}
    for item in h.get("hint") or []:
        entry = {
            "rank": item.get("movenum"),
            "move": item.get("move"),
            "equity": item.get("equity"),
            "eqdiff": item.get("eqdiff"),
        }
        details = item.get("details") or {}
        probs = details.get("probs")
        if probs:
            entry["probs"] = list(probs)
        # Cube hints carry a different payload shape.
        for key in ("action", "double", "take", "nodouble", "doubletake",
                    "doublepass", "equity_nodouble", "equity_double"):
            if key in item:
                entry[key] = item[key]
        out["hint"].append(entry)
    return out


def m_move(notation):
    """Play a move, refusing anything gnubg would not accept.

    gnubg's `move` command reports an illegal move on stdout and returns
    normally -- it raises nothing.  Without this check a typo would be
    silently swallowed: the prompt would accept it, the position would not
    change, and the player would be left wondering why the board was stuck.
    Comparing the position before and after is decisive, since no legal move
    can leave the position identical.
    """
    before = _safe_position()
    gnubg.command("move %s" % notation)
    if _safe_position() == before:
        raise ValueError("illegal move: %s" % notation)
    return _state()


def _safe_position():
    try:
        pi = gnubg.posinfo()
        return (gnubg.positionid(), pi["turn"], tuple(pi["dice"]))
    except Exception:
        return None


def m_double():
    gnubg.command("double")
    return _state()


def m_take():
    gnubg.command("take")
    return _state()


def m_drop():
    gnubg.command("drop")
    return _state()


def m_resign(kind="normal"):
    gnubg.command("resign %s" % kind)
    return _state()


def m_save(path, fmt="mat"):
    """Persist the match.  .mat is the portable interchange format; .sgf is
    gnubg's own and is the only one that round-trips its analysis."""
    cmd = {"mat": "export match mat", "sgf": "save match", "text": "export match text"}[fmt]
    gnubg.command("%s %s" % (cmd, path))
    return {"path": path, "format": fmt}


def m_load(path):
    """Load a match from disk.

    .mat is the portable format every client exports (XG, Backgammon Galaxy,
    GridGammon); .sgf is gnubg's own and is the only one that carries its
    analysis back in.  gnubg needs a different command for each.
    """
    lower = path.lower()
    if lower.endswith(".mat"):
        gnubg.command("import mat %s" % path)
    elif lower.endswith(".sgf"):
        gnubg.command("load match %s" % path)
    elif lower.endswith(".bkg"):
        gnubg.command("import bkg %s" % path)
    else:
        gnubg.command("import auto %s" % path)
    return _state()


def m_analyse_match():
    gnubg.command("analyse match")
    return {"analysed": True}


def m_quit():
    raise SystemExit(0)



def m_match(analyse=True):
    """The whole match as a structured record.

    This is the analysis workhorse.  gnubg hands back every action with its
    ranked alternatives and ``imove`` -- the index of the move actually
    played -- so a decision's cost is simply
    ``moves[0].score - moves[imove].score``.

    ``player`` is "X" for player 0 and "O" for player 1.  That mapping is
    verified in tests/test_record.py rather than taken on trust: the names in
    match-info do not reliably follow the `set player N name` commands, and
    reading it backwards would attribute every one of the human's errors to
    the bot.
    """
    if analyse:
        # Re-analyse at full strength.  During play the lower-ranked moves are
        # pruned to 0-ply, which is fine for choosing a move but too coarse to
        # tell a player what their mistake cost them.
        gnubg.command("analyse match")
    return gnubg.match()


def m_set_level(level="world_class"):
    cfg = LEVELS.get(level, LEVELS["world_class"])
    gnubg.command("set player 1 chequer evaluation plies %d" % cfg["plies"])
    gnubg.command("set player 1 chequer evaluation noise %.3f" % cfg["noise"])
    gnubg.command("set player 1 cube evaluation plies %d" % cfg["plies"])
    gnubg.command("set player 1 cube evaluation noise %.3f" % cfg["noise"])
    return {"level": level, "plies": cfg["plies"], "noise": cfg["noise"]}


def m_decode(position_ids):
    """Board arrays for a list of position IDs.

    Phase classification (race, bear-off, back game) needs the actual
    chequer layout, but gnubg's match record identifies each position only
    by ID.  Decoding happens here, in one round trip, rather than
    reimplementing gnubg's position encoding outside the engine.
    """
    out = {}
    for pid in position_ids:
        try:
            board = gnubg.positionfromid(pid)
            out[pid] = [list(side) for side in board]
        except Exception:
            out[pid] = None
    return out


def m_next_game():
    """Start the next game of the match, if the match is still live."""
    st = _state()
    if st["match_over"]:
        return st
    gnubg.command("new game")
    return _state()


METHODS = {name[2:]: fn for name, fn in list(globals().items())
           if name.startswith("m_") and callable(fn)}


# ---------------------------------------------------------------- serve

def serve(path):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    if os.path.exists(path):
        os.unlink(path)
    srv.bind(path)
    srv.listen(1)
    # Signal readiness only once the socket can actually accept a connection.
    sys.stderr.write("BGCOACH_READY\n")
    sys.stderr.flush()
    conn, _ = srv.accept()
    buf = b""
    with conn:
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    req = json.loads(line.decode("utf-8"))
                except Exception as exc:
                    conn.sendall((json.dumps(
                        {"id": None, "ok": False, "error": "bad json: %s" % exc}
                    ) + "\n").encode("utf-8"))
                    continue
                rid = req.get("id")
                try:
                    fn = METHODS.get(req.get("method"))
                    if fn is None:
                        raise ValueError("unknown method %r" % req.get("method"))
                    result = fn(**(req.get("params") or {}))
                    resp = {"id": rid, "ok": True, "result": result}
                except SystemExit:
                    conn.sendall((json.dumps({"id": rid, "ok": True, "result": "bye"}) + "\n").encode("utf-8"))
                    return
                except Exception as exc:
                    resp = {"id": rid, "ok": False, "error": str(exc),
                            "traceback": traceback.format_exc()}
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))


serve(os.environ["BGCOACH_SOCKET"])
