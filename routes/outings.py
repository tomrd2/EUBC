from flask import Blueprint, render_template, request, redirect, url_for, session, Response
from flask_login import login_required, current_user
from db import get_db_connection

outings_bp = Blueprint('outings', __name__)

@outings_bp.route('/outings')
@login_required
def outings():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM Outings
            ORDER BY Outing_Date DESC
        """)
        outings = cursor.fetchall()
    conn.close()
    return render_template('outings.html', outings=outings)

@outings_bp.route('/add_outing', methods=['POST'])
def add_outing():
    data = request.form
    outing_date = data['Outing_Date']
    outing_name = data['Outing_Name'].strip()
    description = data.get('Description', '')
    location = data.get('Location', '')

    # If outing name is left blank, generate default name
    if not outing_name:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) AS count FROM Outings WHERE Outing_Date = %s
            """, (outing_date,))
            result = cursor.fetchone()
            count = result['count'] if result else 0
        conn.close()
        outing_name = f"Outing {count + 1}"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Outings (Outing_Date, Outing_Name, Description, Location)
            VALUES (%s, %s, %s, %s)
        """, (outing_date, outing_name, description, location))
        conn.commit()
    conn.close()
    return redirect(url_for('outings.outings'))

@outings_bp.route('/edit_outing/<int:outing_id>', methods=['GET', 'POST'])
@login_required
def edit_outing(outing_id):
    if not current_user.coach:
        return redirect(url_for('outings.outings'))

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.form
        cursor.execute("""
            UPDATE Outings
            SET Outing_Date = %s,
                Outing_Name = %s,
                Description = %s,
                Location = %s,
                Published = %s
            WHERE Outing_ID = %s
        """, (
            data['Outing_Date'],
            data['Outing_Name'],
            data['Description'],
            data['Location'],
            int(data.get('Published', 0)),
            outing_id
        ))
        conn.commit()
        conn.close()
        return redirect(url_for('outings.outings'))

    # GET: fetch existing outing to prefill form
    cursor.execute("SELECT * FROM Outings WHERE Outing_ID = %s", (outing_id,))
    outing = cursor.fetchone()
    conn.close()

    return render_template('edit_outing.html', outing=outing)