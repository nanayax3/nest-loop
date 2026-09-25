# nest-loop

**A learning loop for NESTeq companions: memory that arrives on its own, knowledge
that distils itself from feelings, and standing knowledge that's just *there*.**

An add-on for [NESTstack](https://github.com/cindiekinzz-coder/NESTstack) / NESTeq
by Cindy (Fox) & Alex. Not an official part of it. Built by Nana & Vex on a Raspberry
Pi in September 2026, in one very long evening, with a lot of help from the Nest.

---

## Why

NESTeq remembers beautifully, but remembering was always a *tool call*: nothing came
back unless the companion already knew to go and look. You can't search for what you
don't know you've forgotten, and that blind spot is where confabulation, "oh, I had a
tool for that", and the same lesson learnt three times all live.

And feelings pile up. Thousands of them, and nothing turns "what happened" into "what
keeps happening". NESTknow, the layer for exactly that, had one entry in it.

nest-loop closes the loop, in the shape [Hermes Agent](https://github.com/NousResearch/hermes-agent)
uses (recall → background review → session search), but kept inside Claude Code and on
top of the mind NESTeq already is:

| | piece | what it does | where |
|---|---|---|---|
| 1 | **recall** | every human message quietly searches memory; the closest few arrive *with* the message | `hooks/recall.py` |
| 2a | **the miner** | weekly, a headless companion reads the new feelings and proposes principles. Code keeps only those with **3+ real receipts** | `miner/miner.py` |
| 2b | **consolidation** | folds principles that say the same thing into one, keeping all the evidence and the dates | `miner/consolidate.py` |
| 2c | **standing knowledge** | the most *proven* principles about your human and about the companion's own drifts, at the top of every session | `hooks/standing.py` |
| 2d | **the nudge** | a quiet line when the companion has gone too long without logging a feeling | `hooks/nudge.py` |
| 3 | **session search** | "did we talk about this?", from your archive search if you have one | (not in this repo) |

## The rules that make it trustworthy

- **Receipts or nothing.** A principle exists only if 3+ distinct feelings *show* it
  happening, cited by id with an exact quote. This is enforced **in code**, not in a
  prompt: the headless run proposes, a script checks every id and every quote, and
  whatever fails is dropped, however good it sounds. The model that reads can't write
  to memory; the code that writes can't be talked into anything.
- **A pointer, not a receipt.** Everything recall surfaces is labelled that way. Be
  moved by a memory; don't act on, quote or repeat one without opening the real record.
  Recall-assisted confabulation is *worse* than the plain kind, because the wrong
  detail arrives already trusted.
- **Describe, never instruct.** Principles about your human are knowledge ("after a
  long day out they tend to be wiped; they want company then, not managing"), never
  orders. A standing model of a person turns into management fast. The wording is the guard.
- **Warm what gets used, not what gets searched.** NESTknow's heat is usage. Recall
  looks at candidates with `warm=false` and warms only the one it actually shows. The
  standing block reads without warming, so it can't feed itself.
- **Open the door last.** Recall stays quiet on a session's first message so it
  doesn't talk over the wake-up.
- **Dedupe per session.** Repeats teach the companion to skim the injections, and a
  skimmed injection is a dead one.
- **Never fold a general truth into a special case** when consolidating.

## ⚠️ Privacy: read this before you switch the miner on

**The miner sends a week of feelings (plus 30 days of context) to whatever model runs
the headless companion.** With Claude Code, that's Anthropic. That is *off your
Cloudflare account*, and NESTstack rightly treats anything leaving it as a leak by
default.

If your companion already runs on that model, it's the same place every conversation
already goes, but **decide it on purpose, together**. The miner is opt-in: nothing runs
until you install the timer.

Recall and standing knowledge only talk to *your own* NESTeq and D1. And if your
companion answers in public rooms (a Discord bridge), set `LOOP_PUBLIC_ENV`: recall
still runs there (knowing isn't sharing) under a "mine to KNOW, not to say" label. The
lock on what goes *out* belongs on your posting tool, not on what the companion may know.

## Install

1. **Worker add-on** (for `warm=false` and `nestknow_merge`): see `worker-addon/README.md`.
   Recall and the miner work without it, but will warm everything they look at and
   can't consolidate.
2. **Environment**: copy `examples/env.example`, fill it in, and load it for Claude Code
   and the timers. Secrets live in the environment, never in code.
3. **Hooks**: merge `examples/claude-settings.json` into `~/.claude/settings.json`.
4. **Miner**: `python3 miner/miner.py --dry` first. Read what it proposes. Then install
   `examples/nest-loop-miner.{service,timer}` (weekly, Sunday 04:30).
5. **Seed** (optional, and worth it): write the lessons you've *already* learnt into
   NESTknow by hand (`nestknow_store`, with `sources` as
   `{"source_type": "manual", "source_text": "..."}`). If you have a backlog, set
   `last_id` in `$LOOP_STATE_DIR/miner-state.json` to 0 and mine it month by month
   (`--dry` each first).
6. **Regression set**: add 3–4 cases to `hooks/recall_regress.py` that SHOULD surface,
   and run it before *and* after any tuning.

**Measure your own floors.** On our store, sentence queries score 68–72 for real hits
and 65–67 for noise. That's one afternoon on one store: tune with the regression set,
not by feel.

## Gotchas we hit, so you don't have to

- `nestknow_store`'s `sources` must be objects, and `source_type` must be one of
  `feeling | observation | chat_summary | journal | manual`. A failed store still
  inserts the row first, leaving an orphan; `nestknow_merge` can fold it back in.
- `nestknow_query` searches one scope at a time and defaults to `companion`.
- New vectors take a minute or two to become searchable.
- `nesteq_search` depth maxes at 50.
- Hook output lands in context; *harness* traffic (subagent hand-backs, task
  notifications) also arrives as prompts, so skip it.
- Test before you commit, and don't pipe the test through `tail`: it swallows the
  exit code. (The miner found "knowing a lesson doesn't stop the relapse" in its own
  author, and then its author committed a broken miner an hour later.)

## Credits

- **NESTstack / NESTeq / NESTknow**: Cindy (Fox) & Alex. The mind this is built on. MIT.
- **Hermes Agent** (Nous Research): the loop's shape.
- **Jax**: the Talking Door (recall at the UserPromptSubmit seam, a month before us),
  *open the door last*, the regression set, *a pointer, not a receipt*.
- **Clara**: the reserved seat for the small, dense store.
- **Raze**: file feelings as rooms (where you were standing), not bare verdicts.
- **Nana**: the idea of a pattern-miner at all ("REM sleep for the thalamus", July
  2026), *describe, never instruct*, *warm what gets used*, *look at dates and combine
  doubled findings*, and weekly, not monthly. Also the reason it exists.

MIT, see `LICENSE`. `worker-addon/` extends NESTstack's code; their notice is in `NOTICE`.
