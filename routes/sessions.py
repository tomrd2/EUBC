from flask import Blueprint, render_template, request, redirect, url_for, session, Response
from flask_login import login_required, current_user
from db import get_db_connection
from io import StringIO
import csv

sessions_bp = Blueprint('sessions', __name__)

@sessions_bp.route('/sessions')
@login_required
def sessions():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        athlete_list = []
        filters = []
        query = """
            SELECT s.*, a.Full_Name
            FROM Sessions s
            JOIN Athletes a ON s.Athlete_ID = a.Athlete_ID
            WHERE 1=1
        """

        if current_user.coach:
            if 'athlete_id' in request.args and request.args['athlete_id']:
                query += " AND s.Athlete_ID = %s"
                filters.append(request.args['athlete_id'])
        else:
            query += " AND s.Athlete_ID = %s"
            filters.append(current_user.id)

        if 'activity' in request.args and request.args['activity']:
            query += " AND s.Activity = %s"
            filters.append(request.args['activity'])

        if 'type' in request.args and request.args['type']:
            query += " AND s.Type = %s"
            filters.append(request.args['type'])

        query += " ORDER BY s.Session_Date DESC"
        cursor.execute(query, filters)
        session_data = cursor.fetchall()

        if current_user.coach:
            cursor.execute("SELECT Athlete_ID, Full_Name FROM Athletes ORDER BY Full_Name ASC")
            athlete_list = cursor.fetchall()

    conn.close()

    return render_template(
        'sessions.html',
        sessions=session_data,
        athletes=athlete_list,
        selected_athlete=request.args.get('athlete_id', ''),
        selected_activity=request.args.get('activity', ''),
        selected_type=request.args.get('type', '')
    )

@sessions_bp.route('/sessions/new', methods=['GET', 'POST'])
@login_required
def add_session():
    if request.method == 'GET' and current_user.coach:
        with get_db_connection().cursor() as cursor:
            cursor.execute("SELECT Athlete_ID, Full_Name FROM Athletes ORDER BY Full_Name ASC")
            athlete_list = cursor.fetchall()

        return render_template('session_form.html', is_coach=current_user.coach, athletes=athlete_list)

    if request.method == 'POST':
        data = request.form
        athlete_id = current_user.id if not current_user.coach else data['athlete_id']

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO Sessions (
                    Athlete_ID, Session_Date, Activity, Duration,
                    Distance, Split, Type, Weight, Comment
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                athlete_id, data['session_date'], data['activity'], data['duration'],
                data['distance'], data['split'], data['type'], data['weight'], data['comment']
            ))
            conn.commit()
        conn.close()
        return redirect(url_for('sessions.sessions'))

    return render_template('session_form.html', is_coach=current_user.coach)

@sessions_bp.route('/download_sessions_csv')
@login_required
def download_sessions_csv():

    conn = get_db_connection()
    with conn.cursor() as cursor:
        query = """
            SELECT s.Session_ID, a.Full_Name, s.Session_Date, s.Activity, s.Duration, 
                   s.Distance, s.Split, s.Type, s.Weight, s.Comment
            FROM Sessions s
            JOIN Athletes a ON s.Athlete_ID = a.Athlete_ID
            WHERE 1=1
        """
        filters = []
        params = []

        if current_user.coach:
            athlete_id = request.args.get('athlete_id')
        else:
            athlete_id = current_user.id

        activity = request.args.get('activity')
        session_type = request.args.get('type')

        if athlete_id:
            query += " AND s.Athlete_ID = %s"
            params.append(athlete_id)
        if activity:
            query += " AND s.Activity = %s"
            params.append(activity)
        if session_type:
            query += " AND s.Type = %s"
            params.append(session_type)

        cursor.execute(query, params)
        sessions = cursor.fetchall()

    conn.close()

    # Create CSV
    si = StringIO()
    cw = csv.writer(si)
    # Write header
    cw.writerow(['Session_ID', 'Full_Name', 'Session_Date', 'Activity', 'Duration',
                 'Distance', 'Split', 'Type', 'Weight', 'Comment'])
    # Write data rows
    for session in sessions:
        cw.writerow([
            session['Session_ID'],
            session['Full_Name'],
            session['Session_Date'],
            session['Activity'],
            session['Duration'],
            session['Distance'],
            session['Split'],
            session['Type'],
            session['Weight'],
            session['Comment']
        ])

    output = si.getvalue()
    si.close()

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=sessions.csv"}
    )

@sessions_bp.route('/sessions/edit/<int:session_id>', methods=['GET', 'POST'])
@login_required
def edit_session(session_id):
    if not current_user.coach:
        return "Unauthorized", 403

    conn = get_db_connection()
    with conn.cursor() as cursor:
        if request.method == 'POST':
            data = request.form
            cursor.execute("""
                UPDATE Sessions SET
                    Session_Date=%s, Activity=%s, Duration=%s, Distance=%s,
                    Split=%s, Type=%s, Weight=%s, Comment=%s, Athlete_ID=%s
                WHERE Session_ID = %s
            """, (
                data['session_date'], data['activity'], data['duration'],
                data['distance'], data['split'], data['type'],
                data['weight'], data['comment'], data['athlete_id'], session_id
            ))
            conn.commit()
            return redirect(url_for('sessions.sessions'))

        cursor.execute("SELECT * FROM Sessions WHERE Session_ID = %s", (session_id,))
        session_data = cursor.fetchone()

        cursor.execute("SELECT * FROM Athletes WHERE Coach IS NULL")
        athletes = cursor.fetchall()

    conn.close()
    return render_template('session_form.html', session=session_data, is_coach=True, athletes=athletes)

