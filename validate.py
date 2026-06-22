"""
This script shows the difference between two ways of fetching pages of data:

  1. KEYSET pagination  — uses the last row's value to know where to continue.
                          Works correctly even when new rows are added mid-way.

  2. OFFSET pagination  — uses a row number (skip N rows) to get the next page.
                          Breaks when new rows are added mid-way (shows duplicates).

No database setup needed — it uses SQLite which is built into Python.
Run with:  python validate.py
"""

import sqlite3

# ── Settings ─────────────────────────────────────────────────────────────────
TOTAL_ROWS   = 1000   # how many rows to start with
PAGE_SIZE    = 50     # how many rows per page
INJECT_AFTER = 5      # add new rows after this many pages have been fetched
INJECT_COUNT = 50     # how many new rows to add


# ── Helper functions ──────────────────────────────────────────────────────────

def create_table_and_fill(conn):
    """Create the table and insert TOTAL_ROWS rows."""
    conn.execute("""
        CREATE TABLE products (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL
        )
    """)

    # Build a list of dates to insert
    rows_to_insert = []
    for i in range(TOTAL_ROWS):
        month = (i // 28) % 12 + 1       # cycles through months 1–12
        day   = i % 28 + 1               # cycles through days 1–28
        date  = f"2024-{month:02d}-{day:02d}"
        rows_to_insert.append((date,))

    conn.executemany("INSERT INTO products (created_at) VALUES (?)", rows_to_insert)
    conn.commit()


def inject_new_rows(conn):
    """Simulate new rows arriving while we are paginating (future dates)."""
    new_rows = []
    for i in range(INJECT_COUNT):
        date = f"2030-01-{i + 1:02d}"   # 2030 dates sort to the TOP
        new_rows.append((date,))

    conn.executemany("INSERT INTO products (created_at) VALUES (?)", new_rows)
    conn.commit()


# ── Keyset pagination ─────────────────────────────────────────────────────────

def fetch_all_keyset(conn):
    """
    Keyset pagination:
    Instead of saying 'skip N rows', we remember the last row we saw
    and ask for rows that come AFTER it.

    Returns: (number of pages fetched, list of all row ids seen)
    """
    last_date = None   # the created_at value of the last row we fetched
    last_id   = None   # the id of the last row we fetched
    page_count = 0
    all_ids    = []

    while True:
        if last_date is None:
            # First page — no cursor yet, just get the newest rows
            rows = conn.execute("""
                SELECT id, created_at
                FROM products
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            """, (PAGE_SIZE,)).fetchall()
        else:
            # Next pages — only fetch rows that come BEFORE our last row
            rows = conn.execute("""
                SELECT id, created_at
                FROM products
                WHERE (created_at, id) < (?, ?)
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            """, (last_date, last_id, PAGE_SIZE)).fetchall()

        if not rows:
            break   # no more rows, we are done

        page_count += 1

        # After page INJECT_AFTER, simulate new rows being added
        if page_count == INJECT_AFTER:
            inject_new_rows(conn)

        # Collect the ids we saw on this page
        for row in rows:
            all_ids.append(row[0])

        # Remember where we stopped so the next query can continue from here
        last_date = rows[-1][1]
        last_id   = rows[-1][0]

    return page_count, all_ids


# ── Offset pagination ─────────────────────────────────────────────────────────

def fetch_all_offset(conn):
    """
    Offset pagination:
    Uses OFFSET to skip rows we already fetched (like saying 'start from row 50').

    The problem: when new rows arrive, they shift everything down,
    so some rows get skipped and others appear twice.

    Returns: (number of pages fetched, list of all row ids seen)
    """
    offset     = 0
    page_count = 0
    all_ids    = []

    while True:
        rows = conn.execute("""
            SELECT id
            FROM products
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (PAGE_SIZE, offset)).fetchall()

        if not rows:
            break   # no more rows

        page_count += 1

        # After page INJECT_AFTER, simulate new rows being added
        if page_count == INJECT_AFTER:
            inject_new_rows(conn)

        # Collect the ids we saw on this page
        for row in rows:
            all_ids.append(row[0])

        # Move the offset forward by one page
        offset += PAGE_SIZE

    return page_count, all_ids


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    original_ids = set(range(1, TOTAL_ROWS + 1))   # ids 1 to 1000

    # ── Test keyset ───────────────────────────────────────────────────────────
    print("=" * 50)
    print("Testing KEYSET pagination...")
    print("=" * 50)

    conn1 = sqlite3.connect(":memory:")   # in-memory DB, nothing saved to disk
    create_table_and_fill(conn1)

    pages, ids_seen = fetch_all_keyset(conn1)
    unique_ids      = set(ids_seen)
    duplicates      = len(ids_seen) - len(unique_ids)       # extra copies
    missed          = len(original_ids - unique_ids)         # rows we never saw

    print(f"Pages fetched       : {pages}")
    print(f"Total rows seen     : {len(ids_seen)}")
    print(f"Duplicate rows      : {duplicates}")
    print(f"Missed original rows: {missed}")

    if duplicates == 0 and missed == 0:
        print("RESULT: PASS — no duplicates, no missed rows")
    else:
        print(f"RESULT: FAIL — {duplicates} duplicates, {missed} missed")

    # ── Test offset ───────────────────────────────────────────────────────────
    print()
    print("=" * 50)
    print("Testing OFFSET pagination...")
    print("=" * 50)

    conn2 = sqlite3.connect(":memory:")
    create_table_and_fill(conn2)

    pages2, ids_seen2 = fetch_all_offset(conn2)
    unique_ids2       = set(ids_seen2)
    duplicates2       = len(ids_seen2) - len(unique_ids2)
    missed2           = len(original_ids - unique_ids2)

    print(f"Pages fetched       : {pages2}")
    print(f"Total rows seen     : {len(ids_seen2)}")
    print(f"Duplicate rows      : {duplicates2}")
    print(f"Missed original rows: {missed2}")

    if duplicates2 > 0 or missed2 > 0:
        print("RESULT: BUG CONFIRMED — offset breaks when new rows are added mid-way")
    else:
        print("RESULT: No problem detected (unexpected)")


if __name__ == "__main__":
    main()
