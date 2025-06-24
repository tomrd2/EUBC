from datetime import date, timedelta, datetime
from collections import defaultdict
from db import get_db_connection

def add_elo():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        select r.Crew_ID, r.Piece_ID, r.GMT_Percent, o.Outing_Date, o.Outing_ID
        from Results r
        left join Pieces p on r.Piece_ID = p.Piece_ID
        left join Outings o on p.Outing_ID = o.Outing_ID
        ORDER BY o.Outing_Date, r.Piece_ID
    """)
    results = cursor.fetchall()
    dates = [row["Outing_Date"] for row in results if row["Outing_Date"]]
    earliest_date = min(dates)
    start_date = earliest_date - timedelta(days=1)

    cursor.execute("""
        SELECT s.Seat, s.Athlete_ID, s.Athlete_Name, s.Crew_ID, c.Outing_ID
        FROM Seats s
        left join Crews c on s.Crew_ID = c.Crew_ID
        WHERE Seat != 'Cox'
        ORDER BY s.Crew_ID
    """)
    seats = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM Athletes
        WHERE Side != 'Cox' AND (Coach IS NULL OR Coach != 1)
    """)
    athletes = cursor.fetchall()

    elo_history, result_updates = generate_daily_elo(results, seats, athletes, start_date)

    updates = [
        (exp, gain, crew_id, piece_id)     # order must match placeholders
        for (crew_id, piece_id), (exp, gain) in result_updates.items()
    ]

    sql = """
        UPDATE Results
        SET Exp_Percent = %s,
            Net_Gain    = %s
        WHERE Crew_ID = %s
        AND Piece_ID = %s
    """

    cursor.executemany(sql, updates)   # <<–– one network round-trip
    conn.commit()

    return elo_history

def generate_daily_elo(results, seats, athletes, start_date):

    elo_gearing = 8     #Controls how quickly on-the-water ratings change

    result_updates = {}

    # Step 1: Build date range
    outing_dates = sorted({row["Outing_Date"] for row in results if row["Outing_Date"]})
    end_date = outing_dates[-1]
    
    # Step 2: Initialize ratings at start_date
    elo_history = defaultdict(dict)
    current_ratings = {athlete["Athlete_ID"]: 1000 for athlete in athletes}
    for athlete_id in current_ratings:
        elo_history[athlete_id][start_date] = 1000

    # Step 3: Build a mapping of Crew_ID → [Athlete_IDs]
    crew_athletes = defaultdict(list)
    for seat in seats:
        crew_athletes[seat["Crew_ID"]].append(seat["Athlete_ID"])

    # Step 4: Process each day in date range
    date = start_date + timedelta(days=1)
    while date <= end_date:
        # Step 4a: Filter results for this day
        day_results = [r for r in results if r["Outing_Date"] == date]
        
        # If no results, carry over previous day
        if not day_results:
            for athlete_id in current_ratings:
                elo_history[athlete_id][date] = current_ratings[athlete_id]
            date += timedelta(days=1)
            continue
        
        # Step 4b: Process each piece on this day
        piece_ids = sorted({r["Piece_ID"] for r in day_results})
        athlete_gains = defaultdict(float)

        for piece_id in piece_ids:
            piece_results = [r for r in day_results if r["Piece_ID"] == piece_id]
            
            # Compute average crew rating
            crew_ratings = {}
            for result in piece_results:
                crew_id = result["Crew_ID"]
                athletes_in_crew = crew_athletes.get(crew_id, [])
                if not athletes_in_crew:
                    continue
                crew_rating = sum(current_ratings[a] for a in athletes_in_crew) / len(athletes_in_crew)
                crew_ratings[crew_id] = crew_rating

            # Convert to percent_ahead
            expected_percent = {
                crew_id: 100 + (rating - 1000) / 50         # So 50 rating points changes expected GMT % by one point
                for crew_id, rating in crew_ratings.items()
            }

            # Compute expected_fleet_percent
            expected_fleet_percent = sum(expected_percent.values()) / len(expected_percent)

            # Compute actual_fleet_percent (from GMT_Percent)
            actual_fleet_percent = sum(r["GMT_Percent"] for r in piece_results) / len(piece_results)

            # Piece adjustment
            piece_adjustment = actual_fleet_percent / expected_fleet_percent if expected_fleet_percent else 1

            # Adjust expected percent
            adjusted_expected = {
                crew_id: expected * piece_adjustment
                for crew_id, expected in expected_percent.items()
            }

            # Compute crew gain and apply to athletes
            for result in piece_results:
                crew_id = result["Crew_ID"]
                actual = result["GMT_Percent"]
                expected = adjusted_expected[crew_id]
                crew_gain = (actual - expected)

                # Store for updating Results table later
                result_updates[(crew_id, piece_id)] = (round(expected, 2), round(crew_gain, 2))

                # NEW: divide crew_gain by seat-count before adding to each athlete
                seat_count = len(crew_athletes.get(crew_id, [])) or 1     # fallback 1 to avoid div-by-zero
                per_athlete_gain = (crew_gain / seat_count) * elo_gearing

                for athlete_id in crew_athletes.get(crew_id, []):
                    athlete_gains[athlete_id] += per_athlete_gain

        # Step 4c: Update ratings and log history
        for athlete_id, gain in athlete_gains.items():
            current_ratings[athlete_id] += gain
        for athlete_id in current_ratings:
            elo_history[athlete_id][date] = current_ratings[athlete_id]

        # Next day
        date += timedelta(days=1)

    return elo_history, result_updates



if __name__ == "__main__":
    add_elo()
            