from flask import Blueprint, Flask, render_template, request, redirect, url_for, session, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import pymysql
from db import get_db_connection

athletes_bp = Blueprint('athletes', __name__)

# Athletes Page
@athletes_bp.route('/athletes')
@login_required
def athletes():
    if not current_user.coach:
        return redirect(url_for('core.app_menu'))

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Athletes ORDER By Coach, Full_Name")
        data = cursor.fetchall()
    conn.close()
    return render_template('athletes.html', athletes=data)

@athletes_bp.route('/add', methods=['POST'])
@login_required
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
@login_required
def edit_athlete(athlete_id):
    data = request.form
    sculls_value = 1 if 'Sculls' in data else 0
    coach_value  = 1 if 'Coach'  in data else 0  # <-- NEW

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE Athletes
            SET Full_Name=%s,
                Initials=%s,
                M_W=%s,
                Side=%s,
                Sculls=%s,
                Coach=%s,
                Joined=%s,
                Email=%s
            WHERE Athlete_ID=%s
        """, (
            data['Full_Name'], data['Initials'], data['M_W'], data['Side'],
            sculls_value, coach_value, data['Joined'], data['Email'], athlete_id
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('athletes.athletes'))


@athletes_bp.route('/reset_password/<int:athlete_id>', methods=['POST'])
@login_required
def reset_password(athlete_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Get all athletes who don't yet have a password
        cursor.execute("SELECT Athlete_ID, Initials FROM Athletes")
        athletes = cursor.fetchall()

        for athlete in athletes:
            if athlete_id == athlete['Athlete_ID']:
                initials = athlete['Initials']

                # You can choose your default password pattern here
                default_password = f"{initials.lower()}_eubc"  # e.g., "jd_123"
                hashed = generate_password_hash(default_password)

                # Update database with the hashed password
                cursor.execute(
                    "UPDATE Athletes SET Password_Hash = %s WHERE Athlete_ID = %s",
                    (hashed, athlete_id)
                )
                print(f"Set password for Athlete_ID {athlete_id} to '{default_password}'")

        conn.commit()
    conn.close()

    flash(f"Password for athlete {athlete_id} reset to default.", "success")
    return redirect(url_for('athletes.athletes')) 

def _none_if_empty(v):
    v = v.strip() if isinstance(v, str) else v
    return None if v in ("", None) else v

@athletes_bp.route('/athlete/<int:athlete_id>', methods=['GET', 'POST'], endpoint='athlete_detail')
@login_required
def athlete_detail(athlete_id):
    conn = get_db_connection()
    try:
        is_coach = bool(current_user.coach)

        with conn.cursor() as cur:
            if request.method == 'POST':
                # Always editable for both
                full_name = request.form.get('Full_Name', '').strip()
                initials  = request.form.get('Initials', '').strip()
                email     = _none_if_empty(request.form.get('Email', ''))
                dropbox   = _none_if_empty(request.form.get('DropBox', ''))
                max_hr    = _none_if_empty(request.form.get('Max_HR', ''))
                rest_hr   = _none_if_empty(request.form.get('Rest_HR', ''))
                if isinstance(max_hr, str) and max_hr.lstrip('-').isdigit(): max_hr = int(max_hr)
                if isinstance(rest_hr, str) and rest_hr.lstrip('-').isdigit(): rest_hr = int(rest_hr)

                cols = [
                    ("Full_Name", full_name),
                    ("Initials",  initials),
                    ("Email",     email),
                    ("DropBox",   dropbox),
                    ("Max_HR",    max_hr),
                    ("Rest_HR",   rest_hr),
                ]

                if is_coach:
                    # Coaches can also edit these, incl. Start_Rating
                    m_w    = request.form.get('M_W', '').strip()
                    side   = _none_if_empty(request.form.get('Side', ''))
                    joined = _none_if_empty(request.form.get('Joined', ''))
                    sculls = 1 if 'Sculls' in request.form else 0
                    cox    = 1 if 'Cox'    in request.form else 0
                    coach  = 1 if 'Coach'  in request.form else 0

                    start_rating = _none_if_empty(request.form.get('Start_Rating', ''))
                    if isinstance(start_rating, str) and start_rating.lstrip('-').isdigit():
                        start_rating = int(start_rating)

                    cols += [
                        ("M_W",          m_w),
                        ("Side",         side),
                        ("Joined",       joined),
                        ("Sculls",       sculls),
                        ("Cox",          cox),
                        ("Coach",        coach),
                        ("Start_Rating", start_rating),  # ✅ coach-only editable
                    ]

                set_clause = ", ".join([f"{c}=%s" for c,_ in cols])
                params = [v for _,v in cols] + [athlete_id]
                cur.execute(f"UPDATE Athletes SET {set_clause} WHERE Athlete_ID=%s", params)

                # Password change
                new_password = request.form.get('New_Password', '').strip()
                if new_password:
                    cur.execute(
                        "UPDATE Athletes SET Password_Hash=%s WHERE Athlete_ID=%s",
                        (generate_password_hash(new_password), athlete_id)
                    )

                conn.commit()
                flash("Athlete details updated.", "success")
                return redirect(url_for('athletes.athletes'))

            # GET
            cur.execute("SELECT * FROM Athletes WHERE Athlete_ID = %s", (athlete_id,))
            athlete = cur.fetchone()
            if not athlete:
                return "Athlete not found", 404

        # pass is_coach so the template can disable the field for athletes
        return render_template('athlete_detail.html', athlete=athlete, is_coach=is_coach)

    finally:
        conn.close()
