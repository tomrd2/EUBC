from flask import Blueprint, render_template, request, redirect, url_for
from your_db_utils import get_db_connection  # if you have a shared DB function

athletes_bp = Blueprint('athletes', __name__, url_prefix='/athletes')

@app.route('/athletes')
def athletes():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Athletes where coach <> 1")
        data = cursor.fetchall()
    conn.close()
    return render_template('athletes.html', athletes=data)

@app.route('/add', methods=['POST'])
def add_athlete():
    data = request.form
    sculls_value = 1 if 'Sculls' in data else 0
    cox_value = 1 if 'Cox' in data else 0

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Athletes (Athlete_ID, Full_Name, Initials, M_W, Side, Sculls, Cox, Joined, Email)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data['Athlete_ID'], data['Full_Name'], data['Initials'], data['M_W'],
            data['Side'], sculls_value, cox_value, data['Joined'], data['Email']
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('athletes'))

@app.route('/edit/<int:athlete_id>', methods=['POST'])
def edit_athlete(athlete_id):
    data = request.form
    sculls_value = 1 if 'Sculls' in data else 0
    cox_value = 1 if 'Cox' in data else 0

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE Athletes SET Full_Name=%s, Initials=%s, M_W=%s, Side=%s, Sculls=%s, Cox=%s, Joined=%s, Email=%s
            WHERE Athlete_ID=%s
        """, (
            data['Full_Name'], data['Initials'], data['M_W'], data['Side'],
            sculls_value, cox_value, data['Joined'], data['Email'], athlete_id
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('athletes'))
