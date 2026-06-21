// db/run-seed.js
//
// Convenience runner so the seed script can be executed with just
// `npm run seed` (no local psql / Postgres client tools required) —
// handy on Render, Codespaces, or any box that only has Node on it.
//
// node-postgres runs a query string with NO parameters through Postgres'
// "simple query" protocol, which (unlike the extended/parameterized
// protocol) supports multiple semicolon-separated statements in one
// call — exactly what we need to run seed.sql's DROP/CREATE/INSERT/
// CREATE INDEX sequence as one shot.

require('dotenv').config();
const fs = require('fs');
const path = require('path');
const { Client } = require('pg');

async function main() {
  if (!process.env.DATABASE_URL) {
    console.error('DATABASE_URL is not set. Copy .env.example to .env and fill it in.');
    process.exit(1);
  }

  const sqlPath = path.join(__dirname, 'seed.sql');
  const sql = fs.readFileSync(sqlPath, 'utf8');

  const client = new Client({
    connectionString: process.env.DATABASE_URL,
    ssl: process.env.PGSSL === 'false' ? false : { rejectUnauthorized: false },
  });

  console.log('Connecting...');
  await client.connect();

  console.log('Seeding 200,000 products (this can take a few seconds)...');
  const start = Date.now();
  await client.query(sql);
  const seconds = ((Date.now() - start) / 1000).toFixed(2);
  console.log(`Done in ${seconds}s.`);

  const { rows } = await client.query('SELECT count(*)::int AS count FROM products');
  console.log(`products table now has ${rows[0].count} rows.`);

  await client.end();
}

main().catch((err) => {
  console.error('Seed failed:', err);
  process.exit(1);
});
