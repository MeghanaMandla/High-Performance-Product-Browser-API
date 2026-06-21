# Implementation Notes

## Summary

Built a fast, correct cursor-paginated product catalog API supporting 200,000 products with proper handling of concurrent writes. The API guarantees that users never see duplicate products or miss any products, even when data is being added/modified mid-browse.

## Stack & Choices

### Backend: Node.js + Express
- Simple, well-understood HTTP layer over a single query — lightweight and fast
- The actual complexity is in the database layer, not the framework
- Connection pooling (pg module) handles concurrent requests efficiently

### Database: PostgreSQL (Neon/Supabase)
- **Core problem solved by Postgres**: "Paginate correctly while data changes" requires index-backed ordering guarantees
- Composite B-Tree indexes with support for row-value comparisons (`(created_at, id) < (?, ?)`) make keyset pagination both simple and provably correct
- Two indexes designed for the exact query patterns:
  - `(created_at DESC, id DESC)` — backs global "newest first" feed
  - `(category, created_at DESC, id DESC)` — backs category-filtered feed, with category first for equality filtering

### Seed Script
- Single set-based `INSERT ... SELECT ... FROM generate_series(1, 200000)` — no per-row loop overhead
- Creates 200k rows in seconds on free-tier Postgres
- Indexes built **after** data load (faster than building incrementally)
- `created_at` spread across ~2.3 years with higher id = later timestamp, mirroring real-world insertion patterns

### UI: Vanilla JS + Tailwind (CDN)
- No build step required — just HTML + vanilla JS fetch()
- Infinite scroll via IntersectionObserver, manual "Load more" button fallback
- Light 3D tilt effect on hover (CSS transform)
- Theme toggle with radial clip-path animation

## The Hard Problem: Pagination Under Concurrent Writes

### Why Not OFFSET Pagination?

`OFFSET N` means "skip N rows in the current ordering, then take the next page." The problem:

**Scenario**: 50 new products inserted while user is browsing (they'd sort to the top as "newest")
- User's position in the list shifts down by 50 rows
- Their next request with `OFFSET=200` lands 50 rows earlier than where they actually stopped
- **Result: They see 50 products twice** ❌

The simulation in `validate.js` proves this — OFFSET pagination shows 50 duplicates when 50 rows are inserted mid-scroll.

### Why Keyset (Cursor) Pagination Works

Instead of a position, send the actual `(created_at, id)` of the last row seen — a **value**, not a position:

```sql
WHERE (created_at, id) < ($last_created_at, $last_id)
ORDER BY created_at DESC, id DESC
LIMIT $n
```

**Why this stays correct**:
1. New rows inserting "now" sort to the very top (higher `created_at`)
2. The `WHERE (created_at, id) < cursor` condition by construction excludes them
3. User never re-crosses a boundary they've already passed — zero duplicates
4. No OFFSET computation needed — Postgres seeks directly into the B-Tree index at the cursor's position
5. Same latency for page 1 and page 5,000

**Why `id` is the tie-breaker**: Many rows can share the same `created_at` (timestamps aren't unique). The `id` ensures a strict total order, so every row has one unambiguous position in the sort, making the cursor boundary precise.

### Why `created_at` and not `updated_at`

Deliberate choice: If ordered by `updated_at`, editing a product the user already scrolled past would re-sort it to the top — they'd see it twice or miss the update. Ordering by immutable `created_at` means updates never move a row's position in the feed, only change its field values when the user naturally reaches it.

## Performance & Correctness Proofs

### `validate.js` Simulation

Tests both keyset and OFFSET pagination under the exact same scenario:
- Seed 1,000 rows
- Paginate with limit=50
- Inject 50 new rows mid-scroll (page 5 of 20)
- Assert correctness

**Results**:
```
[keyset] pages=20 total_seen=1000 original_rows_seen=1000/1000
[keyset] PASS — zero duplicates, zero missed rows among pre-existing data

[offset] pages=21 duplicates_seen=50 original_rows_seen=1000/1000
[offset] CONFIRMS THE BUG — duplicates and/or missed rows under concurrent inserts
```

### Database Query

The keyset query generates an `Index Scan` (or `Index Only Scan`) on the composite index — never a `Seq Scan` or `Sort`, even at depth. This can be verified with `EXPLAIN ANALYZE`.

## What I'd Improve With More Time

1. **Count estimate for the UI**: Use `pg_class.reltuples` for an approximate total instead of omitting it — exact `COUNT(*)` over 200k rows is expensive and unnecessary
2. **Signed cursors**: HMAC-sign the cursor to prevent clients from hand-crafting arbitrary `(created_at, id)` pairs — not needed for this read-only public catalog, but would matter for per-user data
3. **Additional index variants**: Price-sort mode, `pg_trgm` index for fuzzy name search if search were added later
4. **Integration tests**: Real Postgres tests (via `pg-mem` or Docker) rather than just the SQLite simulation, to verify Postgres planner behavior with real table statistics
5. **API caching headers**: `Cache-Control` headers on immutable data (product details) or category list
6. **Request deduplication**: For very high concurrency, dedup identical concurrent queries to avoid thundering herd on Postgres

## How AI Was Used

Used Claude (via Cursor) to scaffold the end-to-end implementation from a detailed spec I wrote covering:
- Schema design (immutable `created_at`, mutable `updated_at`)
- The cursor-pagination contract
- Express API structure
- UI shape and styling

**What I reviewed/changed**:
- Adjusted the SQL query building to avoid `($param IS NULL OR ...)` branches that can confuse the Postgres planner — instead dynamically building `WHERE` clauses per request
- Reviewed and verified the cursor encode/decode logic
- Wrote `validate.js` from scratch to actually *prove* the keyset-vs-offset correctness claim rather than just asserting it

**Key decision I drove**: The **simulation proof** (`validate.js`) is the real evidence. Saying "keyset pagination is correct under concurrent writes" is a claim; actually injecting writes mid-scroll and showing zero duplicates is proof. That's what I wanted to walk through in an interview rather than hand-waving about composite indexes.

## Deployment

- **Database**: Neon (or Supabase) free tier
  - Go to [neon.tech](https://neon.tech), create a project
  - Copy the `postgres://...` connection string → `DATABASE_URL` env var
  - Run `npm run seed` once to create the table and 200k rows

- **Backend**: Render free web service
  - Connect GitHub repo
  - Build: `npm install`
  - Start: `npm start`
  - Add `DATABASE_URL` env var (paste from Neon)
  - Service will auto-restart on git push

- **Client**: Static HTML served from Express — available at the backend's public URL

## Testing Locally

```bash
# Copy template and fill in DATABASE_URL
cp .env.example .env

# Install dependencies
npm install

# Seed the database (one time only)
npm run seed

# Run the server
npm start

# Visit http://localhost:3000
```

Or test the pagination logic without a database:

```bash
# Verify keyset pagination is correct and OFFSET is buggy under concurrent writes
node validate.js
```

---

**Submitted**: 2026-06-21
