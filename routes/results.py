from flask import Blueprint, render_template, request, redirect, url_for, session, Response
from flask_login import login_required, current_user
from db import get_db_connection

results_bp = Blueprint('results', __name__)

def format_timedelta(td):
    if not td:
        return None
    total_seconds = td.total_seconds()
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:05.2f}"

@results_bp.route('/results/<int:outing_id>')
@login_required
def results_view(outing_id):

    conn = get_db_connection()

    with conn.cursor() as cursor:
        # Get outing details
        cursor.execute("SELECT * FROM Outings WHERE Outing_ID = %s", (outing_id,))
        outing = cursor.fetchone()

        # Get all crews for this outing
        cursor.execute("SELECT Crew_ID FROM Crews WHERE Outing_ID = %s", (outing_id,))
        crews = cursor.fetchall()

        # Get all pieces for this outing
        cursor.execute("SELECT * FROM Pieces WHERE Outing_ID = %s", (outing_id,))
        pieces = cursor.fetchall()

        # Ensure each crew has a result entry for each piece
        for piece in pieces:
            for crew in crews:
                cursor.execute("""
                    SELECT 1 FROM Results 
                    WHERE Piece_ID = %s AND Crew_ID = %s
                """, (piece['Piece_ID'], crew['Crew_ID']))
                exists = cursor.fetchone()
                if not exists:
                    cursor.execute("""
                        INSERT INTO Results (Piece_ID, Crew_ID)
                        VALUES (%s, %s)
                    """, (piece['Piece_ID'], crew['Crew_ID']))

        conn.commit()  # Don't forget this!

        cursor.execute("""
            SELECT 
                r.Piece_ID,
                r.Time,
                r.GMT_Percent,
                c.Crew_ID,
                c.Crew_Name,
                c.Boat_Type,
                c.Hull_Name
            FROM Results r
            JOIN Crews c ON r.Crew_ID = c.Crew_ID
            WHERE c.Outing_ID = %s
        """, (outing_id,))
        raw_results = cursor.fetchall()

    # Organize results by piece_id for easier display
    from collections import defaultdict
    results_by_piece = defaultdict(list)
    for row in raw_results:
        row['Time'] = format_timedelta(row['Time'])
        results_by_piece[row['Piece_ID']].append(row)
        

    # Sort results for each piece by descending GMT_Percent
    for piece_id, crew_list in results_by_piece.items():
        crew_list.sort(key=lambda r: (r['GMT_Percent'] is not None, r['GMT_Percent']), reverse=True)



    conn.close()

    return render_template(
        'results.html',
        outing=outing,
        outing_id=outing_id,
        pieces=pieces,
        results_by_piece=results_by_piece
    )

@results_bp.route('/det_results/<int:outing_id>')
@login_required
def det_results_view(outing_id):

    conn = get_db_connection()

    with conn.cursor() as cursor:
        # Get outing details
        cursor.execute("SELECT * FROM Outings WHERE Outing_ID = %s", (outing_id,))
        outing = cursor.fetchone()

        # Get all crews for this outing
        cursor.execute("SELECT Crew_ID FROM Crews WHERE Outing_ID = %s", (outing_id,))
        crews = cursor.fetchall()

        # Get all pieces for this outing
        cursor.execute("SELECT * FROM Pieces WHERE Outing_ID = %s", (outing_id,))
        pieces = cursor.fetchall()

        # Ensure each crew has a result entry for each piece
        for piece in pieces:
            for crew in crews:
                cursor.execute("""
                    SELECT 1 FROM Results 
                    WHERE Piece_ID = %s AND Crew_ID = %s
                """, (piece['Piece_ID'], crew['Crew_ID']))
                exists = cursor.fetchone()
                if not exists:
                    cursor.execute("""
                        INSERT INTO Results (Piece_ID, Crew_ID)
                        VALUES (%s, %s)
                    """, (piece['Piece_ID'], crew['Crew_ID']))

        conn.commit()  # Don't forget this!

        cursor.execute("""
            SELECT 
                r.Piece_ID,
                r.Time,
                r.GMT_Percent,
                r.Exp_Percent,
                r.Net_Gain,
                c.Crew_ID,
                c.Crew_Name,
                c.Boat_Type,
                c.Hull_Name
            FROM Results r
            JOIN Crews c ON r.Crew_ID = c.Crew_ID
            WHERE c.Outing_ID = %s
        """, (outing_id,))
        raw_results = cursor.fetchall()

    # Organize results by piece_id for easier display
    from collections import defaultdict
    results_by_piece = defaultdict(list)
    for row in raw_results:
        row['Time'] = format_timedelta(row['Time'])
        results_by_piece[row['Piece_ID']].append(row)
        

    # Sort results for each piece by descending GMT_Percent
    for piece_id, crew_list in results_by_piece.items():
        crew_list.sort(key=lambda r: (r['GMT_Percent'] is not None, r['GMT_Percent']), reverse=True)

    conn.close()

    return render_template(
        'det_results.html',
        outing=outing,
        outing_id=outing_id,
        pieces=pieces,
        results_by_piece=results_by_piece
    )