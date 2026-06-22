"""
Proves that keyset pagination is correct under concurrent writes,
and that OFFSET pagination produces duplicates in the same scenario.

Uses Python's built-in sqlite3 — no database setup needed.
Run: python validate.py
"""
import sqlite3

TOTAL        = 1000
PAGE         = 50
INJECT_PAGE  = 5   # inject new rows after fetching this page
INJECT_COUNT = 50


def _seed(conn):
    conn.execute(
        'CREATE TABLE rows (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL)'
    )
    conn.executemany(
        'INSERT INTO rows (created_at) VALUES (?)',
        [(f'2024-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}',) for i in range(TOTAL)],
    )
    conn.commit()


def _inject(conn):
    # Future dates — sort to the TOP of the feed, above any existing cursor
    conn.executemany(
        'INSERT INTO rows (created_at) VALUES (?)',
        [(f'2030-01-{i + 1:02d}',) for i in range(INJECT_COUNT)],
    )
    conn.commit()


def run_keyset(conn):
    cursor, page, ids = None, 0, []
    while True:
        if cursor:
            rows = conn.execute(
                'SELECT id, created_at FROM rows'
                ' WHERE (created_at, id) < (?, ?)'
                ' ORDER BY created_at DESC, id DESC LIMIT ?',
                (*cursor, PAGE),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT id, created_at FROM rows ORDER BY created_at DESC, id DESC LIMIT ?',
                (PAGE,),
            ).fetchall()
        if not rows:
            break
        page += 1
        if page == INJECT_PAGE:
            _inject(conn)
        ids.extend(r[0] for r in rows)
        cursor = (rows[-1][1], rows[-1][0])  # (created_at, id) of last row
    return page, ids


def run_offset(conn):
    off, page, ids = 0, 0, []
    while True:
        rows = conn.execute(
            'SELECT id FROM rows ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?',
            (PAGE, off),
        ).fetchall()
        if not rows:
            break
        page += 1
        if page == INJECT_PAGE:
            _inject(conn)
        ids.extend(r[0] for r in rows)
        off += PAGE
    return page, ids


def main():
    orig = set(range(1, TOTAL + 1))

    # ── keyset ────────────────────────────────────────────────────
    conn = sqlite3.connect(':memory:')
    _seed(conn)
    pages, ids = run_keyset(conn)
    id_set = set(ids)
    dups   = len(ids) - len(id_set)
    missed = len(orig - id_set)
    print(f'[keyset] pages={pages} total_seen={len(ids)} original_rows_seen={len(orig & id_set)}/{TOTAL}')
    if dups == 0 and missed == 0:
        print('[keyset] PASS — zero duplicates, zero missed rows among pre-existing data\n')
    else:
        print(f'[keyset] FAIL — {dups} duplicates, {missed} missed\n')

    # ── offset ────────────────────────────────────────────────────
    conn2 = sqlite3.connect(':memory:')
    _seed(conn2)
    pages2, ids2 = run_offset(conn2)
    id_set2 = set(ids2)
    dups2   = len(ids2) - len(id_set2)
    print(f'[offset] pages={pages2} duplicates_seen={dups2} original_rows_seen={len(orig & id_set2)}/{TOTAL}')
    if dups2 > 0:
        print('[offset] CONFIRMS THE BUG — duplicates and/or missed rows under concurrent inserts')
    else:
        print('[offset] No duplicates detected (unexpected)')


if __name__ == '__main__':
    main()
