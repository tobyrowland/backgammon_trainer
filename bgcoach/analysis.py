"""Turn a list of decisions into a coaching brief.

The unit of skill in backgammon is the **error rate**: equity thrown away
per decision.  Multiplied by 500 it is the Performance Rating (PR) that
tournament players quote, and it is the number to drive down if the goal is
to win championships.

    PR    0.0 - 2.5   world class
          2.5 - 5     expert
          5   - 7.5   advanced
          7.5 - 10    intermediate
          10  - 15    casual
          15 +        beginner

This module is pure aggregation over Decision rows.  It computes; it does
not advise.  The advice comes from the coach, and only ever on top of these
numbers.
"""

from collections import defaultdict

#: PR is the error rate scaled so the bands above land on round numbers.
PR_SCALE = 500

BANDS = [
    (2.5, "world class"),
    (5.0, "expert"),
    (7.5, "advanced"),
    (10.0, "intermediate"),
    (15.0, "casual"),
    (float("inf"), "beginner"),
]


def band(pr):
    for limit, name in BANDS:
        if pr < limit:
            return name
    return "beginner"


def counts_as_decision(d):
    """Whether a decision belongs in the error-rate denominator.

    A forced move -- one legal play -- is not a decision and would only
    dilute the rate.  Cube rows are already only emitted where a real cube
    decision existed (an offered double, a reply to one, or a double that
    should have been offered), so they all count.
    """
    if d.kind == "checker":
        return d.alternatives > 1
    return True


def _rate(decisions):
    counted = [d for d in decisions if counts_as_decision(d)]
    total = sum(d.error for d in counted)
    n = len(counted)
    pr = (total / n) * PR_SCALE if n else 0.0
    return {"decisions": n, "equity_lost": total, "pr": pr, "band": band(pr)}


def collapse_repeats(decisions):
    """Collapse a double missed on consecutive turns into one finding.

    A player who should double and rolls instead will usually still be
    right to double next turn, and the turn after.  Nineteen rows saying
    the same thing is not nineteen lessons -- it is one lesson with a
    persistence count, and reporting it as nineteen would bury everything
    else.
    """
    out = []
    run = None
    for d in decisions:
        is_missed = d.kind == "cube" and d.played == "no double"
        if (is_missed and run is not None
                and run["decision"].game == d.game
                and d.ply - run["last_ply"] <= 2):
            run["times"] += 1
            run["last_ply"] = d.ply
            run["total_error"] += d.error
            continue
        if run is not None:
            out.append(run)
        run = {"decision": d, "times": 1, "last_ply": d.ply, "total_error": d.error}
    if run is not None:
        out.append(run)
    return out


def summarise(decisions, meta=None):
    """The full picture of one match, from the human's side."""
    human = [d for d in decisions if d.is_human]
    bot = [d for d in decisions if not d.is_human]

    checker = [d for d in human if d.kind == "checker"]
    cube = [d for d in human if d.kind in ("cube", "take")]

    by_phase = defaultdict(list)
    for d in checker:
        if counts_as_decision(d):
            by_phase[d.phase].append(d)

    phases = {}
    for name, rows in by_phase.items():
        stats = _rate(rows)
        phases[name] = stats

    on_bar = [d for d in checker if d.on_bar and counts_as_decision(d)]

    mistakes = sorted([d for d in human if d.error > 0], key=lambda d: -d.error)
    grouped = collapse_repeats(sorted(
        [d for d in human if d.error > 0], key=lambda d: (d.game, d.ply)))
    grouped.sort(key=lambda g: -g["total_error"])

    return {
        "meta": meta or {},
        "overall": _rate(human),
        "chequer": _rate(checker),
        "cube": _rate(cube),
        "opponent_overall": _rate(bot),
        "phases": phases,
        "on_bar": _rate(on_bar) if on_bar else None,
        "luck": sum(d.luck for d in human),
        "opponent_luck": sum(d.luck for d in bot),
        "skill_counts": {
            name: len([d for d in human if d.skill == name])
            for name in ("blunder", "error", "doubtful", "ok")
        },
        "missed_doubles": len([d for d in cube if d.played == "no double"]),
        "top_mistakes": mistakes[:12],
        "themes": grouped[:10],
    }


# ---------------------------------------------------------------- rendering

def _pct(value):
    return "%.3f" % value


def format_brief(summary, max_mistakes=10):
    """A compact text brief.

    This is what the coach reads, and what is printed locally when there is
    no API key.  It is deliberately dense: every line is a measured fact,
    so the model spends its effort on diagnosis rather than on arithmetic.
    """
    meta = summary.get("meta") or {}
    lines = []

    length = meta.get("match_length")
    if length:
        lines.append("Match to %s. Final score: you %s - %s bot (%s games)." % (
            length, meta.get("score_human", 0), meta.get("score_bot", 0),
            meta.get("games", 0)))

    o = summary["overall"]
    lines.append("Overall PR %.1f (%s) - %.3f equity lost over %d decisions."
                 % (o["pr"], o["band"], o["equity_lost"], o["decisions"]))

    c, q = summary["chequer"], summary["cube"]
    lines.append("  Chequer play: PR %.1f over %d decisions (%.3f lost)."
                 % (c["pr"], c["decisions"], c["equity_lost"]))
    lines.append("  Cube play:    PR %.1f over %d decisions (%.3f lost), %d missed doubles."
                 % (q["pr"], q["decisions"], q["equity_lost"], summary["missed_doubles"]))

    opp = summary["opponent_overall"]
    lines.append("  Opponent (gnubg) PR %.1f for comparison." % opp["pr"])

    sk = summary["skill_counts"]
    lines.append("  Severity: %d blunders, %d errors, %d doubtful."
                 % (sk["blunder"], sk["error"], sk["doubtful"]))

    luck, oluck = summary["luck"], summary["opponent_luck"]
    lines.append("  Luck: you %+.3f, opponent %+.3f (dice, not skill)." % (luck, oluck))

    if summary["phases"]:
        lines.append("")
        lines.append("Error rate by game phase (chequer play):")
        for name, st in sorted(summary["phases"].items(), key=lambda kv: -kv[1]["pr"]):
            lines.append("  %-14s PR %6.1f over %2d decisions (%.3f lost)"
                         % (name, st["pr"], st["decisions"], st["equity_lost"]))

    if summary.get("on_bar"):
        b = summary["on_bar"]
        lines.append("  %-14s PR %6.1f over %2d decisions (%.3f lost)"
                     % ("(on the bar)", b["pr"], b["decisions"], b["equity_lost"]))

    themes = summary.get("themes") or []
    if themes:
        lines.append("")
        lines.append("Costliest decisions:")
        for item in themes[:max_mistakes]:
            d = item["decision"]
            repeat = ""
            if item["times"] > 1:
                repeat = "  [same call missed %d turns running, %.3f total]" % (
                    item["times"], item["total_error"])
            if d.kind == "checker":
                lines.append(
                    "  game %d ply %-3d roll %-3s  you played %-18s best %-18s"
                    "  cost %.3f  (%s%s)%s"
                    % (d.game + 1, d.ply, d.dice, d.played, d.best, d.error,
                       d.phase, ", on the bar" if d.on_bar else "", repeat))
                if d.position_id:
                    # The position ID loads the exact position in gnubg or XG,
                    # so a finding can be replayed rather than just read about.
                    lines.append("      position: %s" % d.position_id)
            else:
                lines.append(
                    "  game %d ply %-3d cube      you %-18s best %-18s"
                    "  cost %.3f  (%s)%s"
                    % (d.game + 1, d.ply, d.played, d.best, d.error, d.phase, repeat))
    return "\n".join(lines)
