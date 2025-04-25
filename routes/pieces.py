from flask import Blueprint, render_template, request, redirect, url_for, session, Response
from flask_login import login_required, current_user
from db import get_db_connection

pieces_bp = Blueprint('pieces', __name__)

@pieces_bp.route('/pieces/<int:outing_id>')
@login_required
def piece_view(outing_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Get outing details
        cursor.execute("SELECT * FROM Pieces WHERE Outing_ID = %s", (outing_id,))
        pieces = cursor.fetchall()
    conn.close()
    return render_template('pieces.html', pieces=pieces, outing_id=outing_id)

@pieces_bp.route('/add_piece', methods=['POST'])
def add_piece():
    data = request.form
    outing_id = data['Outing_ID']
    distance = data['Distance']
    description = data.get('Description', '')
    rate_cap = data.get('Rate_Cap', '')

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Pieces (Outing_ID, Distance, Description, Rate_Cap)
            VALUES (%s, %s, %s, %s)
        """, (outing_id, distance, description, rate_cap))
        conn.commit()
    conn.close()
    return redirect(url_for('pieces.piece_view', outing_id=outing_id))

@pieces_bp.route('/edit_piece/<int:piece_id>', methods=['GET', 'POST'])
@login_required
def edit_piece(piece_id):
    if not current_user.coach:
        return redirect(url_for('coach_home'))

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.form
        cursor.execute("""
            UPDATE Pieces
            SET Distance = %s,
                Description = %s,
                Rate_Cap = %s
            WHERE Piece_ID = %s
        """, (
            data['Distance'],
            data['Description'],
            data['Rate_Cap'],
            piece_id
        ))
        # 🟡 Get the outing ID for redirect
        cursor.execute("SELECT Outing_ID FROM Pieces WHERE Piece_ID = %s", (piece_id,))
        outing = cursor.fetchone()
        conn.commit()
        conn.close()

        return redirect(url_for('pieces.piece_view', outing_id=outing['Outing_ID']))

    # GET: fetch existing piece
    cursor.execute("SELECT * FROM Pieces WHERE Piece_ID = %s", (piece_id,))
    piece = cursor.fetchone()
    conn.close()

    return render_template('edit_piece.html', piece=piece)