import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def main():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    conn.autocommit = True
    cur = conn.cursor()

    seed_file = os.path.join(os.path.dirname(__file__), 'seed.sql')
    with open(seed_file) as f:
        cur.execute(f.read())

    print('Done — 200,000 rows created.')
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
