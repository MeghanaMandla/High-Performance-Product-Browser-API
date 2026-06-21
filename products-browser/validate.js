// validate.js — throwaway verification script, run locally with `node validate.js`.
// Uses node's built-in :memory: SQLite (same row-value comparison semantics as
// Postgres) to prove out the pagination logic before wiring it to real Postgres.
const { DatabaseSync } = require('node:sqlite');
const db = new DatabaseSync(':memory:');

db.exec(`
  CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    category TEXT,
    created_at TEXT
  );
`);

// Seed 1000 initial rows, ids 1..1000, created_at strictly increasing with id.
const insert = db.prepare('INSERT INTO products (id, category, created_at) VALUES (?, ?, ?)');
const cats = ['A', 'B', 'C'];
for (let i = 1; i <= 1000; i++) {
  insert.run(i, cats[i % 3], String(1000000 + i).padStart(10, '0'));
}

function fetchPageKeyset(cursor, limit = 50) {
  const sql = cursor
    ? `SELECT id, created_at FROM products WHERE (created_at, id) < (?, ?) ORDER BY created_at DESC, id DESC LIMIT ?`
    : `SELECT id, created_at FROM products ORDER BY created_at DESC, id DESC LIMIT ?`;
  const stmt = db.prepare(sql);
  return cursor ? stmt.all(cursor.created_at, cursor.id, limit) : stmt.all(limit);
}

function fetchPageOffset(offset, limit = 50) {
  const stmt = db.prepare(`SELECT id, created_at FROM products ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?`);
  return stmt.all(limit, offset);
}

function nextId() {
  const row = db.prepare('SELECT MAX(id) AS m FROM products').get();
  return row.m + 1;
}

function insertNewRows(n) {
  // Simulate new products being created "now" -> sorts to the very top.
  const maxRow = db.prepare('SELECT MAX(created_at) AS m FROM products').get();
  let base = parseInt(maxRow.m, 10);
  for (let i = 0; i < n; i++) {
    base += 1;
    insert.run(nextId(), cats[i % 3], String(base).padStart(10, '0'));
  }
}

// ---------------------------------------------------------------------------
// Test 1: keyset pagination under concurrent inserts — no dupes, no skips
// among rows that existed before the writes started.
// ---------------------------------------------------------------------------
{
  const seenIds = new Set();
  let cursor = null;
  let page = 0;
  let injectedWrites = false;

  while (true) {
    const rows = fetchPageKeyset(cursor, 50);
    if (rows.length === 0) break;
    for (const r of rows) {
      if (seenIds.has(r.id)) {
        console.error('FAIL keyset: duplicate row id', r.id);
        process.exit(1);
      }
      seenIds.add(r.id);
    }
    cursor = rows[rows.length - 1];
    page += 1;

    // Halfway through, simulate 50 new products being added while the
    // user is mid-scroll (they land above the user's current cursor).
    if (page === 5 && !injectedWrites) {
      insertNewRows(50);
      injectedWrites = true;
    }
  }

  // All 1000 original rows must have been seen exactly once. The 50 rows
  // inserted "ahead" of where the user already scrolled past should NOT
  // appear (the user already moved beyond that point in time) — also
  // correct behavior, not a bug.
  let originalSeen = 0;
  for (let i = 1; i <= 1000; i++) if (seenIds.has(i)) originalSeen++;
  console.log(`[keyset] pages=${page} total_seen=${seenIds.size} original_rows_seen=${originalSeen}/1000`);
  if (originalSeen !== 1000) {
    console.error('FAIL keyset: missed some original rows');
    process.exit(1);
  }
  console.log('[keyset] PASS — zero duplicates, zero missed rows among pre-existing data\n');
}

// ---------------------------------------------------------------------------
// Test 2: OFFSET pagination under the exact same concurrent-insert scenario
// — demonstrate it DOES duplicate/skip, to justify why we didn't use it.
// ---------------------------------------------------------------------------
{
  const db2 = new DatabaseSync(':memory:');
  db2.exec(`CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, created_at TEXT);`);
  const insert2 = db2.prepare('INSERT INTO products (id, category, created_at) VALUES (?, ?, ?)');
  for (let i = 1; i <= 1000; i++) insert2.run(i, cats[i % 3], String(1000000 + i).padStart(10, '0'));

  function fetchOffset(offset, limit = 50) {
    return db2.prepare(`SELECT id, created_at FROM products ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?`).all(limit, offset);
  }

  const seenIds = new Set();
  let duplicates = 0;
  let offset = 0;
  let page = 0;
  let injected = false;

  while (true) {
    const rows = fetchOffset(offset, 50);
    if (rows.length === 0) break;
    for (const r of rows) {
      if (seenIds.has(r.id)) duplicates++;
      seenIds.add(r.id);
    }
    offset += 50;
    page += 1;

    if (page === 5 && !injected) {
      const maxRow = db2.prepare('SELECT MAX(created_at) AS m FROM products').get();
      let base = parseInt(maxRow.m, 10);
      let maxId = db2.prepare('SELECT MAX(id) AS m FROM products').get().m;
      for (let i = 0; i < 50; i++) {
        base += 1; maxId += 1;
        insert2.run(maxId, cats[i % 3], String(base).padStart(10, '0'));
      }
      injected = true;
    }
  }

  let originalSeen = 0;
  for (let i = 1; i <= 1000; i++) if (seenIds.has(i)) originalSeen++;
  console.log(`[offset] pages=${page} duplicates_seen=${duplicates} original_rows_seen=${originalSeen}/1000`);
  if (duplicates > 0 || originalSeen < 1000) {
    console.log('[offset] CONFIRMS THE BUG — duplicates and/or missed rows under concurrent inserts, as expected. This is why OFFSET is not used in the real API.\n');
  } else {
    console.log('[offset] (no drift observed in this particular run/shape, but it is not safe in general — see README)\n');
  }
}
