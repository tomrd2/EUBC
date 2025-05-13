from flask import Blueprint, render_template, request, redirect, url_for, session, Response
from flask_login import login_required, current_user
from db import get_db_connection
from sockets import socketio  # ✅ Import the initialized socketio instance
from flask_socketio import join_room, emit

lineups_bp = Blueprint('lineups', __name__)

@lineups_bp.route('/lineups/<int:outing_id>')
@login_required
def lineup_view(outing_id):
    if not current_user.coach:
        return redirect(url_for('view_lineups.lineup_view', outing_id=outing_id))

    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Get outing details
        cursor.execute("SELECT * FROM Outings WHERE Outing_ID = %s", (outing_id,))
        outing = cursor.fetchone()

        # Get athletes by group
        cursor.execute("SELECT * FROM Athletes WHERE Side = 'Stroke' AND (Coach != 1 OR Coach is null) ORDER BY Full_Name")
        strokes = cursor.fetchall()
        cursor.execute("SELECT * FROM Athletes WHERE Side = 'Bow' AND (Coach != 1 OR Coach is null) ORDER BY Full_Name")
        bows = cursor.fetchall()
        cursor.execute("SELECT * FROM Athletes WHERE Side = 'Both' AND (Coach != 1 OR Coach is null) ORDER BY Full_Name")
        boths = cursor.fetchall()
        cursor.execute("SELECT * FROM Athletes WHERE Side = 'Neither' AND (Coach != 1 OR Coach is null) ORDER BY Full_Name")
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
            """, (outing_id,))
        assigned_seats = cursor.fetchall()

        from collections import defaultdict

        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM Seats")
            seats_raw = cursor.fetchall()

            seat_assignments = defaultdict(dict)
            for seat in seats_raw:
                crew_id = seat['Crew_ID']
                seat_number = seat['Seat']
                seat_assignments[crew_id][str(seat_number)] = seat

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
        seat_assignments=seat_assignments
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

    return redirect(url_for('lineups.lineup_view', outing_id=outing_id))

@socketio.on('delete_crew')
def handle_delete_crew(data):
    crew_id = data.get('crew_id')
    outing_id = data.get('outing_id')

    if not crew_id:
        return

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM Crews WHERE Crew_ID = %s", (crew_id,))
        cursor.execute("DELETE FROM Seats WHERE Crew_ID = %s", (crew_id,))
        conn.commit()
    conn.close()

    emit('crew_deleted', {'crew_id': crew_id}, room=f'outing_{outing_id}')

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

    return redirect(url_for('lineups.lineup_view', outing_id=outing_id))

@socketio.on('crew_update')
def handle_crew_update(data):
    crew_id = data['crew_id']
    field = data['field']
    value = data['value']

    if field not in ['Hull_Name', 'Boat_Type', 'Crew_Name']:
        print("❌ Invalid field:", field)
        return

    conn = get_db_connection()
    with conn.cursor() as cursor:
        if field == 'Hull_Name':
            # Look up Hull_ID from Hulls table
            cursor.execute("SELECT Hull_ID FROM Hulls WHERE Hull_Name = %s", (value,))
            hull = cursor.fetchone()

            if hull:
                hull_id = hull['Hull_ID']
                cursor.execute("""
                    UPDATE Crews SET Hull_Name = %s, Hull_ID = %s WHERE Crew_ID = %s
                """, (value, hull_id, crew_id))
                print(f"✅ Updated Hull_Name to '{value}' and Hull_ID to {hull_id} for Crew_ID {crew_id}")
            else:
                cursor.execute("""
                    UPDATE Crews SET Hull_Name = %s, Hull_ID = NULL WHERE Crew_ID = %s
                """, (value, crew_id))
                print(f"⚠️ Hull_Name '{value}' not found, set Hull_ID to NULL for Crew_ID {crew_id}")
        else:
            cursor.execute(f"""
                UPDATE Crews SET {field} = %s WHERE Crew_ID = %s
            """, (value, crew_id))
            print(f"✅ Updated {field} to '{value}' for Crew_ID {crew_id}")

        conn.commit()
    conn.close()

    # Broadcast update to all other clients
    emit('crew_field_updated', data, broadcast=True)

@socketio.on('assign_seat')
def handle_assign_seat(data):
    outing_id = data['outing_id']
    crew_id = data['crew_id']
    seat = data['seat']
    athlete_id = data['athlete_id']
    athlete_name = data['athlete_name']

    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Remove any existing seat with same crew+seat
        cursor.execute("""
            DELETE FROM Seats WHERE Crew_ID = %s AND Seat = %s
        """, (crew_id, seat))

        # Insert new assignment
        cursor.execute("""
            INSERT INTO Seats (Crew_ID, Seat, Athlete_ID, Athlete_Name)
            VALUES (%s, %s, %s, %s)
        """, (crew_id, seat, athlete_id, athlete_name))

        conn.commit()
    conn.close()

    emit('seat_updated', data, room=f'outing_{outing_id}')


@socketio.on('join_outing')
def handle_join_outing(data):
    outing_id = data.get('outing_id')
    join_room(f'outing_{outing_id}')




