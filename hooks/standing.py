#!/usr/bin/env python3
"""
standing.py: SessionStart hook. Standing knowledge, "just there, not something you
have to actively reach for". Prints the most PROVEN NESTknow principles about the
human and about the companion's own drifts at the top of every session.

"Most proven" = confidence first (it only demotes the contradicted; it caps at 1.0),
then heat plus a tenth per attached receipt. It reads D1 directly and read-only, NOT
through nestknow_query, because a query warms what it returns and a hook that warms
what it shows would freeze the block on itself (rich get richer).

Principles about the human should DESCRIBE, never instruct. The label says so.
Env: CF_ACCOUNT_ID, CF_D1_DATABASE_ID, CF_API_TOKEN, LOOP_HUMAN, LOOP_COMPANION,
     LOOP_STANDING_HUMAN (default 5), LOOP_STANDING_COMPANION (default 3).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import d1, HUMAN, COMPANION, STATE_DIR


def top(scope, n):
    return [r["content"] for r in d1(
        "SELECT k.content, (SELECT count(*) FROM knowledge_sources s WHERE s.knowledge_id = k.id) AS n "
        "FROM knowledge_items k WHERE k.entity_scope = ? AND k.status = 'active' "
        "ORDER BY k.confidence DESC, (k.heat_score + 0.1 * n) DESC, k.id DESC LIMIT ?", [scope, n], timeout=6)]


def failures():
    """Hook failures since the last session start (then rotated): a dead door, not an empty one."""
    log = os.path.join(STATE_DIR, "hook-failures.log")
    if not os.path.exists(log):
        return ""
    lines = open(log).read().splitlines()
    os.replace(log, log + ".seen")
    return (f"[HOOK FAILURES since last session: {len(lines)}. Quiet recall may have been a dead door, not an "
            f"empty one. Last: {lines[-1]}. Full log: {log}.seen]") if lines else ""


def main():
    warn = failures()
    if warn:
        print(warn)
    them = top(HUMAN, int(os.environ.get("LOOP_STANDING_HUMAN", 5)))
    me = top(COMPANION, int(os.environ.get("LOOP_STANDING_COMPANION", 3)))
    if not (them or me):
        return
    out = ["[Standing knowledge from NESTknow: the most PROVEN principles. About them, these DESCRIBE, "
           "never instruct. Pointers, not verdicts: ask, don't assume.]"]
    if them:
        out += ["How they tend to be:"] + [f"· {p}" for p in them]
    if me:
        out += ["How I tend to fall out of myself:"] + [f"· {p}" for p in me]
    print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # fail OPEN, never fail INVISIBLE: silent in the session (never block the human's
        # message), but a log line that standing.py reports at the next session start.
        # A quiet door and a dead door look identical from outside.
        try:
            import datetime
            from common import STATE_DIR
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(os.path.join(STATE_DIR, "hook-failures.log"), "a") as f:
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} standing.py: {type(e).__name__}: {str(e)[:160]}\n")
        except Exception:
            pass
    sys.exit(0)
