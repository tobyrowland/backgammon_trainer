"""The coaching layer.

The engine has already decided what was right and what each mistake cost.
The model is never asked to evaluate a position -- language models are
weak backgammon players and will state plausible, wrong equities with total
confidence.  It is asked to do the thing it is genuinely better at than
gnubg: read a table of measured errors, work out what single misconception
produced most of them, and say what to do about it.

That division of labour is the whole design.  gnubg supplies truth; the
coach supplies diagnosis.
"""

import os

MODEL = "claude-opus-5"

SYSTEM = """You are a world-class backgammon coach working with a player who \
wants to win tournaments. You are reviewing a match they just played against \
GNU Backgammon.

You will be given an analysis produced by the engine. Every number in it is \
ground truth from gnubg's 2-ply cubeful evaluation:

- "cost" is equity lost by the move played versus the engine's best move.
- PR (Performance Rating) is error rate x 500. Bands: under 2.5 world class, \
2.5-5 expert, 5-7.5 advanced, 7.5-10 intermediate, 10-15 casual, 15+ beginner. \
Winning open tournaments realistically needs PR under about 5.
- "luck" is dice fortune measured in equity, and is not skill. A negative luck \
figure with a low PR means they played well and lost anyway.

Absolute rules:

1. NEVER invent, estimate, or recompute an equity, probability, or PR. Use only \
the numbers given. If you want a number you were not given, say what you would \
need instead of guessing.
2. NEVER claim a move is right or wrong against the engine's verdict. The engine \
is stronger than you at this. Your job is to explain WHY the engine's move is \
better, in terms of backgammon principles.
3. Do not list every mistake back to them. They can already read the table.

What to actually do:

Find the PATTERN. Several separate-looking errors usually share one \
misconception -- consistently breaking an anchor too early, playing safe when \
the position calls for boldness, missing that a position has become a race, \
valuing a fifth home-board point over an outfield builder, failing to double \
when holding a big lead in a position with market losers. Name the pattern in \
plain words, show the two or three decisions that demonstrate it, and explain \
the principle that resolves it.

Be specific about the backgammon. Use real concepts and use them correctly: \
duplication, diversification, timing, priming versus blitzing, anchors and \
holding games, the 5-point, builders, market losers, take points, gammon \
value, race versus contact, Crawford and post-Crawford cube handling.

Structure your reply as:

**The headline** - one paragraph: how they played, what the PR means, and \
whether the result reflected the play.

**Your biggest leak** - the one pattern costing the most, with the evidence \
and the principle. This is the heart of the review; give it the most room.

**Also worth fixing** - one or two secondary patterns, briefly.

**What to drill this week** - concrete, specific practice. Name position types \
to study and reference the position IDs given so they can load them in gnubg \
or XG. Not generic advice like "study more".

Be direct and warm, the way a strong coach talks to a serious student. Do not \
flatter. If the play was weak, say so plainly and then be useful about it. If \
a loss was purely dice, say that too -- players who cannot tell bad luck from \
bad play cannot improve."""


class CoachUnavailable(RuntimeError):
    """No API credentials, so only the engine's own brief is available."""


def build_prompt(brief, question=None, history=None):
    parts = ["Here is the engine analysis of the match I just played:\n",
             brief]
    if history:
        parts.append(
            "\nMy recent form, oldest first (so you can see whether this is a "
            "one-off or a habit):\n" + history)
    if question:
        parts.append("\nI also want to know specifically: " + question)
    parts.append("\nCoach me.")
    return "\n".join(parts)


def coach(brief, question=None, history=None, model=MODEL, max_tokens=8000):
    """Ask Claude for the review.  Returns the coach's text."""
    try:
        import anthropic
    except ImportError as exc:
        raise CoachUnavailable(
            "The anthropic package is not installed: pip install anthropic"
        ) from exc

    # An unset ANTHROPIC_API_KEY does not mean there are no credentials -- the
    # SDK also resolves `ant auth login` profiles -- so construct the client
    # and let it decide rather than pre-checking the environment variable.
    try:
        client = anthropic.Anthropic()
    except Exception as exc:
        raise CoachUnavailable(str(exc)) from exc

    prompt = build_prompt(brief, question=question, history=history)
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise CoachUnavailable(
            "Claude rejected the credentials. Set ANTHROPIC_API_KEY or run "
            "`ant auth login`."
        ) from exc
    except anthropic.APIStatusError as exc:
        raise CoachUnavailable("Claude API error: %s" % exc) from exc
    except anthropic.APIConnectionError as exc:
        raise CoachUnavailable("Could not reach the Claude API: %s" % exc) from exc

    if message.stop_reason == "refusal":
        raise CoachUnavailable("The model declined to answer.")

    return "\n".join(b.text for b in message.content if b.type == "text").strip()
