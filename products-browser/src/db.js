// src/db.js
//
// A single shared connection pool, reused across all requests. Pooling
// matters here because a new TCP + TLS + auth handshake per request would
// dominate latency under any real concurrency — the pool keeps a small
// number of warm connections ready and queues requests beyond that.

const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: Number(process.env.PG_POOL_MAX || 10),
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
  // Neon / Supabase both require TLS. Allow opting out for a local
  // Postgres instance via PGSSL=false.
  ssl: process.env.PGSSL === 'false' ? false : { rejectUnauthorized: false },
});

pool.on('error', (err) => {
  // Errors on idle clients (e.g. the DB closing a stale connection)
  // should not crash the process.
  console.error('Unexpected error on idle Postgres client', err);
});

module.exports = pool;
