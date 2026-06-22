"""
server.py — The main API server built with FastAPI.

Endpoints:
  GET /api/health      — check if the server and database are running
  GET /api/categories  — list all product categories
  GET /api/products    — fetch products with keyset pagination

Run with:
  uvicorn src.server:app --reload
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.cursor import decode, encode
from src.db import get_conn

# Load environment variables from .env file
load_dotenv()

# Create the FastAPI app
app = FastAPI(title="Product Catalog API")

# Allow requests from any website (needed for the frontend to call this API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # "*" means any website is allowed
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    """Check that the server is running and the database is reachable."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")   # simple query to test the connection
    return {"status": "ok"}


# ── Categories ────────────────────────────────────────────────────────────────

@app.get("/api/categories")
def get_categories():
    """Return a list of all unique product categories."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT category FROM products ORDER BY category")
            rows = cur.fetchall()

    # Each row is a tuple like ("Electronics",), so we take item [0]
    category_list = [row[0] for row in rows]
    return {"categories": category_list}


# ── Products (with keyset pagination) ─────────────────────────────────────────

@app.get("/api/products")
def get_products(
    limit: int = Query(default=20, ge=1, le=100),   # items per page (1–100)
    category: str = Query(default=None),             # optional filter
    next_cursor: str = Query(default=None),          # where to continue from
):
    """
    Fetch a page of products.

    - Use 'category' to filter by category.
    - Use 'next_cursor' from the previous response to get the next page.
    - Returns 'next_cursor' = null when there are no more pages.
    """

    # Build the WHERE clause piece by piece
    conditions = []   # list of SQL conditions e.g. ["category = %s"]
    args       = []   # list of values matching the %s placeholders

    # If a category filter was given, add it
    if category:
        conditions.append("category = %s")
        args.append(category)

    # If a cursor was given, decode it and add a condition to start after it
    if next_cursor:
        try:
            cursor_created_at, cursor_id = decode(next_cursor)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor — cannot decode it")

        # Keyset condition: get rows that come BEFORE this (created_at, id) pair
        conditions.append("(created_at, id) < (%s, %s)")
        args.append(cursor_created_at)
        args.append(cursor_id)

    # Join conditions into a WHERE clause (or empty string if there are none)
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    else:
        where_clause = ""

    # We fetch one extra row to check if there is a next page
    args.append(limit + 1)

    # Build the final SQL query
    sql = f"""
        SELECT id, name, category, price, created_at, updated_at
        FROM products
        {where_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT %s
    """

    # Run the query
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()

    # Check if there is a next page (we fetched limit+1 rows to find out)
    has_more = len(rows) > limit
    rows     = rows[:limit]   # keep only the rows the caller asked for

    # Convert each database row into a plain dictionary
    products = []
    for row in rows:
        product = {
            "id":         row[0],
            "name":       row[1],
            "category":   row[2],
            "price":      str(row[3]),            # Decimal → string for JSON
            "created_at": row[4].isoformat(),     # datetime → "2024-01-15T..."
            "updated_at": row[5].isoformat(),
        }
        products.append(product)

    # Build the cursor for the next page (points to the last row we returned)
    if has_more and rows:
        last_row    = rows[-1]
        new_cursor  = encode(last_row[4], last_row[0])
    else:
        new_cursor  = None   # no more pages

    return {
        "data":        products,
        "next_cursor": new_cursor,
        "has_more":    has_more,
    }


# Serve the HTML/CSS frontend from the /public folder
app.mount("/", StaticFiles(directory="public", html=True), name="static")
