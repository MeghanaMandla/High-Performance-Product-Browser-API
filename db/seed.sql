-- ============================================================================
-- seed.sql
-- Creates the products table and bulk-loads 200,000 rows in a single
-- set-based INSERT (generate_series), then builds indexes afterwards.
--
-- Run with:  psql "$DATABASE_URL" -f db/seed.sql
-- or:        python db/seed.py   (runs this file over DATABASE_URL)
--
-- Design notes:
--  - Indexes are created AFTER the bulk insert. Building a B-Tree from
--    already-sorted-on-disk data is much faster than maintaining it row
--    by row during 200k individual inserts.
--  - created_at is generated so that higher id == later created_at. This
--    mirrors reality (rows are inserted in time order) and is what makes
--    "newest first" pagination by created_at and by id agree with each
--    other, which matters for the keyset cursor (created_at, id).
--  - updated_at starts equal to created_at. A later UPDATE will bump
--    updated_at but deliberately must NOT change created_at, because the
--    feed is ordered/paginated by created_at, not updated_at (see README).
-- ============================================================================

DROP TABLE IF EXISTS products;

CREATE TABLE products (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT            NOT NULL,
    category    TEXT            NOT NULL,
    price       NUMERIC(10, 2)  NOT NULL CHECK (price >= 0),
    created_at  TIMESTAMPTZ     NOT NULL,
    updated_at  TIMESTAMPTZ     NOT NULL
);

-- ----------------------------------------------------------------------------
-- Bulk insert: 200,000 rows, one statement, fully set-based.
-- generate_series(1, 200000) produces the row source server-side; there is
-- no round trip per row and no procedural (PL/pgSQL FOR loop) overhead.
-- On a typical free-tier Postgres instance this finishes in low single
-- digit seconds.
-- ----------------------------------------------------------------------------
INSERT INTO products (name, category, price, created_at, updated_at)
SELECT
    'Product ' || gs AS name,
    (ARRAY['Electronics', 'Books', 'Clothing', 'Home & Kitchen', 'Toys',
           'Sports', 'Beauty', 'Automotive', 'Garden', 'Grocery']
    )[1 + floor(random() * 10)::int] AS category,
    round((random() * 990 + 10)::numeric, 2) AS price,
    -- Spread rows over ~2.3 years (200,000 seconds-ish steps), oldest id
    -- furthest in the past, highest id closest to "now". Newest first.
    TIMESTAMP '2024-01-01 00:00:00' + (gs * INTERVAL '350 seconds') AS created_at,
    TIMESTAMP '2024-01-01 00:00:00' + (gs * INTERVAL '350 seconds') AS updated_at
FROM generate_series(1, 200000) AS gs;

-- ----------------------------------------------------------------------------
-- Indexes — created after the data load.
--
-- 1) idx_products_created_id
--    Composite B-Tree on (created_at DESC, id DESC).
--    Backs the global "newest first" feed AND the keyset cursor lookup:
--    ORDER BY created_at DESC, id DESC
--    WHERE (created_at, id) < (:cursor_created_at, :cursor_id)
--    Postgres can walk this index directly from the cursor's position
--    instead of scanning/sorting the whole table, and the DESC,DESC
--    column order matches our DESC,DESC ORDER BY exactly so no extra
--    sort step is needed.
--
-- 2) idx_products_category_created_id
--    Composite B-Tree on (category, created_at DESC, id DESC).
--    category goes FIRST because it's the equality filter — that's the
--    standard "equality columns before range/sort columns" rule for
--    composite indexes. Once Postgres has narrowed down to a single
--    category via the index's first column, created_at DESC, id DESC
--    lets it continue down that same index for the ordering/cursor seek,
--    again avoiding a separate sort.
-- ----------------------------------------------------------------------------
CREATE INDEX idx_products_created_id
    ON products (created_at DESC, id DESC);

CREATE INDEX idx_products_category_created_id
    ON products (category, created_at DESC, id DESC);

ANALYZE products;
