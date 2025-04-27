from flask_socketio import SocketIO, emit, join_room
from flask import request
from db import get_db_connection

socketio = SocketIO()

@socketio.on('join_outing')
def handle_join_outing(data):
    outing_id = data['outing_id']
    join_room(f"outing_{outing_id}")

@socketio.on('assign_seat')
def handle_assign_seat(data):
    print("assign_seat triggered:", data)  # ✅ Add this log!
    # Save to DB
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            REPLACE INTO Seats (Crew_ID, Athlete_ID, Athlete_Name, Seat)
            VALUES (%s, %s, %s, %s)
        """, (data['crew_id'], data['athlete_id'], data['athlete_name'], data['seat']))
        conn.commit()
    conn.close()

    # Broadcast to others
    emit('seat_updated', data, room=f"outing_{data['outing_id']}", include_self=False)

@socketio.on('remove_seat')
def handle_remove_seat(data):
    print("remove_seat triggered:", data)  # ✅ Debug line

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            DELETE FROM Seats
            WHERE Crew_ID = %s AND Seat = %s
        """, (data['crew_id'], data['seat']))
        conn.commit()
    conn.close()

    emit('seat_updated', {
        'crew_id': data['crew_id'],
        'seat': data['seat'],
        'athlete_id': None,
        'athlete_name': ''
    }, room=f"outing_{data['outing_id']}", include_self=False)

@socketio.on('join_piece')
def handle_join_piece(data):
    piece_id = data['piece_id']
    join_room(f"piece_{piece_id}")
    print(f"User joined piece {piece_id}")

@socketio.on('result_update')
def handle_result_update(data):
    piece_id = data['piece_id']
    crew_id = data['crew_id']
    field = data['field']
    value = data['value']

    conn = get_db_connection()
    with conn.cursor() as cursor:
        query = f"UPDATE Results SET {field} = %s WHERE Piece_ID = %s AND Crew_ID = %s"
        cursor.execute(query, (value, piece_id, crew_id))
        conn.commit()
    conn.close()

    emit('result_updated', {
        'piece_id': piece_id,
        'crew_id': crew_id,
        'field': field,
        'value': value
    }, room=f"piece_{piece_id}", include_self=False)


