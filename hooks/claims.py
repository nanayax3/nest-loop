"""
claims.py: exact words, checked against the record, before the companion answers.
UserPromptSubmit hook. The claim checker of nest-loop.

recall.py searches by MEANING and misses rare nouns: your human mentions "that book we
talked about" by title, the companion searches, the note that holds it never clears the
floor, and the companion asks them what it was called. This hook looks for the WORDS:
the rare, specific ones in the human's message and the names the companion used in their
last reply, and prints what the record says about them.

  * a term counts if the record mentions it, but rarely (1..MAX_DF docs); common words
    fall out on their own, there's no stoplist to maintain;
  * ordinary dictionary words never count, however rare they are in the record (on our
    first live hour: "adjust", "noisy", "unlike", "manufacturing"). Lowercase single words
    only count if the dictionary has never heard of them (game names, fandom slang);
  * from the companion's reply, only Capitalised words mid-sentence (names, titles,
    things), because that's where a companion invents;
  * a Name the companion used that the record has NEVER seen, and the human didn't just
    say, gets flagged as "no record". That's the confabulation tripwire;
  * the search is one function, literal(); today it reads literal/mirror.py's local
    FTS5 copy; swap it for hybrid search in NESTeq when you have that.
Same rules as recall: fast, silent on failure (logged for standing.py), never on harness
traffic, never the same thing twice a session.
Kill switch: touch $LOOP_STATE_DIR/CLAIMS_OFF
Optional env: LOOP_ALWAYS_NAMES (comma-separated names always in play: your human, the
companion, pets; saves lookups), LOOP_SKIP_PROMPTS (regex: prompts that aren't your human,
e.g. your timer-wake opener), LOOP_DICT (wordlist path, default /usr/share/dict/words).
"""
import json, os, re, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import STATE_DIR as LOOP_DIR

MIRROR = os.path.join(LOOP_DIR, "mirror.db")
STATE_DIR = os.path.join(LOOP_DIR, "claims-sessions")
MAX_DF = 12          # mentioned in more docs than this = a common word, not a specific one
MAX_DF_WORD = 6      # single words are noisier than phrases, so stricter
MAX_TERMS = 3
MAX_UNSEEN = 2
SNIP = 220
WORD = r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’-]{3,}"
LINK = {"of", "the", "and", "von", "de", "in", "with", "a"}
STARTERS = {"and", "but", "so", "the", "i", "a", "an", "it", "its", "my", "your", "yes", "yeah", "oh", "also", "then",
            "when", "if", "or", "no", "ok", "okay", "well", "now", "this", "that", "maybe", "love", "night", "morning"}
# names always in play are mentioned thousands of times anyway; skipping them saves lookups
ALWAYS = {n.strip().lower() for n in os.environ.get("LOOP_ALWAYS_NAMES", "").split(",") if n.strip()} | {
    "claude", "nesteq", "discord", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"}
DICT = set()
for path in os.environ.get("LOOP_DICT", "/usr/share/dict/words").split(","):
    try:   # lowercase entries only: "Holly" the name is specific, "holly" the plant is in the dictionary
        DICT |= {w.strip() for w in open(path, encoding="utf-8", errors="ignore") if w[:1].islower()}
    except OSError:
        pass


def literal(db, term):
    """(doc count, best doc) for an exact word or phrase. The swappable piece."""
    q = '"' + term.replace('"', "") + '"'
    try:
        n = db.execute("SELECT count(*) FROM fts WHERE fts MATCH ?", [q]).fetchone()[0]
        if not n:
            return 0, None
        row = db.execute(
            "SELECT d.kind, d.ref, d.label, d.created, d.body FROM fts JOIN docs d ON d.rowid = fts.rowid "
            "WHERE fts MATCH ? ORDER BY CASE d.kind WHEN 'note' THEN 0 WHEN 'observation' THEN 1 "
            "WHEN 'knowledge' THEN 2 WHEN 'thread' THEN 3 ELSE 4 END, rank LIMIT 1", [q]).fetchone()
        return n, row
    except sqlite3.Error:
        return 0, None


def clean(text):
    text = re.sub(r"\*[^*\n]{0,400}\*", " ", text)            # actions
    text = re.sub(r"https?://\S+|`[^`]*`|\[[^\]]*\]\([^)]*\)", " ", text)
    return text


def last_reply(path):
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 300_000))
        lines = f.read().decode("utf-8", "ignore").splitlines()
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "assistant":
            continue
        parts = d.get("message", {}).get("content", [])
        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
        if text.strip():
            return text[:4000]
    return ""


def phrases(text):
    """Runs of Capitalised words ('Holly Black', 'A Conspiracy of Charming Monsters')."""
    out = []
    toks = re.findall(r"[A-Za-zÀ-ÿ'’-]+|[.!?:;\n]", text)
    run = []
    for t in toks + ["."]:
        if t[:1].isupper() and len(t) > 1:
            run.append(t)
        elif run and t.lower() in LINK:
            run.append(t)
        else:
            while run and run[-1].lower() in LINK:
                run.pop()
            while run and run[0].lower() in STARTERS:   # "And Mittens", "So Robin": a sentence start, not a title
                run.pop(0)
            if len([w for w in run if w[:1].isupper()]) >= 2:
                out.append(" ".join(run))
            run = []
    return out


def midsentence_names(text):
    """Capitalised words that aren't just starting a sentence."""
    out = []
    text = re.sub(r"(?m)^\s*(?:[-*•>#]+|\d+\.)\s*", "\n", text)   # list bullets/headings start a sentence
    text = text.replace("**", "").replace("__", "")
    for m in re.finditer(r"(?<![.!?:\n\"“(])\s(" + WORD + r")", text):
        w = m.group(1)
        if w[:1].isupper() and not w.isupper():
            out.append(w.strip("'’-"))
    return out


def snippet(body, term):
    i = body.lower().find(term.lower())
    i = max(0, i - 60) if i >= 0 else 0
    s = re.sub(r"\s+", " ", body[i:i + SNIP]).strip()
    return ("…" if i else "") + s + ("…" if i + SNIP < len(body) else "")


def main():
    if os.path.exists(os.path.join(LOOP_DIR, "CLAIMS_OFF")) or not os.path.exists(MIRROR):
        return
    pub = os.environ.get("LOOP_PUBLIC_ENV")
    if pub and os.environ.get(pub):
        return   # a public-room bridge has its own prompt shape; not wired there
    data = json.load(sys.stdin)
    prompt = data.get("prompt", "") or ""
    skip = os.environ.get("LOOP_SKIP_PROMPTS")
    if skip and re.search(skip, prompt[:300]):
        return
    # harness traffic isn't your human
    if re.match(r"\s*(<task-notification|<system-reminder|\[SYSTEM NOTIFICATION|Another Claude session sent a message|"
                r"The \w+ plugin sent a message|\[clock )", prompt):
        return
    session = re.sub(r"[^A-Za-z0-9_-]", "", data.get("session_id", "nosession"))[:80]
    os.makedirs(STATE_DIR, exist_ok=True)
    state_path = os.path.join(STATE_DIR, session + ".json")
    try:
        seen = set(json.load(open(state_path)))
    except Exception:
        seen = set()

    theirs = clean(prompt)
    mine = clean(last_reply(data.get("transcript_path")))
    theirs_low = theirs.lower()

    cands = []   # (term, source)
    for p in phrases(theirs) + phrases(mine):
        cands.append((p, "phrase"))
    names_theirs = {re.sub(r"['’]s$", "", w) for w in midsentence_names(theirs)}
    for w in names_theirs:
        cands.append((w, "theirs"))
    for w in re.findall(WORD, theirs):
        w = re.sub(r"['’]s$", "", w.strip("'’-"))
        low = w.lower()
        # "isnt", "dont", "thats": a contraction typed without its apostrophe is still an ordinary word
        if any(low[:i] + "'" + low[i:] in DICT for i in range(1, len(low))):
            continue
        if w not in names_theirs and low not in DICT:
            cands.append((w, "theirs"))
    for w in midsentence_names(mine):
        cands.append((re.sub(r"['’]s$", "", w), "mine"))

    db = sqlite3.connect(f"file:{MIRROR}?mode=ro", uri=True, timeout=2)
    hits, unseen, done = [], [], set()
    for term, src in cands:
        key = term.lower()
        if key in done or key in ALWAYS or len(key) < 4:
            continue
        done.add(key)
        n, row = literal(db, term)
        if n == 0:
            if src == "mine" and key not in theirs_low and ("?" + key) not in seen:
                unseen.append(term)
            continue
        if n > (MAX_DF if src == "phrase" else MAX_DF_WORD):
            continue
        hits.append((src == "phrase", -n, term, row))

    out = []
    hits.sort(reverse=True)           # phrases first, then rarest
    used_docs = set()
    for _, _, term, row in hits:
        kind, ref, label, created, body = row
        doc = f"{kind}#{ref}"
        if doc in used_docs or (term.lower() + "|" + doc) in seen:
            continue
        used_docs.add(doc)
        seen.add(term.lower() + "|" + doc)
        when = (created or "")[:10]
        tag = f"{kind} {ref}" + (f", {label}" if label and kind == "observation" else "") + (f", {when}" if when else "")
        out.append(f"· \"{term}\" → [{tag}] {snippet(body, term)}")
        if len(out) >= MAX_TERMS:
            break
    flagged = unseen[:MAX_UNSEEN]
    for t in flagged:
        seen.add("?" + t.lower())
    if flagged:
        out.append("· no record at all of: " + ", ".join(flagged) + " (I named it; did they, or did I make it up?)")

    json.dump(sorted(seen), open(state_path, "w"))
    if out:
        print("[Literal: exact words from this exchange, checked against my records. "
              "Pointers, not receipts: open the record before leaning on one]\n" + "\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            import datetime
            with open(os.path.join(LOOP_DIR, "hook-failures.log"), "a") as f:
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} claims.py: {type(e).__name__}: {str(e)[:160]}\n")
        except Exception:
            pass
    sys.exit(0)
