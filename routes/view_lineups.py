from flask import Blueprint, render_template, request, redirect, url_for, session, Response
from flask_login import login_required, current_user
from db import get_db_connection

view_lineups_bp = Blueprint('view_lineups', __name__)

@view_lineups_bp.route('/view_lineups/<int:outing_id>')
@login_required
def lineup_view(outing_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Get outing details
        cursor.execute("SELECT * FROM Outings WHERE Outing_ID = %s", (outing_id,))
        outing = cursor.fetchone()

    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT 
                c.Crew_ID,
                c.Hull_ID,
                c.Hull_Name AS Crew_Hull_Name,
                h.Hull_Name AS Hulls_Hull_Name,
                c.Boat_Type AS Crew_Boat_Type,
                h.Boat_Type AS Hulls_Boat_Type,
                c.Crew_Name
            FROM Crews c
            LEFT JOIN Hulls h ON c.Hull_ID = h.Hull_ID
            WHERE c.Outing_ID = %s
            ORDER BY c.Crew_ID
        """, (outing_id,))
        crews = cursor.fetchall()
        for crew in crews:
            crew['Hull_Name'] = crew['Crew_Hull_Name'] or crew['Hulls_Hull_Name']
            crew['Boat_Type'] = crew['Crew_Boat_Type'] or crew['Hulls_Boat_Type']

        with conn.cursor() as cursor:

            cursor.execute("""
            SELECT s.Crew_ID, s.Seat, s.Athlete_ID, s.Athlete_Name
            FROM Seats s
            JOIN Crews c ON s.Crew_ID = c.Crew_ID
            WHERE c.Outing_ID = %s
            ORDER BY s.Seat
            """, (outing_id,))
        assigned_seats = cursor.fetchall()

    conn.close()

    return render_template(
        'view_lineups.html',
        outing=outing,
        outing_id=outing_id,
        crews=crews,
        assigned_seats=assigned_seats
    )
