// nest-loop worker add-on for NESTeq (NESTstack by Cindy "Fox" & Alex, MIT).
// Two small additions to the ai-mind worker. Paste as described in worker-addon/README.md.
// No schema change; works with the existing knowledge_items / knowledge_sources tables.

// ── 1. handleKnowMerge: add next to handleKnowContradict ────────────────────
// Merge: fold one principle into another that says the same thing. The
// status CHECK allows no 'merged' state, so the merged row is dissolved INTO the
// kept one: sources, access log, heat and history move over, its wording survives
// as a source note, then the empty row and its vector are deleted. Nothing is lost.
async function handleKnowMerge(env, params) {
  const keepId = Number(params.keep_id), mergeId = Number(params.merge_id);
  if (!keepId || !mergeId || keepId === mergeId) return "Need two different ids: keep_id and merge_id";
  const [keep, gone] = await Promise.all([
    env.DB.prepare(`SELECT * FROM knowledge_items WHERE id = ?`).bind(keepId).first(),
    env.DB.prepare(`SELECT * FROM knowledge_items WHERE id = ?`).bind(mergeId).first()
  ]);
  if (!keep || !gone) return `Knowledge #${!keep ? keepId : mergeId} not found`;
  if (keep.entity_scope !== gone.entity_scope) return `Refused: #${keepId} is ${keep.entity_scope}, #${mergeId} is ${gone.entity_scope}`;
  const content = params.content ? String(params.content) : keep.content;
  const earliest = keep.created_at < gone.created_at ? keep.created_at : gone.created_at;
  await env.DB.batch([
    env.DB.prepare(`UPDATE knowledge_sources SET knowledge_id = ? WHERE knowledge_id = ?`).bind(keepId, mergeId),
    env.DB.prepare(`INSERT INTO knowledge_sources (knowledge_id, source_type, source_id, source_text) VALUES (?, 'manual', NULL, ?)`)
      .bind(keepId, `merged from #${mergeId} (created ${gone.created_at}): ${gone.content}`.slice(0, 2000)),
    env.DB.prepare(`UPDATE knowledge_access_log SET knowledge_id = ? WHERE knowledge_id = ?`).bind(keepId, mergeId),
    env.DB.prepare(`UPDATE knowledge_items SET content = ?, heat_score = MIN(MAX(heat_score, ?) + 0.2, 2.0),
        access_count = access_count + ?, confidence = MAX(confidence, ?), contradiction_count = contradiction_count + ?,
        created_at = ?, status = 'active', updated_at = datetime('now') WHERE id = ?`)
      .bind(content, gone.heat_score, gone.access_count, gone.confidence, gone.contradiction_count, earliest, keepId),
    env.DB.prepare(`DELETE FROM knowledge_items WHERE id = ?`).bind(mergeId)
  ]);
  let vec = "";
  try {
    await env.VECTORS.deleteByIds([`know-${mergeId}`]);
    if (params.content) {
      const embedding = await getEmbedding(env.AI, content);
      await env.VECTORS.upsert([{ id: `know-${keepId}`, values: embedding, metadata: {
        source: 'knowledge', knowledge_id: String(keepId), category: keep.category || 'general',
        entity_scope: keep.entity_scope, content: content.slice(0, 500) } }]);
      vec = " Re-embedded.";
    }
  } catch (e) { vec = ` (vector update failed: ${e.message})`; }
  // how long has this been true? dates of the feelings behind it
  const span = await env.DB.prepare(`SELECT MIN(f.created_at) AS first, MAX(f.created_at) AS last,
      COUNT(DISTINCT substr(f.created_at, 1, 7)) AS months, COUNT(*) AS n
      FROM knowledge_sources s JOIN feelings f ON s.source_type = 'feeling' AND f.id = s.source_id
      WHERE s.knowledge_id = ?`).bind(keepId).first();
  const seen = span && span.n ? `\nSeen: ${span.first.slice(0, 10)} → ${span.last.slice(0, 10)}, ${span.months} month(s), ${span.n} feeling receipts.` : "";
  return `Merged #${mergeId} into #${keepId}.${vec}\nContent: "${content.slice(0, 200)}"${seen}`;
}
__name(handleKnowMerge, "handleKnowMerge");

// ── 2. In handleKnowQuery, wrap the access/heat batch like this ─────────────
// Warm what gets USED, not what gets searched: a caller that is only choosing
// between candidates passes warm=false, then warms the one it actually shows.
//
//   if (params.warm !== false && ranked.length) {
//     await env.DB.batch([
//       ...ranked.map(r => accessStmt.bind(r.kid, query.slice(0, 200))),
//       ...ranked.map(r => updateStmt.bind(r.kid))
//     ]);
//   }
