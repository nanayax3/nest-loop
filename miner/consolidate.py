#!/usr/bin/env python3
"""
consolidate.py: fold together principles that say the same thing. Runs after the
weekly miner (miner.py calls it), or by hand. Needs worker-addon/ (nestknow_merge).

  1. pulls every active principle with its receipt count and the date span of the
     feelings behind it (D1, read-only);
  2. the headless companion proposes groups that express the SAME tendency (not merely
     related ones), a keeper, and one combined wording;
  3. code checks: same scope, ids exist, at most LOOP_MAX_MERGES (default 10) per run;
     then nestknow_merge, so sources, access history and heat move to the keeper and
     nothing is lost.

The rule learnt on the very first pass: NEVER fold a general principle into a narrow
one. "They are the authority on their own body" must not vanish inside a principle
about heat. It's in the prompt, and it's why a human skim of the first few runs is
worth it.

  python3 consolidate.py --dry    proposals only, nothing merged
"""
import datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import d1, mcp, headless, STATE_DIR

MAX = int(os.environ.get("LOOP_MAX_MERGES", 10))
DRY = "--dry" in sys.argv
SPAN = ("(SELECT {f}(f.created_at) FROM knowledge_sources s JOIN feelings f "
        "ON s.source_type='feeling' AND f.id=s.source_id WHERE s.knowledge_id=k.id)")


def main():
    rows = d1(f"""SELECT k.id, k.entity_scope AS scope, k.category, k.content, k.heat_score AS heat,
                 (SELECT count(*) FROM knowledge_sources s WHERE s.knowledge_id = k.id) AS receipts,
                 {SPAN.format(f='min')} AS first_seen, {SPAN.format(f='max')} AS last_seen
                 FROM knowledge_items k WHERE k.status IN ('active','cooling') ORDER BY k.entity_scope, k.id""")
    by_id = {r["id"]: r for r in rows}
    run = os.path.join(STATE_DIR, "runs", "consolidate-" + datetime.datetime.now().strftime("%Y-%m-%d-%H%M"))
    os.makedirs(run, exist_ok=True)
    json.dump(rows, open(os.path.join(run, "principles.json"), "w"), ensure_ascii=False, indent=1)
    headless(f"""You are tidying your own NESTknow. Read {run}/principles.json: every active principle,
with scope, receipt count and the date span of the feelings behind it.

Find groups that express the SAME tendency in different words. Not related, not overlapping topics:
the same pattern, so that keeping both splits one truth's evidence in two. For each group:
  - keep_id: the member with the most receipts (on a tie, the oldest first_seen);
  - merge_ids: the others (same scope only);
  - content: ONE combined wording, 1-2 plain sentences, as specific as the best member, keeping any
    detail a member had that the others lacked. If the group spans months, it may say so ("since
    January"). Principles about the human DESCRIBE, NEVER INSTRUCT.
Be conservative: when in doubt, don't merge. At most {MAX} groups.
NEVER fold a GENERAL principle (one that holds across situations) into a NARROW one: the general
truth would disappear inside a special case. If any member is broader than the keeper, leave it.
Write {run}/merges.json as {{"merges": [{{"keep_id": 0, "merge_ids": [0], "content": "...", "why": "..."}}]}}
and validate it with `python3 -m json.tool`. Write nothing else.""", cwd=run, turns=40, timeout=1800)
    path = os.path.join(run, "merges.json")
    if not os.path.exists(path):
        return {"principles_folded": 0, "note": "no merges.json"}
    done, refused = [], []
    for g in json.load(open(path)).get("merges", [])[:MAX]:
        keep = g.get("keep_id")
        members = [m for m in g.get("merge_ids", []) if m != keep]
        if not (keep in by_id and members and g.get("content") and all(m in by_id for m in members)
                and all(by_id[m]["scope"] == by_id[keep]["scope"] for m in members)):
            refused.append(g)
            continue
        print(f"\n[{by_id[keep]['scope']}] keep #{keep} <- {members}\n  NEW: {g['content']}\n  WHY: {g.get('why', '')}")
        for m in [keep] + members:
            r = by_id[m]
            print(f"    #{m} ({r['receipts']} rec, {str(r['first_seen'])[:10]}->{str(r['last_seen'])[:10]}): {r['content'][:110]}")
        if not DRY:
            for i, m in enumerate(members):
                mcp("nestknow_merge", {"keep_id": keep, "merge_id": m,
                                       **({"content": g["content"]} if i == len(members) - 1 else {})})
        done.append(g)
    summary = {"proposed": len(done) + len(refused), "merged_groups": len(done), "refused": len(refused),
               "principles_folded": sum(len(g["merge_ids"]) for g in done)}
    json.dump(summary, open(os.path.join(run, "summary.json"), "w"))
    print("\n" + json.dumps(summary))
    return summary


if __name__ == "__main__":
    main()
