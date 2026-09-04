"""Board geometry and terminal rendering.

gnubg hands out ``(anBoard[0], anBoard[1])`` where index 1 is the player on
roll and index 0 the opponent, each in that player's own numbering: element
i is the chequer count on the point (i+1) pips from home, and element 24 is
the bar.  Every position therefore has two valid readings, and the whole
board flips its meaning depending on whose turn it is.

Rendering from that directly is how sign errors get made, so this module
converts once into a single absolute frame -- always the human's numbering,
positive counts for the human, negative for the bot -- and everything
downstream reads that.

Pure: no engine, no I/O.
"""

CHEQUERS = 15


def absolute(board, turn, human=0):
    """Normalise into the human's frame.

    Returns ``points`` indexed 1..24 in the human's numbering (index 0
    unused), positive for human chequers and negative for the bot's, plus
    bar and borne-off counts for each side.
    """
    on_roll, opponent = list(board[1]), list(board[0])
    human_side, bot_side = (on_roll, opponent) if turn == human else (opponent, on_roll)

    points = [0] * 25
    for i in range(24):
        # The two players count in opposite directions: the human's point p
        # is the bot's point 25-p.
        points[i + 1] += human_side[i]
        points[24 - i] -= bot_side[i]

    human_bar, bot_bar = human_side[24], bot_side[24]
    human_off = CHEQUERS - sum(human_side)
    bot_off = CHEQUERS - sum(bot_side)
    return {
        "points": points,
        "human_bar": human_bar,
        "bot_bar": bot_bar,
        "human_off": human_off,
        "bot_off": bot_off,
    }


def pip_counts(board, turn, human=0):
    """(human_pips, bot_pips)."""
    on_roll = sum(n * (i + 1) for i, n in enumerate(board[1]))
    opponent = sum(n * (i + 1) for i, n in enumerate(board[0]))
    return (on_roll, opponent) if turn == human else (opponent, on_roll)


def _glyph(count, row):
    """The 3-character column for one row of a point.

    Rows are counted from the edge inward.  A stack taller than five shows
    the total on its fifth row rather than running off the board.
    """
    n = abs(count)
    if n == 0:
        return "   "
    if row == 4 and n > 5:
        return "%2d " % n
    if row < n:
        return " X " if count > 0 else " O "
    return "   "


def _bar(count, row, human_side):
    n = abs(count)
    if n and row < n:
        return " X " if human_side else " O "
    if n and row == 4 and n > 5:
        return "%2d " % n
    return "   "


TOP = " +13-14-15-16-17-18------19-20-21-22-23-24-+"
BOTTOM = " +12-11-10--9--8--7-------6--5--4--3--2--1-+"


def render(board, turn, human=0, human_name="You", bot_name="Bot",
           score=(0, 0), match_to=0, cube=1, cube_owner=-1, dice=(0, 0)):
    """An ASCII board in gnubg's conventional layout.

    The human is always X along the bottom moving 24 -> 1, so the picture
    never flips between turns -- a board that reorients itself is how you
    learn to misread your own position.
    """
    abs_ = absolute(board, turn, human)
    pts = abs_["points"]
    hp, bp = pip_counts(board, turn, human)
    bot_score = score[1 - human] if len(score) > 1 else 0
    human_score = score[human] if len(score) > human else 0

    def side_note(row, who):
        if who == "bot":
            if row == 0:
                return "  O: %s" % bot_name
            if row == 1:
                return "     %d point%s" % (bot_score, "" if bot_score == 1 else "s")
            if row == 2:
                return "     %d pips" % bp
            if row == 3 and abs_["bot_off"]:
                return "     %d off" % abs_["bot_off"]
        else:
            if row == 0:
                return "  X: %s" % human_name
            if row == 1:
                return "     %d point%s" % (human_score, "" if human_score == 1 else "s")
            if row == 2:
                return "     %d pips" % hp
            if row == 3 and abs_["human_off"]:
                return "     %d off" % abs_["human_off"]
        return ""

    lines = [TOP]
    for row in range(5):
        left = "".join(_glyph(pts[p], row) for p in range(13, 19))
        right = "".join(_glyph(pts[p], row) for p in range(19, 25))
        lines.append(" |%s|%s|%s|%s" % (left, _bar(abs_["bot_bar"], row, False),
                                        right, side_note(row, "bot")))

    cube_txt = "cube %d" % cube
    if cube_owner == human:
        cube_txt += " (yours)"
    elif cube_owner in (0, 1):
        cube_txt += " (%s)" % bot_name
    else:
        cube_txt += " (centred)"
    match_txt = ("%d point match" % match_to) if match_to else "money game"
    lines.append(" |                  |BAR|                  |  %s, %s" % (match_txt, cube_txt))

    for row in reversed(range(5)):
        left = "".join(_glyph(pts[p], row) for p in range(12, 6, -1))
        right = "".join(_glyph(pts[p], row) for p in range(6, 0, -1))
        lines.append(" |%s|%s|%s|%s" % (left, _bar(abs_["human_bar"], row, True),
                                        right, side_note(row, "human")))
    lines.append(BOTTOM)
    return "\n".join(lines)
