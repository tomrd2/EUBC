from datetime import date, timedelta
from collections import defaultdict
from db import get_db_connection

def make_history():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM History")

    # Step 1: Get all relevant athletes
    cursor.execute("""
        SELECT Athlete_ID FROM Athletes
        WHERE Side != 'Cox' AND (Coach IS NULL OR Coach != 1)
    """)
    athletes = [row['Athlete_ID'] for row in cursor.fetchall()]

    # Step 2: Generate date range
    end_date = date.today()
    cursor.execute("SELECT MIN(Session_Date) AS Earliest FROM Sessions")
    start_row = cursor.fetchone()
    start_date = start_row['Earliest'] or end_date  # fallback in case table is empty
    all_dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]

    # Step 3: Get T2Minutes totals from Sessions
    cursor.execute("""
        SELECT Athlete_ID, Session_Date, SUM(T2Minutes) AS Total_T2
        FROM Sessions
        GROUP BY Athlete_ID, Session_Date
    """)
    raw_sessions = cursor.fetchall()

    # Step 4: Build lookup of (athlete_id, date) → T2Minutes
    t2_lookup = defaultdict(int)
    for row in raw_sessions:
        t2_lookup[(row['Athlete_ID'], row['Session_Date'])] = row['Total_T2'] or 0

    # Step 5: Precompute weights
    weights = [1.0, 0.8, 0.6, 0.4, 0.2]

    # Step 6: Build complete history rows with fatigue
    history_records = []

    for athlete_id in athletes:
        for i, current_date in enumerate(all_dates):
            # --- Fatigue Calculation (already present) ---
            fatigue = 0.0
            for offset, weight in enumerate([1.0, 0.8, 0.6, 0.4, 0.2]):
                day = current_date - timedelta(days=offset)
                if day >= start_date:
                    fatigue += weight * float(t2_lookup.get((athlete_id, day), 0))

            # --- Fitness Calculation (new) ---
            fitness = 0.0
            for d in range(100):
                day = current_date - timedelta(days=d)
                if day >= start_date:
                    decay = (100 - d) / 100  # e.g., 1.0, 0.99, ..., 0.01
                    fitness += decay * float(t2_lookup.get((athlete_id, day), 0))

            t2 = t2_lookup.get((athlete_id, current_date), 0)
            history_records.append((
                athlete_id,
                current_date,
                t2,
                round(fatigue/3, 2),
                round(fitness/50.5, 2)
            ))

    cursor.executemany("""
        INSERT INTO History (Athlete_ID, Date, T2Minutes, Fatigue, Fitness)
        VALUES (%s, %s, %s, %s, %s)
    """, history_records)

    conn.commit()
    conn.close()
    print("✅ History table refreshed.")

if __name__ == "__main__":
    make_history()
