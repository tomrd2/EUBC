from flask import Blueprint, Flask, render_template, request, redirect, url_for, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import pymysql
from db import get_db_connection

athletes_bp = Blueprint('athletes', __name__)

# Athletes Page
@athletes_bp.route('/athletes')
def athletes():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Athletes where Coach IS NULL")
        data = cursor.fetchall()
    conn.close()
    return render_template('athletes.html', athletes=data)

@athletes_bp.route('/add', methods=['POST'])
def add_athlete():
    data = request.form
    sculls_value = 1 if 'Sculls' in data else 0
    cox_value = 1 if 'Cox' in data else 0

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Athletes (Full_Name, Initials, M_W, Side, Sculls, Cox, Joined, Email)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data['Full_Name'], data['Initials'], data['M_W'],
            data['Side'], sculls_value, cox_value, data['Joined'], data['Email']
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('athletes.athletes'))

@athletes_bp.route('/edit/<int:athlete_id>', methods=['POST'])
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
    return redirect(url_for('athletes.athletes'))