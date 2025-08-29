from flask import Blueprint, render_template, request, redirect, url_for, session, Response, jsonify, abort
from flask_login import login_required, current_user
from datetime import timedelta
from db import get_db_connection
from io import StringIO
import csv

sessions_bp = Blueprint('sessions', __name__)

from flask import request
from datetime import timedelta

def get_T2_minutes(activity, duration, type):
    #Update this if Type changes to Intensity

    #duration is a string and so needs to be converted to timedelta

    if not duration:
        print("Not duration!")
        return 0
    
    if isinstance(duraction,str):
        parts = duration.split(':')
        if len(parts) == 2:
            hours, minutes = map(int, parts)        
        elif len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
        else:    
            return 0
    
    else:
        return 0

    t2_min = hours * 60 + minutes

    if activity == "Water":
        t2_min = t2_min * 1
    elif activity == "Erg":
        t2_min = t2_min * 1.35
    elif activity == "Static Bike":
        t2_min = t2_min * 0.95
    elif activity == "Road Bike":
        t2_min = t2_min * 0.8
    elif activity == "Run":
        t2_min = t2_min * 1.4
    elif activity == "Swim":
        t2_min = t2_min * 1.2
    elif activity == "Brisk Walk":
        t2_min = t2_min * 0.5
    else:
        t2_min = t2_min * 0.6

    return t2_min


def format_timedelta(td):
    if not td:
        return ''
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"

@sessions_bp.route('/sessions')
@login_required
def sessions():
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    athlete_id = request.args.get('athlete_id')
    activity = request.args.get('activity')
    session_type = request.args.get('type')

    filters = []
    params = []

    if current_user.coach:
        if athlete_id:
            filters.append("s.Athlete_ID = %s")
            params.append(athlete_id)
    else:
        filters.append("s.Athlete_ID = %s")
        params.append(current_user.id)

    if activity:
        filters.append("s.Activity = %s")
        params.append(activity)

    if session_type:
        filters.append("s.Type = %s")
        params.append(session_type)

    if from_date:
        filters.append("s.Session_Date >= %s")
        params.append(from_date)

    if to_date:
        filters.append("s.Session_Date <= %s")
        params.append(to_date)

    where_clause = " AND ".join(filters)
    if where_clause:
        where_clause = "WHERE " + where_clause

    query = f"""
        SELECT s.*, a.Full_Name
        FROM Sessions s
        JOIN Athletes a ON s.Athlete_ID = a.Athlete_ID
        {where_clause}
        ORDER BY s.Session_Date DESC, a.Full_Name ASC
        LIMIT 500
    """

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        sessions = cursor.fetchall()

        if current_user.coach:
            cursor.execute("SELECT Athlete_ID, Full_Name, M_W FROM Athletes ORDER BY Full_Name")
            athletes = cursor.fetchall()
        else:
            athletes = []

    conn.close()

    return render_template('sessions.html',
        sessions=sessions,
        athletes=athletes,
        selected_athlete=athlete_id,
        selected_activity=activity,
        selected_type=session_type,
        from_date=from_date,
        to_date=to_date
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

        T2Minutes = get_T2_minutes(data['activity'], data['duration'],data['type'])

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO Sessions (
                    Athlete_ID, Session_Date, Activity, Duration,
                    Distance, Split, Type, Weight, Comment, T2Minutes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                athlete_id, data['session_date'], data['activity'], data['duration'],
                data['distance'], data['split'], data['type'], data['weight'], data['comment'], T2Minutes
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

            T2Minutes = get_T2_minutes(data['activity'], data['duration'],data['type'])

            print("T2 Minutes: ", T2Minutes)

            cursor.execute("""
                UPDATE Sessions SET
                    Session_Date=%s, Activity=%s, Duration=%s, Distance=%s,
                    Split=%s, Type=%s, Weight=%s, Comment=%s, Athlete_ID=%s,
                    T2Minutes=%s
                WHERE Session_ID = %s
            """, (
                data['session_date'], data['activity'], data['duration'],
                data['distance'], data['split'], data['type'],
                data['weight'], data['comment'], data['athlete_id'], T2Minutes, session_id
            ))
            conn.commit()
            return redirect(url_for('sessions.sessions'))

        cursor.execute("SELECT * FROM Sessions WHERE Session_ID = %s", (session_id,))
        session_data = cursor.fetchone()

        session_data['Duration'] = format_timedelta(session_data['Duration'])
        session_data['Split'] = format_timedelta(session_data['Split'])
        print("SESSION DATA:", session_data)

        cursor.execute("SELECT * FROM Athletes WHERE (Coach IS NULL OR Coach = 0)")
        athletes = cursor.fetchall()

    conn.close()
    return render_template('session_form.html', session=session_data, is_coach=True, athletes=athletes)

@sessions_bp.route('/assign_session', methods=['POST'])
@login_required
def assign_session():
    if not current_user.coach:
        return redirect(url_for('sessions.sessions'))

    session_id = request.form.get('session_id')
    athlete_ids = request.form.getlist('athlete_ids')

    if not session_id or not athlete_ids:
        return redirect(url_for('sessions.sessions'))

    if not athlete_ids:
        return redirect(url_for('sessions.sessions'))

    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Get original session to copy
        cursor.execute("SELECT * FROM Sessions WHERE Session_ID = %s", (session_id,))
        original = cursor.fetchone()

        for athlete_id in athlete_ids:
            if int(athlete_id) != original['Athlete_ID']:
                cursor.execute("""
                    INSERT INTO Sessions (Athlete_ID, Session_Date, Activity, Duration, Distance, Split, Type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    athlete_id,
                    original['Session_Date'],
                    original['Activity'],
                    original['Duration'],
                    original['Distance'],
                    original['Split'],
                    original['Type']
                ))

                conn.commit()
    conn.close()

    return redirect(url_for('sessions.sessions'))

from flask import jsonify, abort, current_app
from datetime import timedelta

@sessions_bp.route('/sessions/<int:session_id>/zones', methods=['GET'], endpoint='session_zones')
@login_required
def session_zones(session_id):
    current_app.logger.info(f"/sessions/{session_id}/zones hit")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Verify the session exists and you’re allowed to see it
            cur.execute("SELECT Athlete_ID, Session_Date, Activity FROM Sessions WHERE Session_ID=%s", (session_id,))
            sess = cur.fetchone()
            if not sess:
                current_app.logger.warning(f"session_zones: session {session_id} not found")
                abort(404)
            if not current_user.coach and sess['Athlete_ID'] != current_user.id:
                current_app.logger.warning(f"session_zones: user {current_user.id} forbidden for session {session_id}")
                abort(403)

            # Pull zones; alias the spaced column name
            cur.execute("""
                SELECT
                  Zone,
                  Time_In_Zone,
                  Activity_Factor,
                  Zone_Factor,
                  `T2 Minutes` AS T2_Minutes
                FROM Zones
                WHERE Session_ID=%s
                ORDER BY Zone
            """, (session_id,))
            rows = cur.fetchall()

        def to_seconds(val):
            if isinstance(val, timedelta): return int(val.total_seconds())
            if isinstance(val, str):
                h, m, *rest = val.split(':')
                s = int(rest[0]) if rest else 0
                return int(h)*3600 + int(m)*60 + s
            return 0

        out = []
        total_sec = 0
        total_t2 = 0
        for r in rows or []:
            secs = to_seconds(r['Time_In_Zone'])
            total_sec += secs
            t2 = int(r.get('T2_Minutes') or 0)
            total_t2 += t2
            out.append({
                "zone": r['Zone'],
                "time_seconds": secs,
                "time_hm": f"{secs//3600:02d}:{(secs%3600)//60:02d}",
                "activity_factor": r.get('Activity_Factor'),
                "zone_factor": r.get('Zone_Factor'),
                "t2_minutes": t2,
            })

        return jsonify({
            "session_id": session_id,
            "session": {
                "athlete_id": sess["Athlete_ID"],
                "session_date": str(sess["Session_Date"]),
                "activity": sess["Activity"],
            },
            "rows": out,
            "totals": {
                "time_seconds": total_sec,
                "time_hm": f"{total_sec//3600:02d}:{(total_sec%3600)//60:02d}",
                "t2_minutes": total_t2,
            }
        })
    finally:
        conn.close()

@sessions_bp.route('/__routes__')
def __routes__():
    from flask import current_app
    return "<pre>" + "\n".join(sorted(str(r) for r in current_app.url_map.iter_rules())) + "</pre>"