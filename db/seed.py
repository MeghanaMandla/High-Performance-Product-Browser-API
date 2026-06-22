"""
seed.py — Fills the database with sample product data.

This reads the SQL commands from seed.sql and runs them against the database.
The DATABASE_URL must be set in your .env file before running this.

Run with:
  python db/seed.py
"""

import os

import psycopg2
from dotenv import load_dotenv

# Load DATABASE_URL and other variables from the .env file
load_dotenv()


def main():
    # Connect to the PostgreSQL database using the URL from .env
    database_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(database_url)

    # autocommit = True means each SQL statement is saved immediately
    conn.autocommit = True
    cur = conn.cursor()

    # Find the seed.sql file in the same folder as this script
    this_folder  = os.path.dirname(__file__)
    seed_file    = os.path.join(this_folder, "seed.sql")

    # Read the SQL file and run all the commands inside it
    print("Running seed.sql ...")
    with open(seed_file) as f:
        sql_commands = f.read()
        cur.execute(sql_commands)

    print("Done — 200,000 rows created.")

    # Close the cursor and connection when finished
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
