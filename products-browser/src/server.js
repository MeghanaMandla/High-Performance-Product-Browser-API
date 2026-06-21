// src/server.js
//
// GET /api/products?limit=&category=&cursor=
//
// Cursor-based (keyset) pagination over (created_at DESC, id DESC).
// See README.md for the full reasoning; short version:
//
//   - We never use OFFSET. OFFSET N means "skip N rows in the current
//     ordering, then take the next page" — but the *position* of every
//     row in that ordering shifts every time a row is inserted ahead of
//     it. Two requests five seconds apart can disagree about what "row
//     #4000" even is, which is exactly how OFFSET pagination produces
//     duplicates and skipped rows while data is being written.
//
//   - Keyset pagination instead says "give me rows strictly after the
//     last (created_at, id) pair I saw". That pair is a fact about a
//     specific row, not a position in a list, so it's immune to other
//     rows being inserted, updated, or deleted anywhere else in the
//     table. It also lets Postgres seek directly into the B-Tree index
//     at that point instead of scanning-and-discarding N rows, so it
//     stays fast (~same latency) no matter how deep the user pages.

require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const pool = require('./db');
const { encodeCursor, decodeCursor } = require('./cursor');

const app = express();
app.use(cors());
app.use(express.static(path.join(__dirname, '..', 'public')));

const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

app.get('/api/products', async (req, res) => {
  try {
    // ---- validate & parse query params -----------------------------
    let limit = parseInt(req.query.limit, 10);
    if (!Number.isFinite(limit) || limit <= 0) limit = DEFAULT_LIMIT;
    limit = Math.min(limit, MAX_LIMIT);

    const category = typeof req.query.category === 'string' && req.query.category.trim()
      ? req.query.category.trim()
      : null;

    let cursor = null;
    if (req.query.next_cursor || req.query.cursor) {
      cursor = decodeCursor(req.query.next_cursor || req.query.cursor);
      if (!cursor) {
        return res.status(400).json({ error: 'Invalid cursor' });
      }
    }

    // ---- build the query dynamically --------------------------------
    // We only add the clauses we actually need, rather than writing one
    // big query with `$param IS NULL OR ...` branches. That keeps each
    // query's shape (and therefore its query plan) simple and predictable
    // for the planner, and keeps the EXPLAIN output easy to defend.
    const where = [];
    const params = [];

    if (category) {
      params.push(category);
      where.push(`category = $${params.length}`);
    }

    if (cursor) {
      // Row-wise comparison: Postgres evaluates this as
      //   created_at < cursor_created_at
      //   OR (created_at = cursor_created_at AND id < cursor_id)
      // in a single index-friendly condition, which is exactly the
      // composite (created_at DESC, id DESC) index's native ordering.
      params.push(cursor.created_at);
      params.push(cursor.id);
      where.push(`(created_at, id) < ($${params.length - 1}, $${params.length})`);
    }

    // Fetch one extra row so we can tell whether there's a next page
    // without a separate COUNT(*) query (COUNT(*) over 200k rows is
    // comparatively expensive and we don't need an exact total here).
    params.push(limit + 1);
    const limitParamIndex = params.length;

    const sql = `
      SELECT id, name, category, price, created_at, updated_at
      FROM products
      ${where.length ? `WHERE ${where.join(' AND ')}` : ''}
      ORDER BY created_at DESC, id DESC
      LIMIT $${limitParamIndex}
    `;

    const { rows } = await pool.query(sql, params);

    const hasMore = rows.length > limit;
    const pageRows = hasMore ? rows.slice(0, limit) : rows;
    const nextCursor = hasMore ? encodeCursor(pageRows[pageRows.length - 1]) : null;

    res.json({
      data: pageRows,
      next_cursor: nextCursor,
      has_more: hasMore,
    });
  } catch (err) {
    console.error('GET /api/products failed:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Small helper endpoint so the UI can populate a category filter
// dropdown without hardcoding the list client-side.
app.get('/api/categories', async (_req, res) => {
  try {
    const { rows } = await pool.query(
      'SELECT DISTINCT category FROM products ORDER BY category'
    );
    res.json({ categories: rows.map((r) => r.category) });
  } catch (err) {
    console.error('GET /api/categories failed:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

app.get('/api/health', async (_req, res) => {
  try {
    await pool.query('SELECT 1');
    res.json({ status: 'ok' });
  } catch (err) {
    res.status(500).json({ status: 'db_unreachable' });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
