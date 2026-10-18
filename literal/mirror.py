#!/usr/bin/env python3
"""
mirror.py: a local, literal copy of the companion's memory, for exact-word search.

nesteq_search is semantic, and semantic search is bad at rare nouns: a book title or a
product name inside a long entry gets diluted in the embedding and never clears the
floor. So this pulls the text tables out of D1 into a local SQLite file with an FTS5
index, and hooks/claims.py asks it for exact words in milliseconds, offline.

Full rebuild every run (a few thousand rows takes seconds). Written to a temp file and
swapped in, so a reader never sees half a mirror. Read-only on D1.
Run it on a timer (examples/nest-loop-literal.timer, every 3 hours is plenty: what you
log inside a conversation, you still remember inside that conversation).

The better end state is hybrid search inside NESTeq itself (D1 has FTS5 too), so every
room gets it. Until then, this.
"""
import os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import d1, STATE_DIR

OUT = os.path.join(STATE_DIR, "mirror.db")
SOURCES = [   # (kind, SQL). Every row: id, label, created, body.
    ("observation", "SELECT o.id, e.name AS label, o.added_at AS created, o.content AS body "
                    "FROM observations o JOIN entities e ON e.id = o.entity_id"),
    ("feeling",     "SELECT id, emotion AS label, created_at AS created, content AS body FROM feelings"),
    ("note",        "SELECT id, thread_id AS label, created_at AS created, content AS body FROM thread_notes"),
    ("thread",      "SELECT id, status AS label, created_at AS created, content AS body FROM threads"),
    ("knowledge",   "SELECT id, entity_scope AS label, created_at AS created, content AS body FROM knowledge_items"),
]


def pull(sql):
    """Page integer ids 1000 at a time; tables with text ids come in one go."""
    rows, last = [], -1
    paged = "SELECT * FROM (" + sql + ") WHERE id > ? ORDER BY id LIMIT 1000"
    try:
        while True:
            page = d1(paged, [last])
            if not page:
                return rows
            rows += page
            last = page[-1]["id"]
            if not isinstance(last, int):
                return rows
    except RuntimeError:
        return d1(sql)


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = OUT + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.execute("CREATE TABLE docs (kind TEXT, ref TEXT, label TEXT, created TEXT, body TEXT)")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(body, content='docs', content_rowid='rowid', "
               "tokenize='unicode61 remove_diacritics 2')")
    counts = {}
    for kind, sql in SOURCES:
        try:
            rows = pull(sql)
        except RuntimeError:
            rows = []          # a table your NESTeq doesn't have yet
        counts[kind] = len(rows)
        db.executemany("INSERT INTO docs VALUES (?,?,?,?,?)",
                       [(kind, str(r["id"]), r.get("label") or "", r.get("created") or "", r["body"] or "") for r in rows])
    db.execute("INSERT INTO fts(fts) VALUES ('rebuild')")
    db.commit()
    db.close()
    os.replace(tmp, OUT)
    if "-q" not in sys.argv:
        print("mirror:", counts)


if __name__ == "__main__":
    main()
