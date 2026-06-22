# Product Catalog — 200k products, fast cursor-paginated browsing

A small FastAPI + Postgres backend that lets someone browse ~200,000 products
newest-first, filter by category, and paginate through them — correctly, even
while data is being written concurrently.

## Stack

- **Python + FastAPI** — backend API
- **PostgreSQL** (Neon/Supabase free tier in production) — single table, two
  composite B-Tree indexes
- **Vanilla HTML/JS + Custom CSS** — bonus UI, no build step, no CDN dependency

## Why these choices

Postgres because the core requirement — "paginate correctly while rows are
being inserted/updated" — is fundamentally about index-backed ordering
guarantees, and Postgres' composite B-Tree indexes plus support for row-value
comparisons (`(created_at, id) < (%s, %s)`) make keyset pagination both simple
to write and provably correct. FastAPI because it is a thin, well-understood
HTTP layer over one query — lightweight and fast with automatic API docs at
`/docs`. No ORM: there's exactly one query that matters and it needs to be
exactly right, so it's hand-written SQL with parameterized inputs.

## Project layout

```
db/seed.sql        DDL + bulk seed (200k rows) + indexes — single script
db/seed.py         Runs seed.sql over DATABASE_URL (no psql CLI needed)
src/db.py          psycopg2 connection pool
src/cursor.py      opaque base64url cursor encode/decode
src/server.py      FastAPI app: GET /api/products, /api/categories, /api/health
public/index.html  bonus UI (not graded, see task brief)
validate.py        offline proof-of-correctness simulation (see below)
```

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env                    # fill in DATABASE_URL from Neon/Supabase
python db/seed.py                       # creates table + 200,000 rows + indexes
uvicorn src.server:app --reload         # http://localhost:8000
```

## API Endpoints

### `GET /api/products`

| Parameter | Required | Default | Description |
|---|---|---|---|
| `limit` | No | 20 (max 100) | Results per page |
| `category` | No | — | Filter by category name |
| `next_cursor` | No | — | Pagination cursor from previous response |

Response:

```json
{
  "data": [
    {
      "id": 42,
      "name": "Product 42",
      "category": "Books",
      "price": "19.99",
      "created_at": "2024-01-15T12:34:56Z",
      "updated_at": "2024-01-15T12:34:56Z"
    }
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0IjoiMjAyNC0wMS0xNVQxMjozNDo1NloiLCJpZCI6NDJ9",
  "has_more": true
}
```

`next_cursor` is opaque to the client — just pass back whatever you were
given. Internally it's the last row's `(created_at, id)`.

### `GET /api/categories`

Returns all distinct product categories.

```json
{ "categories": ["Automotive", "Beauty", "Books", "Clothing", "Electronics", "..."] }
```

### `GET /api/health`

```json
{ "status": "ok" }
```

---

## The hard part: pagination that stays correct while data changes

### Why `LIMIT/OFFSET` breaks under writes

`OFFSET N` means "skip N rows in the *current* ordering, then take the next
page." The problem is that "position N" is not a fact about any particular
row — it's a fact about the whole table at the instant the query runs. If
the table changes between two page requests, position N can refer to a
completely different row the second time:

- **Insert 50 new rows at the top** (newer `created_at`, which is exactly
  what "newest first" means by definition) → everything the user has already
  seen shifts down by 50 positions. Their next `OFFSET=200` request now lands
  50 rows earlier than where they actually left off → **they see 50 rows
  twice**.
- **Delete or move a row out from earlier in the ordering** → the opposite
  happens, rows shift up, and the next `OFFSET` request **skips** rows the
  user never saw.

This isn't a rare edge case — it's the default behavior of OFFSET any time
the table is written to during a browsing session, which is exactly the
scenario in the task ("50 new products are added/updated while someone is
browsing"). It also gets *slower* the deeper you page: `OFFSET 50000` still
makes Postgres walk and discard 50,000 index entries before it can return
anything, so tail-page latency degrades linearly with depth.

### Why keyset (cursor) pagination fixes it

Instead of "skip N rows," the client sends back a **bookmark anchored to
actual data**: the `(created_at, id)` of the last row it saw. The next page
is simply:

```sql
WHERE (created_at, id) < ($last_created_at, $last_id)
ORDER BY created_at DESC, id DESC
LIMIT $n
```

Because the bookmark is a value, not a position, it's unaffected by what
happens elsewhere in the table:

- **New rows inserted "now"** sort to the very top of the feed (higher
  `created_at`) — strictly *ahead* of any cursor the user already holds. The
  `WHERE (created_at, id) < cursor` condition by construction excludes them.
  The user simply never re-crosses a point they've already paged past, so no
  duplicates, and nothing they already saw moves or disappears.
- **No `OFFSET` is ever computed**, so Postgres can seek directly into the
  `(created_at DESC, id DESC)` B-Tree at the cursor's value and read the next
  `LIMIT` rows from there — an index range scan, not "scan-and-discard N."
  Page 1 and page 5,000 cost the same.
- **The `id` tie-breaker matters**: many rows can share the same `created_at`
  (timestamps aren't unique). Sorting by `created_at` alone would make the
  order, and therefore the cursor boundary, ambiguous between rows with equal
  timestamps — some could be skipped or repeated right at the page boundary.
  Pairing with the always-unique `id` makes the sort key a strict total order,
  so every row has one unambiguous position no matter how many timestamps
  collide.

### Why the cursor is `(created_at, id)` and not `(updated_at, id)`

This is a deliberate design choice, not an oversight. The task says products
can be **updated** mid-browse too, and the result still has to be correct.
If the feed were ordered/paginated by `updated_at`, editing a product the
user already scrolled past would re-sort it to the top of the feed — they'd
either see it a second time, or (if they'd already paged beyond where it now
needs to land) never see the edit at all without restarting. Ordering by the
immutable `created_at` instead means an `UPDATE` changes that row's field
values but never its position in the feed, so the pagination walk stays
stable. Each page is still queried live, though, so when the user does reach
that row's position, they see its current `price`/`name`/`updated_at` —  not
stale cached data — they just see it in the right place exactly once.

### Indexes

```sql
CREATE INDEX idx_products_created_id
    ON products (created_at DESC, id DESC);

CREATE INDEX idx_products_category_created_id
    ON products (category, created_at DESC, id DESC);
```

- `(created_at DESC, id DESC)` backs the unfiltered feed. Its column order
  matches `ORDER BY created_at DESC, id DESC` exactly, so Postgres needs no
  separate sort step — it just walks the index.
- `(category, created_at DESC, id DESC)` backs the filtered feed.
  `category` is first because it's the **equality** predicate
  (`WHERE category = $1`); standard composite-index rule is equality columns
  before range/sort columns. Once Postgres narrows to one category via the
  first index column, `created_at DESC, id DESC` continues the *same* index
  for ordering and the cursor seek, again avoiding a sort.

Both queries should show `Index Scan` (or `Index Only Scan`) in
`EXPLAIN ANALYZE`, not `Seq Scan` or a `Sort` node — that's the thing worth
checking with `EXPLAIN ANALYZE SELECT ...` against the real 200k-row table.

### Proof, not just an argument

`validate.py` is a small offline simulation (uses Python's built-in
`sqlite3`, which supports the same `(a, b) < (?, ?)` row-value comparison
Postgres does) that:

1. Seeds 1,000 rows, paginates with the keyset query, and injects 50 new
   "concurrent" rows halfway through the scroll — asserts zero duplicates and
   zero missed pre-existing rows.
2. Runs the identical scenario through plain `OFFSET` pagination instead, to
   show it actually does duplicate rows under the same conditions.

```bash
python validate.py
```

```
[keyset] pages=20 total_seen=1000 original_rows_seen=1000/1000
[keyset] PASS — zero duplicates, zero missed rows among pre-existing data

[offset] pages=21 duplicates_seen=50 original_rows_seen=1000/1000
[offset] CONFIRMS THE BUG — duplicates and/or missed rows under concurrent inserts
```

---

## Seed script

`db/seed.sql` creates 200,000 rows with one set-based
`INSERT ... SELECT ... FROM generate_series(1, 200000)` — no procedural
per-row loop, no 200,000 round trips. Indexes are created **after** the bulk
insert (building a B-Tree from data already on disk is cheaper than
maintaining it incrementally across 200k individual inserts).

`created_at` is generated so that higher `id` ⇒ later `created_at`, spread
across roughly two years — mirrors how rows actually arrive in a real system,
and is what makes "order by id" and "order by created_at" agree, which the
keyset cursor (and the "newest first" requirement) depends on.

## Deployment

- **Database**: [Neon](https://neon.tech) or [Supabase](https://supabase.com)
  free tier Postgres. Copy the connection string into `DATABASE_URL`, run
  `python db/seed.py` once against it.
- **Backend**: [Render](https://render.com) free web service — connect the
  repo, set build command to `pip install -r requirements.txt`, start command
  to `uvicorn src.server:app --host 0.0.0.0 --port $PORT`, add the
  `DATABASE_URL` env var.

## What I'd improve with more time

- Add an index-backed total count estimate (`pg_class.reltuples`) for the UI
  instead of omitting a total, since exact `COUNT(*)` over 200k rows isn't
  free and isn't needed for correctness.
- Cursor currently isn't signed — for a public API I'd HMAC-sign it so a
  client can't hand-craft an arbitrary `(created_at, id)` to probe data
  outside intended access patterns (not a concern for this read-only public
  catalog, but would matter if rows were ever per-user).
- Add a composite index variant for a price-sort mode if that filter were
  needed, and a `pg_trgm` index if free-text name search were added later.
- Light integration tests against a real Postgres (e.g. via a Dockerized
  Postgres) rather than the `sqlite3` simulation, which proves the *algorithm*
  but not Postgres-specific planner behavior.

## How I used AI

I used Claude to scaffold this end-to-end from a detailed spec I wrote
covering the schema, the cursor-pagination contract, and the UI shape. I
reviewed and adjusted the generated SQL and query-building logic, and added
`validate.js` myself to actually prove the keyset-vs-offset correctness claim
rather than just asserting it in prose — that simulation (seed 1,000 rows,
inject 50 concurrent inserts mid-scroll, assert no dupes/skips, then show
OFFSET fails the same test) is the thing I'd want to walk through live, since
it's the actual evidence behind the design decision rather than a
description of it. One thing worth flagging: an early draft used a SQL
pattern with `($param IS NULL OR ...)` branches to make one "universal" query
handle the filtered/unfiltered and first-page/cursor cases — I changed that
to dynamically building the WHERE clause per request instead, since the
`IS NULL OR` style can fool the Postgres planner into a generic plan that
doesn't reliably hit the composite index for every parameter combination,
which would undermine the exact "fast pagination" guarantee this task is
about.
