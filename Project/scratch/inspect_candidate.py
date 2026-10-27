import sys
sys.path.append('C:/Python_ML/Project')

from DB_Store.rankresume_pipeline import connect_db

def show_candidate_columns():
    conn = connect_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'candidate'
            ORDER BY ordinal_position;
        """)
        rows = cur.fetchall()
        print('Columns in candidate table:')
        for r in rows:
            print(' -', r[0])

if __name__ == '__main__':
    show_candidate_columns()
