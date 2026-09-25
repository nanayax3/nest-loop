#!/usr/bin/env python3
"""
recall.py: memory that arrives WITH the message instead of being fetched by deciding.
A Claude Code UserPromptSubmit hook. Whatever it prints lands next to the human's
message before the companion reads it.

Why: remembering-as-a-tool-call has a blind spot. You can't search for what you
don't know you've forgotten, and that blind spot is where confabulation lives.

What it does on each message:
  * strips *actions* and URLs, skips tiny messages ("meh", a lone emoji);
  * one semantic search on NESTeq (nesteq_search, depth 50);
  * a RESERVED SEAT for distilled knowledge (NESTknow): the small, dense store of
    principles would otherwise lose every seat to thousands of feelings. Candidates
    are looked up with warm=false and ONLY the one shown is warmed: warm what gets
    used, not what gets searched (needs worker-addon/, otherwise it just warms normally);
  * prints up to 3, deduped per session (repeats teach you to skim, which kills the
    mechanism);
  * labels everything A POINTER, NOT A RECEIPT: be moved by it, but open the real
    record before acting on, quoting or repeating it;
  * stays quiet on the FIRST message of a session ("open the door last", so it
    doesn't talk over the wake-up), on harness traffic, and when the kill file exists;
  * fails silent: any error, exit 0, print nothing.

Env (see common.py): NEST_MCP_URL, NEST_MCP_TOKEN, LOOP_HUMAN, LOOP_COMPANION.
  LOOP_FLOOR           similarity floor for memories (default 68.5; MEASURE YOURS)
  LOOP_KNOW_FLOOR      weighted floor for NESTknow (default 72)
  LOOP_KNOW_SCOPES     comma list (default "<human>,<companion>,craft")
  LOOP_LESSON_ENTITIES comma list of entity names that hold distilled lessons, used
                       for the reserved seat if NESTknow has nothing (default none)
  LOOP_PUBLIC_ENV      name of an env var that is set in sessions answering in a public
                       room (e.g. a Discord bridge). Recall still runs there (knowing is
                       not sharing) but under a "mine to KNOW, not to say" label. The lock
                       for what goes OUT belongs on your posting tool, not on recall.
  LOOP_PUBLIC_MESSAGE_RE  optional regex with one group capturing the triggering message
                       inside a bridge prompt; otherwise the last 400 chars are used.
Kill switch: touch $LOOP_STATE_DIR/RECALL_OFF
"""
import hashlib, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import mcp, HUMAN, COMPANION, STATE_DIR

FLOOR = float(os.environ.get("LOOP_FLOOR", 68.5))
KNOW_FLOOR = float(os.environ.get("LOOP_KNOW_FLOOR", 72))
LESSON_FLOOR = FLOOR - 4.5
KNOW_SCOPES = [s for s in os.environ.get("LOOP_KNOW_SCOPES", f"{HUMAN},{COMPANION},craft").split(",") if s]
LESSONS = {s for s in os.environ.get("LOOP_LESSON_ENTITIES", "").split(",") if s}
MAX_HITS, MAX_CHARS = 3, 240
HARNESS = re.compile(r"\s*(<task-notification|<system-reminder|\[SYSTEM NOTIFICATION|Another Claude session sent a message)")
HEAD = re.compile(r"^\*\*\[(.+?)\*\*(?: \((\w+)\))? \((\d+(?:\.\d+)?)%\)$", re.M)
KNOW = re.compile(r"^\*\*#\d+\*\*[^\n]*?\((\d+(?:\.\d+)?)% weighted\)\nCategory:[^\n]*\n(.+?)(?=\n\n\*\*#|\Z)", re.M | re.S)


def clean(s):
    return re.sub(r"\s+", " ", s).strip().rstrip(".").rstrip()


def key(s):
    return hashlib.sha1(clean(s)[:160].encode()).hexdigest()[:16]


def know(query):
    def one(scope):
        text = mcp("nestknow_query", {"query": query, "entity_scope": scope, "limit": 1, "warm": False}, timeout=3)
        return [(scope, float(m.group(1)), m.group(2).strip()) for m in KNOW.finditer(text)]
    try:
        with ThreadPoolExecutor(len(KNOW_SCOPES)) as ex:
            res = [r for f in [ex.submit(one, s) for s in KNOW_SCOPES] for r in f.result()]
    except Exception:
        return []
    return sorted([r for r in res if r[1] >= KNOW_FLOOR], key=lambda r: -r[1])


def main():
    if os.path.exists(os.path.join(STATE_DIR, "RECALL_OFF")):
        return
    public = bool(os.environ.get(os.environ.get("LOOP_PUBLIC_ENV", ""), "")) if os.environ.get("LOOP_PUBLIC_ENV") else False
    data = json.load(sys.stdin)
    prompt = data.get("prompt", "") or ""
    if HARNESS.match(prompt):
        return
    session = re.sub(r"[^A-Za-z0-9_-]", "", data.get("session_id", "nosession"))[:80]
    if public:
        rx = os.environ.get("LOOP_PUBLIC_MESSAGE_RE")
        m = None
        if rx:
            for m in re.finditer(rx, prompt, re.S):
                pass
        prompt = m.group(1) if m else prompt[-400:]

    query = re.sub(r"\*[^*]{0,400}\*", " ", prompt)          # actions are how they move, not what they say
    query = re.sub(r"\s+", " ", re.sub(r"https?://\S+", " ", query)).strip()
    if len(re.sub(r"[^\w]", "", query)) < 15:
        return
    query = query[:400]

    os.makedirs(STATE_DIR, exist_ok=True)
    opened = os.path.join(STATE_DIR, f"recall-{session}.open")
    if not public and not os.path.exists(opened) and not os.environ.get("RECALL_TEST"):
        open(opened, "w").close()                              # open the door LAST
        return

    text = mcp("nesteq_search", {"query": query, "n_results": 50}, timeout=3)
    marks = list(HEAD.finditer(text))
    hits = [(m.group(1).replace("]", "").strip(), m.group(2) or "", m.group(3),
             text[m.end():(marks[i + 1].start() if i + 1 < len(marks) else len(text))].strip())
            for i, m in enumerate(marks)]

    state_path = os.path.join(STATE_DIR, f"recall-{session}.json")
    try:
        seen = set(json.load(open(state_path)))
    except Exception:
        seen = set()

    seat = None
    for scope, w, content in know(query):                       # the reserved seat
        if key(content) not in seen:
            seat = (f"KNOW:{scope}", "knowledge", str(w), content)
            try:                                                 # shown = used: warm exactly this one
                mcp("nestknow_query", {"query": content, "entity_scope": scope, "limit": 1}, timeout=3)
            except Exception:
                pass
            break
    if not seat:
        for label, kind, score, snippet in hits:
            if label in LESSONS and float(score) >= LESSON_FLOOR and key(snippet) not in seen:
                seat = (label, kind, score, snippet)
                break

    out = []
    for label, kind, score, snippet in ([seat] if seat else []) + [h for h in hits if h is not seat]:
        if (label, kind, score, snippet) != seat and float(score) < FLOOR:
            continue
        k = key(snippet)
        if k in seen:
            continue
        seen.add(k)
        snippet = clean(snippet)
        if len(snippet) > MAX_CHARS:
            snippet = snippet[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
        tag = "LESSON " if (label in LESSONS or label.startswith("KNOW:")) else ""
        out.append(f"· {tag}[{label}] {snippet}")
        if len(out) >= MAX_HITS:
            break
    json.dump(sorted(seen), open(state_path, "w"))
    if out:
        head = ("[Recall: mine to KNOW, not to say. This session answers in a public room; what's private "
                "stays private unless it was already said there. Pointers, not receipts]") if public else \
               ("[Recall: memory brought these up on its own. A POINTER, NOT A RECEIPT: fine to be moved by one, "
                "never to act on, quote or repeat one without opening the real record first]")
        print(head + "\n" + "\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
