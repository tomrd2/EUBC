from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from flask_login import login_required
from db import get_db_connection
from datetime import timedelta
from flask_socketio import SocketIO, emit
from sockets import socketio

timing_bp = Blueprint('timing', __name__)

def time_to_seconds(t):
    if isinstance(t, timedelta):
        return t.total_seconds()
    elif isinstance(t, str):
        try:
            h, m, s = map(int, t.split(':'))
            return h * 3600 + m * 60 + s
        except ValueError:
            return 0
    else:
        return 0


@timing_bp.route('/timing/<int:piece_id>')
@login_required
def timing_view(piece_id):
    conn = get_db_connection()

    with conn.cursor() as cursor:
        # Get Piece and Outing info
        cursor.execute("SELECT Outing_ID, Description FROM Pieces WHERE Piece_ID = %s", (piece_id,))
        piece = cursor.fetchone()

        if not piece:
            conn.close()
            return "Piece not found", 404

        outing_id = piece['Outing_ID']
        piece_description = piece['Description']

        cursor.execute("SELECT Outing_ID, Outing_Date, Outing_Name FROM Outings WHERE Outing_ID = %s", (outing_id,))
        outing = cursor.fetchone()

        # Get all Crew_IDs for the outing
        cursor.execute("SELECT Crew_ID FROM Crews WHERE Outing_ID = %s", (outing_id,))
        crew_ids = [row['Crew_ID'] for row in cursor.fetchall()]

        # Get existing Result rows for this piece
        cursor.execute("SELECT Crew_ID FROM Results WHERE Piece_ID = %s", (piece_id,))
        existing_result_crew_ids = {row['Crew_ID'] for row in cursor.fetchall()}

        # Find crews missing a Results row
        missing_crew_ids = set(crew_ids) - existing_result_crew_ids

        # Insert missing rows with default (NULL) values
        for crew_id in missing_crew_ids:
            cursor.execute("""
                INSERT INTO Results (Piece_ID, Crew_ID) VALUES (%s, %s)
            """, (piece_id, crew_id))

        conn.commit()

        # Fetch all GMT values into a dictionary: { "Boat_Type": timedelta }
        cursor.execute("SELECT Boat_Type, GMT FROM GMTs")
        gmts = {row['Boat_Type']: row['GMT'] for row in cursor.fetchall()}

        # Fetch all Results JOINED with Crews
        cursor.execute("""
            SELECT r.*, c.Hull_Name, c.Crew_Name, c.Boat_Type, p.Distance, p.Outing_ID
            FROM Results r
            JOIN Crews c ON r.Crew_ID = c.Crew_ID
            JOIN Pieces p ON r.Piece_ID = p.Piece_ID
            WHERE r.Piece_ID = %s
            ORDER BY c.Crew_Name ASC
        """, (piece_id,))

        results = cursor.fetchall()

        for row in results:
            print('Piece_ID:',row.get('Piece_ID'))
            print('Distance: ',row.get('Distance'))

            # Format Start
            if row['Start']:
                if hasattr(row['Start'], 'strftime'):
                    row['Start_formatted'] = row['Start'].strftime('%H:%M:%S.%f')[:-5]
                else:
                    # timedelta case
                    total_seconds = row['Start'].total_seconds()
                    h = int(total_seconds // 3600)
                    m = int((total_seconds % 3600) // 60)
                    s = total_seconds % 60
                    row['Start_formatted'] = f"{h:02d}:{m:02d}:{s:04.1f}"
            else:
                row['Start_formatted'] = ''

            # Format Finish
            if row['Finish']:
                if hasattr(row['Finish'], 'strftime'):
                    row['Finish_formatted'] = row['Finish'].strftime('%H:%M:%S.%f')[:-5]
                else:
                    total_seconds = row['Finish'].total_seconds()
                    h = int(total_seconds // 3600)
                    m = int((total_seconds % 3600) // 60)
                    s = total_seconds % 60
                    row['Finish_formatted'] = f"{h:02d}:{m:02d}:{s:04.1f}"
            else:
                row['Finish_formatted'] = ''

            # Format Time
            if row['Time']:
                total_seconds = row['Time'].total_seconds()
                h = int(total_seconds // 3600)
                m = int((total_seconds % 3600) // 60)
                s = total_seconds % 60
                row['Time_formatted'] = f"{h:02d}:{m:02d}:{s:04.1f}"
            else:
                row['Time_formatted'] = ''

            # Get raw GMT time for this boat type
            raw_gmt = gmts.get(row['Boat_Type'])
            print(f"🧾 Raw GMT value from DB for {row['Boat_Type']}: {raw_gmt}")
    
            # Convert to seconds for use in JavaScript
            row['GMT_value'] = time_to_seconds(raw_gmt)

    conn.close()

    return render_template('timing.html',
                            piece_id=piece_id,
                            outing=outing,
                            piece_description=piece_description,
                            results=results)

@timing_bp.route('/update_result', methods=['POST'])
@login_required
def update_result():
    data = request.json
    field = data['field']
    value = data['value']
    piece_id = data['piece_id']
    crew_id = data['crew_id']

    if field not in ['Start', 'Finish', 'Time', 'Comment', 'GMT_Percent']:
        return jsonify({'error': 'Invalid field'}), 400

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(f"""
            UPDATE Results
            SET {field} = %s
            WHERE Piece_ID = %s AND Crew_ID = %s
        """, (value, piece_id, crew_id))
        conn.commit()
    conn.close()

    return jsonify({'status': 'success'})

@socketio.on('result_update')
def handle_result_update(data):
    field = data.get('field')
    value = data.get('value')
    piece_id = data.get('piece_id')
    crew_id = data.get('crew_id')

    if not (field and piece_id and crew_id):
        print("⚠️ Invalid update data:", data)
        return

    conn = get_db_connection()
    with conn.cursor() as cursor:
        query = f"UPDATE Results SET {field} = %s WHERE Piece_ID = %s AND Crew_ID = %s"
        cursor.execute(query, (value, piece_id, crew_id))
        conn.commit()
    conn.close()

    emit('result_updated', data, broadcast=True)


