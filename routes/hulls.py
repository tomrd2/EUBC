from flask import Blueprint, Flask, render_template, request, redirect, url_for, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import pymysql
from db import get_db_connection

hulls_bp = Blueprint('hulls', __name__)

# Hulls Page
@hulls_bp.route('/hulls')
def hulls():
    if not current_user.coach:
        return render_template('athlete_home.html', user=current_user)
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Hulls")
        hulls = cursor.fetchall()
    conn.close()
    return render_template('hulls.html', hulls=hulls)

@hulls_bp.route('/add_hull', methods=['POST'])
def add_hull():
    data = request.form
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Hulls (Hull_Name, Boat_Type, Max_Weight)
            VALUES (%s, %s, %s)
        """, (
            data['Hull_Name'], data['Boat_Type'], data['Max_Weight']
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('hulls.hulls'))

@hulls_bp.route('/edit_hull/<int:hull_id>', methods=['POST'])
def edit_hull(hull_id):
    data = request.form
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE Hulls SET Hull_Name=%s, Boat_Type=%s, Max_Weight=%s
            WHERE Hull_ID=%s
        """, (
            data['Hull_Name'], data['Boat_Type'], data['Max_Weight'], hull_id
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('hulls.hulls'))