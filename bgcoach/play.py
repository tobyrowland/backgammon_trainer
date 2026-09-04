"""The interactive match: you against gnubg, in the terminal.

Two deliberate choices about how this plays:

*You move blind.*  The candidate list is not shown before you commit.  A
trainer that shows you the engine's ranking first is a calculator, not a
trainer -- the whole value is in comparing your judgement against the
engine's afterwards.  ``?`` overrides this when you genuinely want to be
shown, and asking is recorded so the review knows the move was assisted.

*Feedback is deferred by default.*  Tournament conditions are silent, and
learning to sit with uncertainty is part of the skill.  ``--instant`` turns
on move-by-move feedback for study sessions.
"""

from . import notation
from .board import render
from .record import match_meta

HELP = """
Commands
  <enter> or r     roll the dice
  d                double
  t / p            take / pass (when you have been doubled)
  24/18 13/11      play a move (bar/20 and 6/off also work)
  ?                ask the engine (recorded as an assisted move)
  b                redraw the board
  pip              show pip counts
  q                resign the match and go to the review
"""


def _flatten(match):
    out = []
    for gi, game in enumerate(match.get("games") or []):
        for action in game.get("game") or []:
            out.append((gi, action))
    return out


def _describe(action):
    act = action.get("action")
    if act == "move":
        mv = notation.format_move(action.get("move"))
        return "rolls %s and plays %s" % (notation.format_dice(action.get("dice")), mv)
    if act == "double":
        return "DOUBLES"
    if act == "take":
        return "takes"
    if act == "drop":
        return "passes"
    if act == "resign":
        return "resigns"
    return act or "?"


class Match:
    """One match against the engine, played interactively."""

    def __init__(self, engine, length=5, level="world_class", instant=False,
                 human_index=0, out=print, ask=input):
        self.engine = engine
        self.length = length
        self.level = level
        self.instant = instant
        self.human = human_index
        self.out = out
        self.ask = ask
        self.cursor = 0
        self.assisted = []          # plies where the engine was consulted

    # ------------------------------------------------------------- plumbing

    def _token(self):
        return "X" if self.human == 0 else "O"

    def _report_new_actions(self):
        """Announce whatever happened since the last time we looked.

        gnubg plays the bot's turns inside whichever command we issued, so
        the only way to know what it did is to read the record back.
        """
        match = self.engine.match(analyse=False)
        actions = _flatten(match)
        new = actions[self.cursor:]
        self.cursor = len(actions)
        for _, action in new:
            if action.get("player") != self._token():
                self.out("  Bot %s" % _describe(action))
        return new

    def _instant_feedback(self, new):
        """Grade the human's move immediately, in study mode."""
        for _, action in new:
            if action.get("player") != self._token() or action.get("action") != "move":
                continue
            analysis = action.get("analysis") or {}
            moves = analysis.get("moves") or []
            imove = analysis.get("imove")
            if not moves or not isinstance(imove, int) or imove >= len(moves):
                continue
            if imove == 0:
                self.out("  -> best move.")
                continue
            best = moves[0].get("score")
            got = moves[imove].get("score")
            if best is None or got is None:
                continue
            cost = max(0.0, best - got)
            self.out("  -> ranked %d. Best was %s (costs you %.3f)."
                     % (imove + 1, notation.format_move(moves[0].get("move")), cost))

    def score(self):
        """The running score, taken from the match record.

        Not from cubeinfo: that reports the score *going into* the current
        game, so at the moment a game ends -- exactly when the result is
        announced -- it still reads as it did before the game was played.
        """
        try:
            meta = match_meta(self.engine.match(analyse=False),
                              human_index=self.human)
            return meta.get("score_human", 0), meta.get("score_bot", 0)
        except Exception:
            return 0, 0

    def show(self, state):
        self.out("")
        self.out(render(state["board"], state["turn"], human=self.human,
                        score=state["score"], match_to=state["match_to"],
                        cube=state["cube"], cube_owner=state["cube_owner"],
                        dice=state["dice"]))

    # ------------------------------------------------------------ the loop

    def run(self):
        state = self.engine.new_match(length=self.length, level=self.level)
        self.out("Match to %d against gnubg (%s). Type ? for help at any prompt."
                 % (self.length, self.level.replace("_", " ")))
        self._report_new_actions()
        self.show(state)

        guard = 0
        while guard < 5000:
            guard += 1
            state = self.engine.state()

            if state.get("match_over"):
                mine, theirs = self.score()
                self.out("\nMatch over. Final score: you %d - %d bot." % (mine, theirs))
                break

            if state["gamestate"] != "playing":
                mine, theirs = self.score()
                self.out("\nGame over. Score: you %d - %d bot." % (mine, theirs))
                state = self.engine.next_game()
                if self.engine.state()["gamestate"] != "playing":
                    mine, theirs = self.score()
                    self.out("Match over. Final score: you %d - %d bot." % (mine, theirs))
                    break
                self._report_new_actions()
                self.show(self.engine.state())
                continue

            if state["turn"] != self.human:
                # gnubg normally plays its own turn inside our command; if we
                # ever land here it simply needs prodding.
                self._report_new_actions()
                state = self.engine.state()
                if state["turn"] != self.human:
                    break
                continue

            if state["doubled"]:
                if not self._handle_double(state):
                    break
                continue

            if not self._handle_turn(state):
                break

        return self.assisted

    def _handle_double(self, state):
        cube_to = state["cube"] * 2
        self.out("\n  Bot DOUBLES to %d." % cube_to)
        while True:
            reply = self.ask("  take or pass? [t/p] ").strip().lower()
            if reply in ("t", "take"):
                self.engine.take()
                self.out("  You take. Cube at %d." % cube_to)
                self._report_new_actions()
                self.show(self.engine.state())
                return True
            if reply in ("p", "pass", "d", "drop"):
                self.engine.drop()
                self.out("  You pass.")
                self._report_new_actions()
                return True
            if reply in ("q", "quit"):
                return False
            self.out(HELP)

    def _handle_turn(self, state):
        """Prompt until the player does something that advances the game.

        The position is re-read from the engine on every pass rather than
        trusted from the snapshot this was called with.  An earlier version
        decided once whether the dice had been rolled and then stuck to it;
        any change it had not seen left the prompt and the engine disagreeing
        about what turn it was, and the loop asked for a move forever.
        """
        while True:
            state = self.engine.state()
            if state["gamestate"] != "playing" or state["turn"] != self.human:
                return True                      # something advanced; re-enter
            if state["doubled"]:
                return self._handle_double(state)

            rolled = tuple(state["dice"]) != (0, 0)
            prompt = "  your move: " if rolled else "  [enter] to roll, d to double: "

            try:
                raw = self.ask(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                self.out("\nStopping.")
                return False
            cmd = raw.lower()

            if cmd in ("q", "quit", "resign"):
                return False
            if cmd in ("h", "help"):
                self.out(HELP)
                continue
            if cmd == "b":
                self.show(state)
                continue
            if cmd == "pip":
                mine = state["on_roll_pips"]
                theirs = state["opponent_pips"]
                self.out("  pips - you %d, bot %d (%+d)" % (mine, theirs, theirs - mine))
                continue
            if cmd == "?":
                self._show_hint(state)
                continue

            if not rolled:
                if cmd in ("", "r", "roll"):
                    self.engine.roll()
                    rolled_state = self.engine.state()
                    self.out("  You roll %s." % notation.format_dice(rolled_state["dice"]))
                    self._check_dance(rolled_state)
                    continue
                if cmd in ("d", "double"):
                    try:
                        self.engine.double()
                    except Exception as exc:
                        self.out("  Cannot double: %s" % exc)
                        continue
                    self.out("  You double.")
                    self._report_new_actions()
                    self.show(self.engine.state())
                    return True
                self.out(HELP)
                continue

            if not raw:
                self.out("  Enter a move, or ? to be shown the options.")
                continue

            try:
                self.engine.move(raw)
            except Exception as exc:
                reason = str(exc).strip() or "illegal move"
                self.out("  %s. Try again, or ? for the options." % reason)
                continue

            new_actions = self._report_new_actions()
            if self.instant:
                self._instant_feedback(new_actions)
            self.show(self.engine.state())
            return True

    def _check_dance(self, state):
        """Announce a dance if the roll has no legal play.

        gnubg advances past it on its own, so nothing needs submitting -- but
        without a word on screen the board simply changes and it looks like
        the roll was ignored.
        """
        if state["gamestate"] != "playing" or state["turn"] != self.human:
            self.out("  No legal move -- you dance.")
            self._report_new_actions()
            self.show(self.engine.state())
            return
        hint = self.engine.hint()
        if hint.get("hinttype") == "chequer" and not hint.get("hint"):
            self.out("  No legal move -- you dance.")
            self._report_new_actions()
            self.show(self.engine.state())

    def _show_hint(self, state):
        hint = self.engine.hint()
        moves = hint.get("hint") or []
        if not moves:
            self.out("  (no move hint available here -- %s)"
                     % hint.get("reason", "cube decision"))
            return
        self.assisted.append(len(self.assisted))
        self.out("  Engine's candidates:")
        for item in moves[:5]:
            self.out("    %d. %-20s %+.3f" % (item["rank"], item["move"],
                                              item.get("eqdiff") or 0.0))
        self.out("  (recorded as an assisted move)")
