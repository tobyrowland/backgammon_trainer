# backgammon_trainer

Play backgammon against a world-class engine, then have Claude review the match
and tell you what to work on.

```
$ bgcoach play --length 7
$ bgcoach history
```

## How it works, and why it works that way

Two engines, with a strict division of labour:

**GNU Backgammon plays you and grades you.** gnubg is a genuinely world-class
bot and the analysis engine serious players already use. Every number this tool
reports — what your move cost, what the best move was, your error rate — comes
from gnubg's 2-ply cubeful evaluation. Nothing is estimated.

**Claude reads the numbers and coaches you.** The model never evaluates a
position. This matters: language models are weak backgammon players and will
state a plausible, wrong equity with complete confidence. Ask one whether to
play 13/7 6/5 or 24/18 13/11 and you get prose, not analysis.

So the model is given gnubg's measured errors and asked to do the thing it is
genuinely better at than gnubg: notice that eleven of your fourteen mistakes
were the *same* misjudgement, name it, and tell you what to drill. gnubg can
tell you a move cost 0.073. It cannot tell you that you keep breaking your
anchor because you are afraid of being hit.

That split is the whole design. Truth from the engine, diagnosis from the model.

## What it measures

The unit of skill in backgammon is **error rate**: equity thrown away per
decision. Multiplied by 500 that is **PR (Performance Rating)**, the number
tournament players quote.

| PR | |
|---|---|
| under 2.5 | world class |
| 2.5 – 5 | expert |
| 5 – 7.5 | advanced |
| 7.5 – 10 | intermediate |
| 10 – 15 | casual |
| 15+ | beginner |

Winning open tournaments realistically means getting under about 5.

Three things are reported separately, because they are different skills:

- **Chequer play** and **cube play** are split. Cube errors are where matches
  are actually lost, and averaging them into one number hides that.
- **Missed doubles are counted.** A player who rolls when they should have
  doubled leaves no cube action in the record at all, so reviewing only your
  moves makes this leak invisible. It is often the single most expensive habit
  a decent player has — a real profile from testing showed perfect chequer play
  (0.000 equity lost over 20 moves) alongside 2.53 lost across 19 missed
  doubles.
- **Luck is separated from skill.** gnubg measures dice fortune in equity, so a
  match you lost with a low PR and negative luck is reported as what it was.
  Players who cannot tell bad luck from bad play cannot improve.

Errors are grouped by game phase (opening, middle game, race, bear-off, back
game) and tagged when you were on the bar, so the report says *where* your
equity goes rather than just how much.

Every finding cites a position ID you can paste into gnubg or XG to replay it.

## Install

GNU Backgammon does the real work, so it has to be installed:

```bash
sudo apt-get install gnubg        # Debian / Ubuntu
brew install gnubg                # macOS
```

Then:

```bash
pip install -e .
```

Coaching uses the Claude API. Either export `ANTHROPIC_API_KEY`, or run
`ant auth login`. Without credentials everything still works — you get the full
engine analysis, just not the written review.

## Use

```bash
bgcoach play                        # a 5-point match against world_class
bgcoach play --length 7 --level grandmaster
bgcoach play --instant              # grade every move as you play
bgcoach play --question "was my cube handling at 4-away sound?"

bgcoach review match.mat            # analyse a match from XG, Galaxy, GridGammon
bgcoach review match.sgf --player 1
bgcoach history                     # PR over time
```

Levels: `beginner`, `casual`, `intermediate`, `advanced`, `expert`,
`world_class`, `supremo`, `grandmaster`. The weaker levels add evaluation noise
rather than only searching less deeply, so they play like a fallible human
rather than a stupid one. **Analysis is always at full strength**, whatever the
opponent is set to — a weak sparring partner never means a weak review.

### While you play

```
  <enter> or r     roll
  d                double
  t / p            take / pass
  24/18 13/11      play a move (bar/20 and 6/off also work)
  ?                ask the engine (recorded as an assisted move)
  pip              pip counts
  q                resign and go to the review
```

You move **blind** by default — the engine's ranking is not shown before you
commit, because a trainer that shows you the answer first is a calculator. `?`
overrides it when you genuinely want to be shown, and the move is marked as
assisted so the review knows.

Feedback is deferred to the end by default, which is tournament conditions.
`--instant` grades each move as you play, for study sessions.

## Tracking progress

Every match is saved to `./matches/`. `bgcoach history` shows PR over time,
split into chequer and cube, and says whether you are actually improving. PR
over a single short match is noisy; the trend is the signal.

## Development

```bash
python -m pytest tests/ -q
```

The tests that matter most pin facts about gnubg that the analysis rests on and
which would otherwise fail silently:

- **Player 0 is `X` in the match record.** gnubg's `match-info` names do not
  reliably follow `set player N name`, so identity is carried by the X/O token
  alone. Reading it backwards would attribute every one of your errors to the
  bot and produce a confident review of mistakes you never made.
- **`board[1]` is the player on roll**, `board[0]` the opponent — each in their
  own numbering, where your 24-point is their 1-point.
- **A correct no-double is not a decision.** Counting every position where
  rolling on was right would dilute the error rate towards zero.
- **The play loop terminates.**

## Limitations

- Analysis is 2-ply, not rollouts. That is strong enough that the errors it
  reports are real, but a handful of close positions would flip under a full
  rollout. For a position that matters, roll it out in gnubg directly.
- The engine's own cube handling below `world_class` is deliberately noisy.
- Money-game play and match play differ in cube strategy; this trains match
  play, which is what tournaments are.
