"""
db.py — Database connection setup.

We use a "connection pool" instead of opening a new connection for every request.
A pool keeps a set of connections ready so the app responds faster.

The DATABASE_URL comes from the .env file and looks like:
    postgresql://user:password@host:5432/dbname
"""

import os
from contextlib import contextmanager

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

# Load variables from the .env file into the environment
load_dotenv()

# How many database connections to keep open at once
# Minimum = 1, Maximum = value from .env (default 10)
MIN_CONNECTIONS = 1
MAX_CONNECTIONS = int(os.getenv("PG_POOL_MAX", "10"))

# Create the connection pool when the app starts
connection_pool = ThreadedConnectionPool(
    MIN_CONNECTIONS,
    MAX_CONNECTIONS,
    dsn=os.getenv("DATABASE_URL"),   # the full database URL from .env
)


@contextmanager
def get_conn():
    """
    Borrow a database connection from the pool.

    Usage:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")

    The connection is automatically returned to the pool when the
    'with' block ends, even if an error happens.
    """
    # Borrow a connection from the pool
    conn = connection_pool.getconn()
    try:
        yield conn          # give the connection to the caller
    finally:
        connection_pool.putconn(conn)   # always return it to the pool
