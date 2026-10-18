#!/usr/bin/env python3
"""
transcript.py: read the companion's own Claude Code sessions back, for the weekly passes.

human_messages(days): the human's messages, each with the end of the companion's reply just
before it (so "what lands" can see what they were answering).
conversation(days): both sides, for the airing.
Harness traffic, hook output, tool results and headless runs are not your human and are
dropped. Set LOOP_TRANSCRIPTS to a glob of the session files of your companion's LIVE
sessions (e.g. ~/.claude/projects/-home-you/*.jsonl), not the folders the headless
miner/noticing/airing runs write into, or the passes will read their own prompts.
LOOP_SKIP_PROMPTS (regex) drops your own non-human openers too (timer wakes, a bridge).
"""
import datetime, glob, json, os, re

HARNESS = re.compile(r"\s*(<task-notification|<system-reminder|\[SYSTEM NOTIFICATION|Another Claude session|"
                     r"The \w+ plugin sent a message|\[clock |<command-|Caveat:|This session is being continued|"
                     r"\[Request interrupted)")
SKIP = re.compile(os.environ["LOOP_SKIP_PROMPTS"]) if os.environ.get("LOOP_SKIP_PROMPTS") else None


def not_human(txt):
    return bool(HARNESS.match(txt) or (SKIP and SKIP.search(txt[:300])))


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
            return ""
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _files(since):
    pattern = os.environ.get("LOOP_TRANSCRIPTS")
    if not pattern:
        raise SystemExit("set LOOP_TRANSCRIPTS to a glob of your companion's live session files")
    return [p for p in glob.glob(os.path.expanduser(pattern)) if os.path.getmtime(p) >= since.timestamp()]


def _walk(days):
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    for path in _files(since):
        for line in open(path, encoding="utf-8", errors="ignore"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("isSidechain") or d.get("isMeta") or d.get("type") not in ("user", "assistant"):
                continue
            txt = text_of((d.get("message") or {}).get("content")).strip()
            if not txt or (d["type"] == "user" and not_human(txt)):
                continue
            ts = d.get("timestamp", "")
            try:
                if datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")) < since:
                    continue
            except Exception:
                continue
            yield path, d["type"], ts[:16], txt


def human_messages(days, out):
    rows, last = [], {}
    for path, kind, ts, txt in _walk(days):
        if kind == "assistant":
            last[path] = txt
            continue
        rows.append({"ts": ts, "session": os.path.basename(path)[:8], "theirs": txt[:1200],
                     "mine_before": re.sub(r"\s+", " ", last.get(path, ""))[-300:]})
    return _write(rows, out)


def conversation(days, out, human="Human", companion="Companion"):
    rows = [{"ts": ts, "who": human if kind == "user" else companion, "text": txt[:1500]}
            for _, kind, ts, txt in _walk(days)]
    return _write(rows, out)


def _write(rows, out):
    rows.sort(key=lambda r: r["ts"])
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows
