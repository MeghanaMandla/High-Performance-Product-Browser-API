// src/cursor.js
//
// Encodes/decodes the keyset pagination cursor as an opaque, URL-safe
// base64 string. Clients should treat it as a black box — they just pass
// whatever `next_cursor` they were given back in on the next request.
//
// Internally it's just {created_at, id} — the last row's sort key — but
// keeping it opaque means we're free to change its internal shape later
// (e.g. add a version field) without breaking API consumers.

function encodeCursor(row) {
  const payload = JSON.stringify({
    created_at: row.created_at instanceof Date ? row.created_at.toISOString() : row.created_at,
    id: row.id,
  });
  return Buffer.from(payload, 'utf8').toString('base64url');
}

function decodeCursor(cursor) {
  if (!cursor || typeof cursor !== 'string') return null;
  try {
    const json = Buffer.from(cursor, 'base64url').toString('utf8');
    const obj = JSON.parse(json);
    if (!obj || typeof obj.id === 'undefined' || !obj.created_at) return null;
    // Basic sanity check that created_at parses to a real date.
    if (Number.isNaN(Date.parse(obj.created_at))) return null;
    return { created_at: obj.created_at, id: obj.id };
  } catch (err) {
    return null; // malformed cursor — caller should treat as a 400
  }
}

module.exports = { encodeCursor, decodeCursor };
