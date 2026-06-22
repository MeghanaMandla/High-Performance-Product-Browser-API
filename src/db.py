import os
from contextlib import contextmanager

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

load_dotenv()

_pool = ThreadedConnectionPool(
    1,
    int(os.getenv('PG_POOL_MAX', '10')),
    dsn=os.getenv('DATABASE_URL'),
)


@contextmanager
def get_conn():
    conn = _pool.getconn()
    try:
        yield conn
    finally:
        _pool.putconn(conn)
