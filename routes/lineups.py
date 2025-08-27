from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, Response, jsonify, current_app, g
)
from flask_login import login_required, current_user
from db import get_db_connection, tenant_context
from sockets import socketio  # ✅ Import the initialized socketio instance
from flask_socketio import join_room, emit
from flask import g, current_app
import logging
log = logging.getLogger(__name__)

lineups_bp = Blueprint('lineups', __name__)

def outing_room(outing_id: int) -> str:
    # Try user → g → request args; fall back to 'default'
    tenant = getattr(current_user, "tenant_key", None) \
          or getattr(g, "tenant_key", None) \
          or ((request.view_args or {}).get("club") if hasattr(request, "view_args") else None)
    return f"outing_{tenant or 'default'}_{outing_id}"


@lineups_bp.route('/lineups/<int:outing_id>')
@login_required
def lineup_view(outing_id):
    if not current_user.coach:
        return redirect(url_for('view_lineups.lineup_view', outing_id=outing_id))

    gender_filter = request.args.get('gender', 'all')  # default to "all"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Get outing details
        cursor.execute("SELECT * FROM Outings WHERE Outing_ID = %s", (outing_id,))
        outing = cursor.fetchone()

        # Build gender filter condition
        gender_condition = ""
        gender_param = []
        if gender_filter in ('M', 'W'):
            gender_condition = "AND M_W = %s"
            gender_param = [gender_filter]

        # Fetch filtered athletes
        cursor.execute(f"""
            SELECT * FROM Athletes
            WHERE Side = 'Stroke' AND (Coach != 1 OR Coach IS NULL) {gender_condition}
            ORDER BY Full_Name
        """, gender_param)
        strokes = cursor.fetchall()

        cursor.execute(f"""
            SELECT * FROM Athletes
            WHERE Side = 'Bow' AND (Coach != 1 OR Coach IS NULL) {gender_condition}
            ORDER BY Full_Name
        """, gender_param)
        bows = cursor.fetchall()

        cursor.execute(f"""
            SELECT * FROM Athletes
            WHERE Side = 'Both' AND (Coach != 1 OR Coach IS NULL) {gender_condition}
            ORDER BY Full_Name
        """, gender_param)
        boths = cursor.fetchall()

        cursor.execute(f"""
            SELECT * FROM Athletes
            WHERE Side = 'Neither' AND (Coach != 1 OR Coach IS NULL) {gender_condition}
            ORDER BY Full_Name
        """, gender_param)
        neithers = cursor.fetchall()

        cursor.execute("SELECT * FROM Athletes WHERE Side = 'Cox' AND (Coach != 1 OR Coach is null) ORDER BY Full_Name")
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
                ORDER BY Boat_Type DESC
            """, (outing_id,))
            available_hulls = cursor.fetchall()

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT s.Crew_ID, s.Seat, s.Athlete_ID, s.Athlete_Name
                FROM Seats s
                JOIN Crews c ON s.Crew_ID = c.Crew_ID
                WHERE c.Outing_ID = %s
                ORDER BY s.Crew_ID, s.Seat
            """, (outing_id,))
            assigned_seats = cursor.fetchall()

        from collections import defaultdict

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT s.*
                FROM Seats s
                JOIN Crews c ON s.Crew_ID = c.Crew_ID
                WHERE c.Outing_ID = %s
            """, (outing_id,))
            seats_raw = cursor.fetchall()

        seat_assignments = defaultdict(dict)
        for seat in seats_raw:
            crew_id = seat['Crew_ID']
            seat_number = str(seat['Seat'])
            seat_assignments[crew_id][seat_number] = seat

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT Outing_ID, Outing_Date, Outing_Name
                FROM Outings
                WHERE Outing_Date >= CURDATE() - INTERVAL 30 DAY
                ORDER BY Outing_Date DESC
            """)
            recent_outings = cursor.fetchall()

    conn.close()

    return render_template(
        'lineups.html',
        outing=outing,
        outing_id=outing_id,
        strokes=strokes,
        bows=bows,
        boths=boths,
        neithers=neithers,
        coxes=coxes,
        crews=crews,
        available_hulls=available_hulls,
        assigned_seats=assigned_seats,
        seat_assignments=seat_assignments,
        recent_outings=recent_outings,
        gender_filter=gender_filter
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
            print("New Hull_ID: ", hull_id)

        cursor.execute("""
            INSERT INTO Crews (Outing_ID, Hull_ID, Hull_Name, Boat_Type, Crew_Name)
            VALUES (%s, %s, %s, %s, %s)
        """, (outing_id, hull_id, hull_name, boat_type, crew_name))

        conn.commit()
    conn.close()

    gender = request.form.get('gender')
    return redirect(url_for('lineups.lineup_view', outing_id=outing_id, **({'gender': gender} if gender else {})))

@lineups_bp.route('/publish_lineup/<int:outing_id>', methods=['POST'])
@login_required
def publish_lineup(outing_id):
    if not current_user.coach:
        return redirect(url_for('view_lineups.lineup_view', outing_id=outing_id))

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE Outings SET Published = 1 WHERE Outing_ID = %s", (outing_id,))
        conn.commit()
    conn.close()

    gender = request.form.get('gender')
    return redirect(url_for('lineups.lineup_view', outing_id=outing_id, **({'gender': gender} if gender else {})))

@lineups_bp.route('/clone_lineup/<int:outing_id>', methods=['POST'])
@login_required
def clone_lineup(outing_id):
    gender = request.form.get('gender')
    source_outing_id = request.form.get('source_outing_id')

    if not current_user.coach or not source_outing_id:
        return redirect(url_for('lineups.lineup_view', outing_id=outing_id))

    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Step 1: Delete current crews/seats
        cursor.execute("""
            DELETE FROM Seats WHERE Crew_ID IN (
                SELECT Crew_ID FROM Crews WHERE Outing_ID = %s
            )
        """, (outing_id,))
        cursor.execute("DELETE FROM Crews WHERE Outing_ID = %s", (outing_id,))

        # Step 2: Fetch source crews
        cursor.execute("""
            SELECT Crew_ID, Hull_ID, Hull_Name, Boat_Type, Crew_Name
            FROM Crews
            WHERE Outing_ID = %s
        """, (source_outing_id,))
        source_crews = cursor.fetchall()

        crew_id_map = {}

        # Step 3: Insert each crew and track new IDs
        for crew in source_crews:
            cursor.execute("""
                INSERT INTO Crews (Outing_ID, Hull_ID, Hull_Name, Boat_Type, Crew_Name)
                VALUES (%s, %s, %s, %s, %s)
            """, (outing_id, crew['Hull_ID'], crew['Hull_Name'], crew['Boat_Type'], crew['Crew_Name']))
            new_crew_id = cursor.lastrowid
            crew_id_map[crew['Crew_ID']] = new_crew_id

        # Step 4: Clone Seats
        for old_crew_id, new_crew_id in crew_id_map.items():
            cursor.execute("""
                SELECT Seat, Athlete_ID, Athlete_Name
                FROM Seats
                WHERE Crew_ID = %s
            """, (old_crew_id,))
            seats = cursor.fetchall()
            for seat in seats:
                cursor.execute("""
                    INSERT INTO Seats (Crew_ID, Seat, Athlete_ID, Athlete_Name)
                    VALUES (%s, %s, %s, %s)
                """, (new_crew_id, seat['Seat'], seat['Athlete_ID'], seat['Athlete_Name']))

        conn.commit()
    conn.close()

    return redirect(url_for('lineups.lineup_view', outing_id=outing_id, **({'gender': gender} if gender else {})))

@lineups_bp.post('/api/assign-seat')
@login_required
def api_assign_seat():
    if not current_user.coach:
        return jsonify(ok=False, error="forbidden"), 403
    data = request.get_json(force=True) or {}
    outing_id   = data.get('outing_id')
    crew_id     = int(data.get('crew_id'))
    seat        = str(data.get('seat'))         # keep as string (supports 'Cox')
    athlete_id  = data.get('athlete_id')
    athlete_id  = int(athlete_id) if (str(athlete_id).isdigit()) else None
    athlete_name= data.get('athlete_name') or ''

    with tenant_context(current_app, current_user.tenant_key):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO Seats (Crew_ID, Seat, Athlete_ID, Athlete_Name)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        Athlete_ID = VALUES(Athlete_ID),
                        Athlete_Name = VALUES(Athlete_Name)
                """, (crew_id, seat, athlete_id, athlete_name))
            conn.commit()
        finally:
            conn.close()
    return jsonify(ok=True)

@lineups_bp.post('/api/remove-seat')
@login_required
def api_remove_seat():
    if not current_user.coach:
        return jsonify(ok=False, error="forbidden"), 403
    data = request.get_json(force=True) or {}
    crew_id = int(data.get('crew_id'))
    seat    = str(data.get('seat'))

    with tenant_context(current_app, current_user.tenant_key):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM Seats WHERE Crew_ID=%s AND Seat=%s", (crew_id, seat))
            conn.commit()
        finally:
            conn.close()
    return jsonify(ok=True)

@lineups_bp.post('/api/update-crew-field')
@login_required
def api_update_crew_field():
    if not current_user.coach:
        return jsonify(ok=False, error="forbidden"), 403
    data = request.get_json(force=True) or {}
    crew_id = int(data.get('crew_id'))
    field   = data.get('field')
    value   = data.get('value') or ''

    if field not in ('Hull_Name', 'Boat_Type', 'Crew_Name'):
        return jsonify(ok=False, error="bad field"), 400

    with tenant_context(current_app, current_user.tenant_key):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                if field == 'Hull_Name':
                    # optional: set Hull_ID if name matches
                    cur.execute("SELECT Hull_ID FROM Hulls WHERE Hull_Name=%s", (value,))
                    hull = cur.fetchone()
                    if hull:
                        cur.execute("UPDATE Crews SET Hull_Name=%s, Hull_ID=%s WHERE Crew_ID=%s",
                                    (value, hull['Hull_ID'], crew_id))
                    else:
                        cur.execute("UPDATE Crews SET Hull_Name=%s, Hull_ID=NULL WHERE Crew_ID=%s",
                                    (value, crew_id))
                else:
                    cur.execute(f"UPDATE Crews SET {field}=%s WHERE Crew_ID=%s", (value, crew_id))
            conn.commit()
        finally:
            conn.close()
    return jsonify(ok=True)

@lineups_bp.post('/api/delete-crew')
@login_required
def api_delete_crew():
    if not current_user.coach:
        return jsonify(ok=False, error="forbidden"), 403
    data = request.get_json(force=True) or {}
    crew_id = int(data.get('crew_id'))

    with tenant_context(current_app, current_user.tenant_key):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM Seats WHERE Crew_ID=%s", (crew_id,))
                cur.execute("DELETE FROM Crews WHERE Crew_ID=%s", (crew_id,))
            conn.commit()
        finally:
            conn.close()
    return jsonify(ok=True)



