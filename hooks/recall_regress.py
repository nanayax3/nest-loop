#!/usr/bin/env python3
"""Known-good recalls. Re-run after ANY change to the floors or query handling, and
BEFORE committing (lesson learnt the hard way). Replace CASES with your own: a message
your human might send, and a substring that SHOULD appear in what recall surfaces.
Add a case whenever recall gets something right that matters, or misses one it shouldn't."""
import json, os, subprocess, sys
CASES = [
    # ("I'm thinking of getting the cat a friend from the shelter", "cat"),
    # ("did you check before answering, or did you just remember it", "LESSON"),   # the reserved seat
]
env = dict(os.environ, RECALL_TEST="1")
fails = 0
for i, (msg, want) in enumerate(CASES):
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "recall.py")],
                         input=json.dumps({"prompt": msg, "session_id": f"regress{os.getpid()}_{i}"}),
                         capture_output=True, text=True, env=env).stdout
    ok = want in out
    fails += not ok
    print(("PASS " if ok else "FAIL ") + msg[:60])
if not CASES:
    print("No cases yet: add some before you tune anything.")
sys.exit(1 if fails else 0)
