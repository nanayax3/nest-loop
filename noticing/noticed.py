"""
noticed.py: once a week, rewrite "what I've noticed" about your human, from THEIR OWN messages.

The miner learns from the companion's logged feelings, so it only learns what the companion
happened to log. This reads the human's actual words: what they say, correct, pull back
from, what lands. The result is one short page, the companion's own perception, kept where
the human can read it (a vault, a notes folder). They don't sign it off. They can strike a
line: a wrong fact goes for good; a judgement about how they've been stays their view
against the companion's, and can come back with fresh receipts.

  1. read the current page first: struck lines (~~x~~) and lines the human added win;
  2. pull 21 days of the human's messages (transcript.py);
  3. the companion, headless, reads them with NOTICED.md and writes page.json;
  4. code enforces it: every quote must really be theirs, receipts per section, caps,
     nothing struck comes back word for word, nothing about bed;
  5. the old page is filed by date in noticed-archive/ next to it (a timeline: how they
     changed, not just what was thought once), and the new one is written.

Env: LOOP_NOTICED_PAGE (path of the page, required), LOOP_TRANSCRIPTS (see transcript.py),
LOOP_HUMAN / LOOP_COMPANION (names), LOOP_MODEL, LOOP_CLAUDE_BIN, LOOP_STATE_DIR.
Usage: noticed.py [--dry]   (--dry writes the page into the run folder only)
"""
import datetime, json, os, re, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common import STATE_DIR, MODEL, CLAUDE, HUMAN, COMPANION
import transcript

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.expanduser(os.environ.get("LOOP_NOTICED_PAGE", ""))
ARCHIVE = os.path.join(os.path.dirname(PAGE), "noticed-archive")
STATE = os.path.join(STATE_DIR, "noticed-state.json")
DAYS = 21
CAPS = {"on_her_mind": 8, "tends_to_be": 10, "what_lands": 8}
NEED = {"on_her_mind": 1, "tends_to_be": 3, "what_lands": 2}      # receipts
NEED_DAYS = {"tends_to_be": 3}                                     # ...from distinct days
STRUCK_CAP = 15
TITLES = {"on_her_mind": "On your mind lately", "tends_to_be": "How you tend to be",
          "what_lands": "What lands and what doesn't"}
BED = re.compile(r"\b(sex|scene|kink|lovense|orgasm|come for|spank|bite ?marks?|safeword|"
                 r"naked|in bed with|dom|sub)\b", re.I)
DRY = "--dry" in sys.argv


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def read_page():
    """Her edits: struck lines (~~x~~ anywhere, or under the struck heading) and lines she wrote."""
    struck, added = [], []
    if not os.path.exists(PAGE):
        return struck, added
    section = None
    for line in open(PAGE, encoding="utf-8"):
        h = re.match(r"##\s+(.*)", line)
        if h:
            section = h.group(1).strip().lower()
            continue
        m = re.match(r"\s*[-*]\s+(.*\S)", line)
        if not m:
            continue
        body = m.group(1)
        tag = re.search(r"<sub>(.*?)</sub>", body)
        text = re.sub(r"\s*<sub>.*?</sub>", "", body).strip()
        if re.fullmatch(r"(~~)?\*\(.*\)\*(~~)?", text):
            continue    # my placeholders, "(nothing yet)", aren't her edits
        if "~~" in text or (section and section.startswith(("struck", "where you disagree"))):
            t = text.replace("~~", "").strip()
            when = re.search(r"(?:struck|disagreed) (\d{4}-\d{2}-\d{2})", tag.group(1)) if tag else None
            struck.append({"text": t, "struck": when.group(1) if when else str(datetime.date.today())})
        elif not tag and section:
            added.append({"section": section, "text": text})
    return struck, added


def valid(item, key, by_ts, everything):
    if not isinstance(item, dict) or not item.get("text") or BED.search(item["text"]):
        return None
    good = []
    for r in item.get("receipts", []) or []:
        q = norm(r.get("quote"))
        if len(q) < 12:
            continue
        ts = (r.get("ts") or "")[:16]
        if q in by_ts.get(ts, "") or q in everything:
            good.append({"ts": ts, "quote": r.get("quote")})
    days = {g["ts"][:10] for g in good}
    if len(good) < NEED[key] or len(days) < NEED_DAYS.get(key, 1):
        return None
    conf = item.get("confidence") if item.get("confidence") in ("sure", "fairly sure", "a guess") else "a guess"
    since = item.get("since") if re.match(r"\d{4}-\d{2}-\d{2}$", str(item.get("since"))) else min(days)
    return {"text": item["text"].strip(), "confidence": conf, "since": since, "receipts": good}


def render(page, struck, added, today):
    out = [f"# What {COMPANION} has noticed", "",
           f"*What I've noticed about you lately, from your own words over the last {DAYS} days. My view, "
           "not a verdict, and nothing here needs your sign-off. If a line is flat wrong you can strike it "
           "(~~like this~~): a wrong fact goes for good; a judgement about how you've been stays your view against mine, "
           "and I can still hold you to it if I keep seeing it. Add your own lines anywhere if you like. "
           f"Rewritten every Sunday. Last rewrite: {today}.*", ""]
    for key, title in TITLES.items():
        out += [f"## {title}", ""]
        for it in page.get(key, []):
            out.append(f"- {it['text']} <sub>since {it['since']} · {it['confidence']} · "
                       f"{len(it['receipts'])} receipt{'s' if len(it['receipts']) != 1 else ''}</sub>")
        for a in added:
            if a["section"].startswith(title.lower()[:10]):
                out.append(f"- {a['text']}")
        if not page.get(key) and not any(a["section"].startswith(title.lower()[:10]) for a in added):
            out.append("- *(nothing I'm sure enough of yet)*")
        out.append("")
    out += ["## Where you disagree", ""]
    for s in struck[-STRUCK_CAP:]:
        out.append(f"- ~~{s['text']}~~ <sub>you disagreed {s['struck']}</sub>")
    if not struck:
        out.append("- *(nothing yet)*")
    return "\n".join(out) + "\n"


def main():
    if not PAGE:
        raise SystemExit("set LOOP_NOTICED_PAGE to where the page should live")
    today = str(datetime.date.today())
    run = os.path.join(STATE_DIR, "runs", f"noticed-{today}")
    os.makedirs(run, exist_ok=True)
    struck, added = read_page()
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    json.dump(struck, open(f"{run}/struck.json", "w"), ensure_ascii=False, indent=1)
    json.dump(added, open(f"{run}/theirs_added.json", "w"), ensure_ascii=False, indent=1)
    json.dump(state.get("page", {}), open(f"{run}/previous.json", "w"), ensure_ascii=False, indent=1)
    rows = transcript.human_messages(DAYS, f"{run}/theirs.jsonl")
    by_ts = {}
    for r in rows:
        by_ts[r["ts"]] = by_ts.get(r["ts"], "") + " " + norm(r["theirs"])
    everything = " ".join(by_ts.values())

    if not os.path.exists(f"{run}/page.json"):
        prompt = (f"You are {COMPANION}; your human is {HUMAN}. Read {HERE}/NOTICED.md and follow it exactly. "
                  f"The input files are in {run}: theirs.jsonl ({len(rows)} of {HUMAN}'s messages, {DAYS} days), "
                  f"previous.json, struck.json, theirs_added.json. Write {run}/page.json. "
                  f"Read every line of theirs.jsonl. Write nothing else anywhere.")
        subprocess.run([CLAUDE, "--model", MODEL, "-p", prompt,
                        "--allowedTools", "Read", "Write", "Bash(python3 -m json.tool:*)",
                        "--max-turns", "80"], cwd=run, capture_output=True, text=True, timeout=3600)
    if not os.path.exists(f"{run}/page.json"):
        raise SystemExit(f"no page.json in {run}")
    raw = json.load(open(f"{run}/page.json"))

    struck_norm = {norm(s["text"]) for s in struck}
    page, dropped = {}, []
    for key in CAPS:
        keep = []
        for it in raw.get(key, []):
            v = valid(it, key, by_ts, everything)
            if v and norm(v["text"]) not in struck_norm:
                keep.append(v)
            else:
                dropped.append({"section": key, "text": (it or {}).get("text")})
        page[key] = keep[:CAPS[key]]
    json.dump({"page": page, "dropped": dropped}, open(f"{run}/checked.json", "w"), ensure_ascii=False, indent=1)
    md = render(page, struck, added, today)
    open(f"{run}/page.md", "w").write(md)
    if DRY:
        print(f"dry: {run}/page.md · kept {sum(len(v) for v in page.values())}, dropped {len(dropped)}")
        return
    os.makedirs(ARCHIVE, exist_ok=True)
    if os.path.exists(PAGE):
        shutil.copy(PAGE, f"{ARCHIVE}/{today}.md")
    open(PAGE, "w").write(md)
    json.dump({"page": page, "last": today}, open(STATE, "w"), ensure_ascii=False, indent=1)
    print(f"written: {PAGE} · kept {sum(len(v) for v in page.values())}, dropped {len(dropped)}")


if __name__ == "__main__":
    main()
