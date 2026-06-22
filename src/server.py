import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.cursor import decode, encode
from src.db import get_conn

load_dotenv()

app = FastAPI(title='Product Catalog API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/health')
def health():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
    return {'status': 'ok'}


@app.get('/api/categories')
def get_categories():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT DISTINCT category FROM products ORDER BY category')
            return {'categories': [r[0] for r in cur.fetchall()]}


@app.get('/api/products')
def get_products(
    limit: int = Query(default=20, ge=1, le=100),
    category: str = Query(default=None),
    next_cursor: str = Query(default=None),
):
    conditions, args = [], []

    if category:
        conditions.append('category = %s')
        args.append(category)

    if next_cursor:
        try:
            cur_created_at, cur_id = decode(next_cursor)
        except Exception:
            raise HTTPException(status_code=400, detail='Invalid cursor')
        conditions.append('(created_at, id) < (%s, %s)')
        args.extend([cur_created_at, cur_id])

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    args.append(limit + 1)

    sql = f'''
        SELECT id, name, category, price, created_at, updated_at
        FROM products
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT %s
    '''

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [
        {
            'id': r[0],
            'name': r[1],
            'category': r[2],
            'price': str(r[3]),
            'created_at': r[4].isoformat(),
            'updated_at': r[5].isoformat(),
        }
        for r in rows
    ]

    new_cursor = encode(rows[-1][4], rows[-1][0]) if (has_more and rows) else None

    return {'data': data, 'next_cursor': new_cursor, 'has_more': has_more}


app.mount('/', StaticFiles(directory='public', html=True), name='static')
