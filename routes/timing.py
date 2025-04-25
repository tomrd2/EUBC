from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from flask_login import login_required
from db import get_db_connection

timing_bp = Blueprint('timing', __name__)

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

        cursor.execute("SELECT Outing_Date, Outing_Name FROM Outings WHERE Outing_ID = %s", (outing_id,))
        outing = cursor.fetchone()

        # Fetch all Results JOINED with Crews
        cursor.execute("""
            SELECT r.*, c.Hull_Name, c.Crew_Name
            FROM Results r
            JOIN Crews c ON r.Crew_ID = c.Crew_ID
            WHERE r.Piece_ID = %s
            ORDER BY c.Crew_Name ASC
        """, (piece_id,))
        results = cursor.fetchall()

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

    if field not in ['Start', 'Finish', 'Time', 'Comment']:
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

