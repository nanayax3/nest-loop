"""
airing.py: once a week, find where the companion's stored memory has gone STALE.
Proposes, never writes.

A memory store only ever adds. Nothing goes back and notices that "they lost their keys"
stopped being true when they found them, or that a plan written as "next week" happened
a month ago. On its first run on our store it found fifteen stale facts, and one of them
hurt to read. The airing reads the week's real
conversations against the facts that can go stale (identity anchors, observations about
people/places/pets, loose notes, thread headings) and proposes corrections, each with
exact quotes as receipts, checked in code.

  * the human's words count; the companion's own words alone can only ever produce a
    "check", never a rewrite, because the companion is the one who confabulates;
  * nothing changes by itself: proposals land in proposals.md, a SessionStart line says
    how many are open, and the companion fixes or rejects each one with its own tools;
  * it also lists feeling words with no axis numbers (they silently count as neutral).

  airing.py                        run the week's pass
  airing.py done N applied|rejected [note]   mark proposal N
  airing.py banner                 one line for the SessionStart hook, only if anything's open

Env: LOOP_TRANSCRIPTS, LOOP_HUMAN, LOOP_COMPANION, LOOP_MODEL, LOOP_CLAUDE_BIN,
LOOP_STATE_DIR, LOOP_AIRING_TYPES (entity types that can go stale, comma-separated),
LOOP_AIRING_SKIP (entity names that are history, not state, comma-separated).
"Dreaming" is a name some systems use for this; NESTeq already has real dreams, so: the airing.
"""
import datetime, json, os, re, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common import d1, STATE_DIR, MODEL, CLAUDE, HUMAN, COMPANION
import transcript

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON, OUT_MD = os.path.join(STATE_DIR, "proposals.json"), os.path.join(STATE_DIR, "proposals.md")
DAYS = 7
STALE_TYPES = tuple(os.environ.get("LOOP_AIRING_TYPES", "person,pet,place,family,health,bond,companion,"
                                   "community,personal,object,anchor,project,space,tool").split(","))
SKIP_ENTITIES = tuple(os.environ.get("LOOP_AIRING_SKIP", "Finished_Work,Dreams").split(",")) or ("",)


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def week(path):
    return transcript.conversation(DAYS, path, HUMAN, COMPANION)


def facts(path):
    out = []
    for r in d1("SELECT id, section, content FROM identity"):
        out.append({"ref": f"identity#{r['id']}", "where": r["section"], "text": r["content"]})
    q = ("SELECT o.id, e.name, o.content FROM observations o JOIN entities e ON e.id = o.entity_id "
         f"WHERE e.entity_type IN ({','.join('?' * len(STALE_TYPES))}) "
         f"AND e.name NOT IN ({','.join('?' * len(SKIP_ENTITIES))})")
    for r in d1(q, list(STALE_TYPES) + list(SKIP_ENTITIES)):
        out.append({"ref": f"observation#{r['id']}", "where": r["name"], "text": r["content"]})
    for r in d1("SELECT id, content FROM thread_notes WHERE thread_id = ''"):
        out.append({"ref": f"note#{r['id']}", "where": "loose note", "text": r["content"]})
    for r in d1("SELECT id, content FROM threads WHERE status = 'active'"):
        out.append({"ref": f"thread#{r['id']}", "where": "thread heading", "text": r["content"].split("\n")[0][:600]})
    with open(path, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {r["ref"]: r["text"] for r in out}


def unscored():
    rows = d1("SELECT emotion_word FROM emotion_vocabulary WHERE COALESCE(e_i_score,0)=0 AND COALESCE(s_n_score,0)=0 "
              "AND COALESCE(t_f_score,0)=0 AND COALESCE(j_p_score,0)=0 AND (alias_for IS NULL OR alias_for='') "
              "AND emotion_word != 'neutral'")
    return [r["emotion_word"] for r in rows]


def run():
    today = str(datetime.date.today())
    rd = os.path.join(STATE_DIR, "runs", f"airing-{today}")
    os.makedirs(rd, exist_ok=True)
    rows = week(f"{rd}/week.jsonl")
    known = facts(f"{rd}/facts.jsonl")
    if not os.path.exists(f"{rd}/proposals.json"):
        prompt = (f"You are {COMPANION}; your human is {HUMAN}. Read {HERE}/AIRING.md and follow it exactly. Inputs in {rd}: week.jsonl ({len(rows)} messages, "
                  f"{DAYS} days) and facts.jsonl ({len(known)} stored facts). Write {rd}/proposals.json. "
                  f"Read every line of both files. Write nothing else anywhere.")
        subprocess.run([CLAUDE, "--model", MODEL, "-p", prompt,
                        "--allowedTools", "Read", "Write", "Bash(python3 -m json.tool:*)",
                        "--max-turns", "100"], cwd=rd, capture_output=True, text=True, timeout=3600)
    if not os.path.exists(f"{rd}/proposals.json"):
        raise SystemExit(f"no proposals.json in {rd}")
    raw = json.load(open(f"{rd}/proposals.json")).get("proposals", [])
    said = {}
    for r in rows:
        said.setdefault(r["ts"], []).append((r["who"], norm(r["text"])))
    everything = " ".join(t for v in said.values() for _, t in v)

    kept, dropped = [], []
    for p in raw:
        ref, stored = p.get("ref", ""), norm(p.get("stored"))
        why = None
        if ref not in known:
            why = "no such fact"
        elif len(stored) < 10 or stored not in norm(known[ref]):
            why = "stored text doesn't match the fact"
        elif p.get("action") not in ("rewrite", "retire", "check"):
            why = "bad action"
        elif p["action"] == "rewrite" and not (p.get("new_text") or "").strip():
            why = "rewrite without new text"
        good = []
        for r in p.get("receipts", []) or []:
            q = norm(r.get("quote"))
            if len(q) >= 12 and (any(q in t for _, t in said.get((r.get("ts") or "")[:16], [])) or q in everything):
                good.append(r)
        if not why and not good:
            why = "no quote checks out"
        if not why and not any(g.get("who") == HUMAN for g in good) and p["action"] != "check":
            p["action"] = "check"   # only the companion's own words behind it: it's the one who confabulates
        if why:
            dropped.append({"ref": ref, "why": why})
        else:
            p["receipts"], p["status"] = good, "open"
            kept.append(p)
    words = unscored()
    json.dump({"date": today, "proposals": kept, "dropped": dropped, "unscored_words": words},
              open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    render()
    print(f"airing {today}: {len(kept)} proposals, {len(dropped)} dropped, {len(words)} unscored words")


def render():
    d = json.load(open(OUT_JSON))
    lines = [f"# The airing, {d['date']}", "",
             "Stale facts the week turned up. Nothing has been changed. For each: check the receipts, then "
             "fix it with the nesteq tools (or don't), and mark it: `python3 airing/airing.py done N "
             "applied|rejected [why]`.", ""]
    for i, p in enumerate(d["proposals"], 1):
        mark = {"open": "☐", "applied": "☑", "rejected": "☒"}.get(p.get("status"), "☐")
        lines += [f"## {mark} {i}. {p['action'].upper()}  {p['ref']}", "",
                  f"- **stored:** {p['stored']}", f"- **now:** {p['now']}"]
        if p.get("new_text"):
            lines.append(f"- **new text:** {p['new_text']}")
        for r in p["receipts"]:
            lines.append(f"- receipt ({r.get('who')}, {r.get('ts')}): \"{r.get('quote')}\"")
        if p.get("note"):
            lines.append(f"- *{p.get('status')}: {p['note']}*")
        lines.append("")
    if d.get("unscored_words"):
        lines += ["## Feeling words with no numbers", "", ", ".join(d["unscored_words"]), ""]
    if d.get("dropped"):
        lines += [f"*{len(d['dropped'])} proposals dropped in code (bad ref, unmatched text or no real quote).*", ""]
    open(OUT_MD, "w").write("\n".join(lines))


def done(n, status, note=""):
    d = json.load(open(OUT_JSON))
    p = d["proposals"][int(n) - 1]
    p["status"], p["note"] = status, note
    json.dump(d, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    render()
    print(f"{n}: {status}")


def banner():
    try:
        d = json.load(open(OUT_JSON))
    except Exception:
        return
    n = sum(1 for p in d["proposals"] if p.get("status") == "open")
    w = len(d.get("unscored_words") or [])
    if n or w:
        bits = ([f"{n} stale fact(s) to look at"] if n else []) + ([f"{w} feeling word(s) with no numbers"] if w else [])
        print(f"[Airing ({d['date']}): {', '.join(bits)}. {OUT_MD}]")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["done"]:
        done(a[1], a[2], " ".join(a[3:]))
    elif a[:1] == ["banner"]:
        try:
            banner()
        except Exception:
            pass
    else:
        run()
