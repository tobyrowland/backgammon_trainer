"""Command line entry point."""

import argparse
import os
import sys

from . import store
from .analysis import format_brief
from .coach import CoachUnavailable, coach
from .engine import GnubgSession, GnubgUnavailable
from .play import Match
from .review import analyse

LEVELS = ["beginner", "casual", "intermediate", "advanced", "expert",
          "world_class", "supremo", "grandmaster"]


def _coach_section(brief, directory, question=None, use_history=True):
    """Print the engine brief, then the coach's read of it."""
    print("\n" + "=" * 70)
    print("ENGINE ANALYSIS")
    print("=" * 70)
    print(brief)

    rows = store.history(directory) if use_history else []
    history_text = store.format_history(rows) if len(rows) > 1 else None

    print("\n" + "=" * 70)
    print("COACH")
    print("=" * 70)
    try:
        print(coach(brief, question=question, history=history_text))
    except CoachUnavailable as exc:
        print("(Coaching unavailable: %s)" % exc)
        print("The engine analysis above is complete and correct on its own.")
        return False
    return True


def cmd_play(args):
    with GnubgSession() as engine:
        match = Match(engine, length=args.length, level=args.level,
                      instant=args.instant)
        match.run()

        print("\nAnalysing at full strength...")
        decisions, summary = analyse(engine, human_index=0)
        brief = format_brief(summary)

        path = store.save(summary, decisions, directory=args.dir,
                          extra={"assisted_moves": len(match.assisted),
                                 "level": args.level})
        if args.save_match:
            try:
                engine.save(os.path.abspath(args.save_match),
                            fmt="sgf" if args.save_match.endswith(".sgf") else "mat")
                print("Match file: %s" % args.save_match)
            except Exception as exc:
                print("(could not export match file: %s)" % exc)

        if args.no_coach:
            print("\n" + brief)
        else:
            _coach_section(brief, args.dir, question=args.question)
        print("\nSaved to %s" % path)


def cmd_review(args):
    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        sys.exit("No such file: %s" % path)

    if path.endswith(".json"):
        data = store.load(path)
        summary = data.get("summary") or {}
        # A saved summary is plain JSON, so rebuild just enough for the brief.
        from .analysis import format_brief as _fmt
        from types import SimpleNamespace
        for key in ("top_mistakes", "themes"):
            items = summary.get(key) or []
            if key == "themes":
                summary[key] = [dict(i, decision=SimpleNamespace(**i["decision"]))
                                for i in items]
            else:
                summary[key] = [SimpleNamespace(**i) for i in items]
        brief = _fmt(summary)
        _coach_section(brief, args.dir, question=args.question)
        return

    with GnubgSession() as engine:
        engine.load(path)
        decisions, summary = analyse(engine, human_index=args.player)
        brief = format_brief(summary)
        saved = store.save(summary, decisions, directory=args.dir,
                           extra={"source": path})
        _coach_section(brief, args.dir, question=args.question)
        print("\nSaved to %s" % saved)


def cmd_history(args):
    rows = store.history(args.dir)
    if not rows:
        sys.exit("No matches recorded yet in %s. Play one: bgcoach play" % args.dir)
    print(store.format_history(rows, limit=args.limit))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="bgcoach",
        description="Play backgammon against GNU Backgammon, then have Claude "
                    "coach you on the match.")
    parser.add_argument("--dir", default=store.DEFAULT_DIR,
                        help="where match records are kept (default: ./matches)")
    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="play a match against the engine")
    play.add_argument("--length", type=int, default=5, help="match length (default 5)")
    play.add_argument("--level", default="world_class", choices=LEVELS,
                      help="engine strength (default world_class)")
    play.add_argument("--instant", action="store_true",
                      help="grade every move as you play instead of at the end")
    play.add_argument("--no-coach", action="store_true",
                      help="engine analysis only, no LLM review")
    play.add_argument("--question", help="something specific to ask the coach")
    play.add_argument("--save-match", help="also export the match (.mat or .sgf)")
    play.set_defaults(func=cmd_play)

    review = sub.add_parser("review",
                            help="analyse a match file (.mat/.sgf) or a saved record")
    review.add_argument("file")
    review.add_argument("--player", type=int, default=0, choices=(0, 1),
                        help="which player is you (0 = the first named, default)")
    review.add_argument("--question", help="something specific to ask the coach")
    review.set_defaults(func=cmd_review)

    hist = sub.add_parser("history", help="your PR over time")
    hist.add_argument("--limit", type=int, default=20)
    hist.set_defaults(func=cmd_history)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except GnubgUnavailable as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit("\nStopped.")


if __name__ == "__main__":
    main()
