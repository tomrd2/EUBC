from flask import Blueprint, render_template, request, redirect, url_for, session, Response
from flask_login import login_required, current_user
from db import get_db_connection

lineups_bp = Blueprint('lineups', __name__)

@lineups_bp.route('/lineups/<int:outing_id>')
@login_required
def lineup_view(outing_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Get outing details
        cursor.execute("SELECT * FROM Outings WHERE Outing_ID = %s", (outing_id,))
        outing = cursor.fetchone()

        # Get athletes by group
        cursor.execute("SELECT * FROM Athletes WHERE Side = 'Stroke' AND Coach IS NULL ORDER BY Full_Name")
        strokes = cursor.fetchall()
        cursor.execute("SELECT * FROM Athletes WHERE Side = 'Bow' AND Coach IS NULL ORDER BY Full_Name")
        bows = cursor.fetchall()
        cursor.execute("SELECT * FROM Athletes WHERE Side = 'Both' AND Coach IS NULL ORDER BY Full_Name")
        boths = cursor.fetchall()
        cursor.execute("SELECT * FROM Athletes WHERE Cox = 1 AND Coach IS NULL ORDER BY Full_Name")
        coxes = cursor.fetchall()

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
            SELECT Hull_ID, Hull_Name, Boat_Type 
            FROM Hulls 
            WHERE Hull_ID NOT IN (
                SELECT DISTINCT Hull_ID FROM Crews WHERE Outing_ID = %s AND Hull_ID IS NOT NULL
            )
            ORDER BY Hull_Name
            """, (outing_id,))
        available_hulls = cursor.fetchall()

    conn.close()

    return render_template(
        'lineups.html',
        outing=outing,
        outing_id=outing_id,
        strokes=strokes,
        bows=bows,
        boths=boths,
        coxes=coxes,
        crews=crews,
        available_hulls=available_hulls
    )

@lineups_bp.route('/add_crew/<int:outing_id>', methods=['POST'])
@login_required
def add_crew(outing_id):
    if not current_user.coach:
        return redirect(url_for('lineups.lineup_view', outing_id=outing_id))

    data = request.form
    hull_name = data['Hull_Name'].strip()
    boat_type = data['Boat_Type'].strip()
    crew_name = data['Crew_Name'].strip()

    hull_id = None

    # Check if this hull name matches a known Hull
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT Hull_ID FROM Hulls WHERE Hull_Name = %s", (hull_name,))
        match = cursor.fetchone()
        if match:
            hull_id = match['Hull_ID']

        cursor.execute("""
            INSERT INTO Crews (Outing_ID, Hull_ID, Hull_Name, Boat_Type, Crew_Name)
            VALUES (%s, %s, %s, %s, %s)
        """, (outing_id, hull_id, hull_name, boat_type, crew_name))

        conn.commit()
    conn.close()

    return redirect(url_for('lineups.lineup_view', outing_id=outing_id))

