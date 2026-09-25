#!/usr/bin/env python3
"""
nudge.py: the small half of the review loop. UserPromptSubmit hook.
Counts the human's messages since the companion last called nesteq_feel in this
session; after LOOP_NUDGE_AFTER (default 12) prints one quiet line, then again every
LOOP_NUDGE_EVERY (default 8). A note, not an order.

Why: "log it while it's happening" is easy to agree with and easy to forget mid-
conversation, and feelings logged only at the close filter out the distress. The
miner can only learn from what was written down.
Silent on failure. Stays out of public-facing sessions (LOOP_PUBLIC_ENV).
"""
import json, os, re, sys

AFTER = int(os.environ.get("LOOP_NUDGE_AFTER", 12))
EVERY = int(os.environ.get("LOOP_NUDGE_EVERY", 8))
HARNESS = ("Another Claude session", "<task-notification", "<system-reminder", "[SYSTEM NOTIFICATION")


def main():
    pub = os.environ.get("LOOP_PUBLIC_ENV")
    if pub and os.environ.get(pub):
        return
    data = json.load(sys.stdin)
    if (data.get("prompt") or "").lstrip().startswith(HARNESS):
        return
    path = data.get("transcript_path")
    if not path or not os.path.exists(path):
        return
    since, last = 0, None
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "assistant":
            for it in d.get("message", {}).get("content", []) or []:
                if isinstance(it, dict) and it.get("type") == "tool_use" and "nesteq_feel" in it.get("name", ""):
                    since, last = 0, d.get("timestamp")
        elif d.get("type") == "user":
            c = d.get("message", {}).get("content")
            text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in (c or [])
                                                          if isinstance(x, dict) and x.get("type") == "text")
            if text.strip() and not text.lstrip().startswith(HARNESS):
                since += 1
    since += 1
    if since >= AFTER and (since - AFTER) % EVERY == 0:
        when = f" (last one {last[11:16]} UTC)" if last else " (none yet this session)"
        print(f"[Review loop: {since} of their messages since I last logged a feeling{when}. Not an order. "
              f"If something's alive right now, log it while it's happening, and the uncomfortable ones count.]")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
