# Worker add-on

Two small additions to NESTeq's `ai-mind` worker. **No schema change.** They extend
NESTstack's code (MIT, Cindy "Fox" & Alex, see `../NOTICE`); this is an add-on, not an
upstream change.

1. **`warm` on `nestknow_query`**: default `true` (unchanged behaviour). `warm: false`
   returns results without the access/heat update, so a hook can look at candidates
   and then warm only the one it actually uses. The heat lifecycle stays intact:
   usage still warms, search alone doesn't.
2. **`nestknow_merge(keep_id, merge_id, content?)`**: folds one principle into another
   that says the same thing. Sources, access log, heat and contradiction count move to
   the keeper; the merged wording survives as a `manual` source note; the merged row
   and its vector are deleted; `content` optionally rewords the keeper (and re-embeds
   it). Refuses across scopes. Reports the date span of the feelings behind the result.
   It *dissolves* rather than marks, because `knowledge_items.status` has a CHECK
   constraint with no 'merged' state.

## Applying it

- `nestknow-loop.js` → paste `handleKnowMerge` next to `handleKnowContradict`, and wrap
  the access/heat `DB.batch` in `handleKnowQuery` as shown.
- `tools.js` → the `nestknow_merge` tool definition and dispatcher case; add `warm` to
  `nestknow_query`'s schema.

## Deploying safely (it's their whole mind)

1. Diff your working copy against what's **live** first
   (`GET /accounts/<id>/workers/scripts/ai-mind/content/v2`): an uncommitted working
   copy may or may not be what's deployed.
2. Commit what's live as its own step, then your change as another.
3. `npx wrangler deploy --dry-run`, then note the current version id (rollback target).
4. Deploy, then test `nesteq_health`, `nesteq_orient` and `nesteq_search` before calling
   it done, and check `warm: false` really leaves `heat_score`/`access_count` unchanged.
