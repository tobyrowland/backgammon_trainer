"""Backgammon move notation.

gnubg reports a move as a tuple of ``(from, to)`` hops in the mover's own
point numbering, where 25 is the bar and 0 is off.  Humans read
``bar/20 13/11(2)``.  This module converts between the two.

Pure: no engine, no I/O.
"""

BAR = 25
OFF = 0


def _point(n):
    if n == BAR:
        return "bar"
    if n == OFF:
        return "off"
    return str(n)


def format_move(hops):
    """Render gnubg's hop tuples as standard notation.

    Consecutive hops by the same chequer are chained (``24/18/13``), and
    identical hops are grouped with a multiplier (``13/11(2)``) -- both are
    how the move would appear in a match record or a book.
    """
    hops = [tuple(h) for h in (hops or []) if h and len(h) >= 2]
    hops = [(h[0], h[1]) for h in hops if not (h[0] == 0 and h[1] == 0)]
    if not hops:
        return "(no play)"

    # Chain hops where one ends on the point the next starts from, which is
    # the same chequer continuing.  Walk greedily; gnubg emits hops in play
    # order, so a single pass is enough.
    chains = []
    for src, dst in hops:
        for chain in chains:
            if chain[-1] == src and src != BAR and src != OFF:
                chain.append(dst)
                break
        else:
            chains.append([src, dst])

    rendered = ["/".join(_point(p) for p in chain) for chain in chains]

    out, seen = [], {}
    for item in rendered:
        seen[item] = seen.get(item, 0) + 1
    for item in rendered:
        if item in out or seen[item] == 0:
            continue
        count = seen[item]
        out.append(item)
        seen[item] = 0
        if count > 1:
            out[-1] = "%s(%d)" % (item, count)
    return " ".join(out)


def format_dice(dice):
    dice = list(dice or [])
    if len(dice) < 2 or not dice[0]:
        return "--"
    return "%d%d" % (dice[0], dice[1])
