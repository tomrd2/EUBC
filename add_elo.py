from datetime import date, timedelta, datetime
from collections import defaultdict
from db import get_db_connection, get_param


def _parse_season_start() -> date | None:
    """Read Params.Season_Start (YYYY-MM-DD) and return a date or None."""
    try:
        raw = get_param("Season_Start", None).value
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def add_elo():
    conn = get_db_connection()
    cursor = conn.cursor()

    # --- Resolve season start (optional) ---
    season_start = _parse_season_start()

    # Filter results by season if Season_Start is set
    extra_where = " AND o.Outing_Date >= %s" if season_start else ""
    params = (season_start,) if season_start else ()

    cursor.execute(f"""
        SELECT r.Crew_ID, r.Piece_ID, r.GMT_Percent, o.Outing_Date, o.Outing_ID
        FROM Results r
        LEFT JOIN Pieces p ON r.Piece_ID = p.Piece_ID
        LEFT JOIN Outings o ON p.Outing_ID = o.Outing_ID
        WHERE (r.Unrated IS NULL OR r.Unrated = 0)
        {extra_where}
        ORDER BY o.Outing_Date, r.Piece_ID
    """, params)
    results = cursor.fetchall()

    # Determine start_date (the day *before* we begin daily stepping)
    if season_start:
        start_date = season_start - timedelta(days=1)
    else:
        dates = [row["Outing_Date"] for row in results if row.get("Outing_Date")]
        earliest_date = min(dates) if dates else date.today()
        start_date = earliest_date - timedelta(days=1)

    cursor.execute("""
        SELECT s.Seat, s.Athlete_ID, s.Athlete_Name, s.Crew_ID, c.Outing_ID
        FROM Seats s
        LEFT JOIN Crews c ON s.Crew_ID = c.Crew_ID
        WHERE Seat != 'Cox'
        ORDER BY s.Crew_ID
    """)
    seats = cursor.fetchall()

    # Only what we need (and include Start_Rating)
    cursor.execute("""
        SELECT Athlete_ID, Start_Rating
        FROM Athletes
        WHERE Side != 'Cox' AND (Coach IS NULL OR Coach != 1)
    """)
    athletes = cursor.fetchall()

    elo_history, result_updates = generate_daily_elo(results, seats, athletes, start_date)

    updates = [
        (exp, gain, crew_id, piece_id)
        for (crew_id, piece_id), (exp, gain) in result_updates.items()
    ]

    if updates:
        cursor.executemany(
            """
            UPDATE Results
               SET Exp_Percent = %s,
                   Net_Gain    = %s
             WHERE Crew_ID = %s
               AND Piece_ID = %s
            """,
            updates,
        )
        conn.commit()

    return elo_history


def generate_daily_elo(results, seats, athletes, start_date):
    # Controls how quickly ratings move (defaults to 8 if Params missing)
    try:
        elo_gearing = float(get_param("Elo_Gearing", 8).value)
    except Exception:
        elo_gearing = 8.0

    result_updates = {}

    # Step 1: build date range (start_date+1 .. today)
    end_date = date.today()

    # Step 2: initialize per-athlete rating from Start_Rating (fallback 1000)
    elo_history = defaultdict(dict)

    def _start_val(raw):
        try:
            v = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            v = 0
        return v if v > 0 else 1000

    current_ratings = {
        row["Athlete_ID"]: _start_val(row.get("Start_Rating"))
        for row in athletes
    }
    for athlete_id, start_val in current_ratings.items():
        elo_history[athlete_id][start_date] = start_val

    # Step 3: Crew_ID → athlete IDs
    from collections import defaultdict as _dd
    crew_athletes = _dd(list)
    for seat in seats:
        crew_athletes[seat["Crew_ID"]].append(seat["Athlete_ID"])

    # Step 4: per-day processing
    current_date = start_date + timedelta(days=1)
    while current_date <= end_date:
        # Results for this day only
        day_results = [r for r in results if r.get("Outing_Date") == current_date]

        # No results → carry forward yesterday’s rating
        if not day_results:
            for aid in current_ratings:
                elo_history[aid][current_date] = current_ratings[aid]
            current_date += timedelta(days=1)
            continue

        # Aggregate by piece
        piece_ids = sorted({r["Piece_ID"] for r in day_results})
        athlete_gains = _dd(float)

        for piece_id in piece_ids:
            piece_results = [r for r in day_results if r["Piece_ID"] == piece_id]

            # Average crew rating
            crew_ratings = {}
            for result in piece_results:
                crew_id = result["Crew_ID"]
                members = crew_athletes.get(crew_id, [])
                known = [a for a in members if a in current_ratings]
                if not known:
                    continue
                crew_ratings[crew_id] = sum(current_ratings[a] for a in known) / len(known)

            # Rating → expected GMT%
            expected_percent = {
                crew_id: 100 + (rating - 1000) / 50.0
                for crew_id, rating in crew_ratings.items()
            }
            if not expected_percent:
                continue

            expected_fleet = sum(expected_percent.values()) / len(expected_percent)
            valid_actuals = [r["GMT_Percent"] for r in piece_results if r["GMT_Percent"] is not None]
            if not valid_actuals:
                continue

            actual_fleet = sum(valid_actuals) / len(valid_actuals)
            piece_adjust = (actual_fleet / expected_fleet) if expected_fleet else 1.0

            adjusted_expected = {cid: exp * piece_adjust for cid, exp in expected_percent.items()}

            for result in piece_results:
                crew_id = result["Crew_ID"]
                actual = result["GMT_Percent"]
                expected = adjusted_expected.get(crew_id)
                if expected is None or actual is None:
                    continue
                crew_gain = (actual - expected)

                # Save for Results table
                result_updates[(crew_id, piece_id)] = (round(expected, 2), round(crew_gain, 2))

                # Split gain across seated athletes
                seat_count = len(crew_athletes.get(crew_id, [])) or 1
                per_athlete_gain = (crew_gain / seat_count) * elo_gearing
                for aid in crew_athletes.get(crew_id, []):
                    athlete_gains[aid] += per_athlete_gain

        # If no real changes, still carry forward
        if not athlete_gains:
            for aid in current_ratings:
                elo_history[aid][current_date] = current_ratings[aid]
            current_date += timedelta(days=1)
            continue

        # Apply gains + save for the day
        for aid, gain in athlete_gains.items():
            if aid in current_ratings:
                current_ratings[aid] += gain
        for aid in current_ratings:
            elo_history[aid][current_date] = current_ratings[aid]

        current_date += timedelta(days=1)

    return elo_history, result_updates


if __name__ == "__main__":
    add_elo()
