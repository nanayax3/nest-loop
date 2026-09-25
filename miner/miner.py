#!/usr/bin/env python3
"""
miner.py: the weekly miner. NESTknow learns from NESTeq's feelings, receipts or nothing.

Run it from a timer (see examples/). Each run:
  1. exports the NEW feelings since the last run, plus the 30 days before them as
     CONTEXT (so a pattern's three receipts can span weeks), plus the current NESTknow
     list (D1, read-only);
  2. wakes the companion HEADLESS (Claude Code, -p) with MINER.md to propose principles.
     That run can only read files and write one proposal file. It cannot touch memory;
  3. ENFORCES THE RECEIPTS RULE IN CODE: every receipt id must be in the window, 3+
     distinct per principle, at least one from the new week, every quote an exact
     substring of its feeling. Reinforcements and contradictions may cite NEW feelings
     only, so no week is counted twice. Whatever fails is dropped;
  4. a proposal that near-duplicates an existing principle (>= LOOP_DUP weighted)
     reinforces it instead of being stored again;
  5. stores / reinforces / contradicts through NESTknow's own tools, runs the
     consolidation pass (consolidate.py), saves state, and sends ONE line via
     LOOP_NOTIFY_CMD, so a stalled miner gets noticed.

PRIVACY, READ THIS: step 2 sends a week of feelings (plus context) to whatever model the
headless run uses. That is OFF your Cloudflare account. If your companion already runs on
that model, it's the same place every conversation already goes, but decide it on
purpose. Opt-in only.

  python3 miner.py --dry          propose and check, write nothing, notify nothing
  LOOP_STATE_DIR=/tmp/x python3 miner.py --dry   test against a throwaway state
Backlog: set last_id in $LOOP_STATE_DIR/miner-state.json to where mining should start.
"""
import datetime, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import d1, mcp, notify, headless, HUMAN, COMPANION, STATE_DIR

DRY = "--dry" in sys.argv
DUP = float(os.environ.get("LOOP_DUP", 88))
STATE = os.path.join(STATE_DIR, "miner-state.json")
HERE = os.path.dirname(os.path.abspath(__file__))
COLS = "id, created_at, emotion, intensity, source, tags, content"


def main():
    state = json.load(open(STATE)) if os.path.exists(STATE) else {"last_id": 0}
    rows = d1(f"SELECT {COLS} FROM feelings WHERE id > ? ORDER BY id", [state["last_id"]])
    if len(rows) < 5:
        notify(f"🔎 Miner: only {len(rows)} new feelings, nothing to mine yet.")
        return
    context = d1(f"SELECT {COLS} FROM feelings WHERE id <= ? AND created_at >= datetime(?, '-30 days') ORDER BY id",
                 [state["last_id"], rows[0]["created_at"]])
    label = f"{rows[0]['created_at'][:10]}..{rows[-1]['created_at'][:10]}"
    run = os.path.join(STATE_DIR, "runs", datetime.datetime.now().strftime("%Y-%m-%d-%H%M"))
    os.makedirs(run, exist_ok=True)
    for name, data in (("feelings.jsonl", rows), ("context.jsonl", context)):
        with open(os.path.join(run, name), "w") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in data)
    known = d1("SELECT id, entity_scope, category, status, content FROM knowledge_items "
               "WHERE status != 'contradicted' ORDER BY id")
    json.dump(known, open(os.path.join(run, "knowledge-existing.json"), "w"), ensure_ascii=False, indent=1)
    instructions = open(os.path.join(HERE, "MINER.md")).read().replace("{HUMAN}", HUMAN).replace("{COMPANION}", COMPANION)
    open(os.path.join(run, "MINER.md"), "w").write(instructions)

    headless(f"Read {run}/MINER.md and follow it exactly. NEW feelings: {run}/feelings.jsonl (label "
             f"\"{label}\"). CONTEXT, the 30 days before: {run}/context.jsonl. Existing knowledge: "
             f"{run}/knowledge-existing.json. Write {run}/candidates.json. Read every line. "
             f"Write nothing else anywhere.", cwd=run)
    cpath = os.path.join(run, "candidates.json")
    if not os.path.exists(cpath):
        notify(f"⚠️ Miner: {len(rows)} feelings ({label}) produced no candidates. See {run}.")
        return
    cand = json.load(open(cpath))

    new = {r["id"]: (r["content"] or "") for r in rows}
    feel = {**{r["id"]: (r["content"] or "") for r in context}, **new}
    known_ids = {k["id"] for k in known}
    scopes = {HUMAN, COMPANION, "craft"}

    def valid(receipts, need, new_only=False):
        pool = new if new_only else feel
        good = [r for r in receipts if r.get("id") in pool and (not r.get("quote") or r["quote"] in pool[r["id"]])]
        if len({r["id"] for r in good}) < need or not any(r["id"] in new for r in good):
            return None
        return good

    def cite(good):
        return f"miner {label}: feelings #" + ", #".join(str(r["id"]) for r in good if r["id"] in new)

    stored = merged = reinforced = contradicted = 0
    dropped = []
    for p in cand.get("principles", []):
        good = valid(p.get("receipts", []), 3)
        if not good or p.get("scope") not in scopes or not p.get("principle"):
            dropped.append(p.get("principle", "?")[:60])
            continue
        hit = mcp("nestknow_query", {"query": p["principle"], "entity_scope": p["scope"], "limit": 1, "warm": False})
        m = re.search(r"^\*\*#(\d+)\*\*[^\n]*?\((\d+(?:\.\d+)?)% weighted\)", hit, re.M)
        if m and float(m.group(2)) >= DUP:
            if not DRY:
                mcp("nestknow_reinforce", {"knowledge_id": int(m.group(1)), "context": cite(good)})
            merged += 1
            continue
        if not DRY:
            mcp("nestknow_store", {"content": p["principle"], "category": p.get("category") or "general",
                                   "entity_scope": p["scope"],
                                   "sources": [{"source_type": "feeling", "source_id": r["id"],
                                                "source_text": r.get("quote", "")} for r in good]})
        stored += 1
    for x in cand.get("reinforces", []):
        good = valid(x.get("receipts", []), 1, new_only=True)
        if good and x.get("knowledge_id") in known_ids:
            if not DRY:
                mcp("nestknow_reinforce", {"knowledge_id": int(x["knowledge_id"]), "context": cite(good)})
            reinforced += 1
    for c in cand.get("contradicts", []):
        good = valid(c.get("receipts", []), 1, new_only=True)
        if good and c.get("knowledge_id") in known_ids:
            if not DRY:
                mcp("nestknow_contradict", {"knowledge_id": int(c["knowledge_id"]),
                                            "context": f"miner {label}: {c.get('why', '')[:300]}"})
            contradicted += 1

    folded = 0
    if not DRY and os.environ.get("LOOP_CONSOLIDATE", "1") == "1":
        try:
            import consolidate
            folded = (consolidate.main() or {}).get("principles_folded", 0)
        except Exception as e:
            dropped.append(f"(consolidate failed: {str(e)[:80]})")
    summary = {"label": label, "new": len(rows), "context": len(context), "stored": stored,
               "reinforced": reinforced + merged, "contradicted": contradicted, "folded": folded,
               "dropped_for_receipts": dropped, "almost": len(cand.get("almost", []))}
    json.dump(summary, open(os.path.join(run, "summary.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if not DRY:
        json.dump({"last_id": rows[-1]["id"], "last_run": datetime.datetime.now().isoformat(timespec="seconds")},
                  open(STATE, "w"))
        notify(f"🔎 Miner: {len(rows)} new feelings ({label}): {stored} new principles, "
               f"{reinforced + merged} reinforced, {contradicted} contradicted, {folded} folded together, "
               f"{len(dropped)} dropped for missing receipts, {summary['almost']} almost.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        notify(f"⚠️ Miner crashed: {str(e)[:300]}")
        raise
