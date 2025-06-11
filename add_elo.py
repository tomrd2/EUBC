from datetime import date, timedelta
from collections import defaultdict
from db import get_db_connection

def add_elo():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        select r.Crew_ID, r.Piece_ID, r.GMT_Percent, o.Outing_Date
        from Results r
        left join Pieces p on r.Piece_ID = p.Piece_ID
        left join Outings o on p.Outing_ID = o.Outing_ID
        ORDER BY o.Outing_Date, r.Piece_ID
    """)
    results = cursor.fetchall()
    dates = [datetime.strptime(row[3], "%Y-%m-%d") for row in results]
    earliest_date = min(dates)
    start_date = earliest_date - timedelta(days=1)

    cursor.execute("""
        SELECT * FROM Seats
    """)
    seats = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM Athletes
    """)
    athletes = cursor.fetchall()

    elo_ratings = []

    for athlete in athletes:
        elo_ratings.append((start_date,athlete["Athlete_ID"],500))

    piece = []

    for result in results:
        if not last_piece:
            last_piece = result['Piece_ID']
        
        if last_piece != result['Piece_ID']
            elo_ratings = (piece, elo_ratings, seats)
        
        last_piece = result['Piece_ID']
        piece.append(result)
            