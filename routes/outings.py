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
            WHERE Outing_Date >= CURDATE() - INTERVAL 2 MONTH
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