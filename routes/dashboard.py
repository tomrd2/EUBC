from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from db import get_db_connection
from datetime import datetime, date, timedelta, time
from make_history import make_history

dashboard_bp = Blueprint('dashboard', __name__)

def yearweek_to_date(yearweek):
    year = int(str(yearweek)[:4])
    week = int(str(yearweek)[4:])
    return datetime.strptime(f'{year}-W{week}-1', "%Y-W%W-%w")

def format_day_suffix(n):
    return f"{n}{'th' if 11<=n<=13 else {1:'st',2:'nd',3:'rd'}.get(n%10, 'th')}"

@dashboard_bp.route('/athlete_dash')
@login_required
def athlete_dashboard():
    make_history()
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get athletes
    cursor.execute("SELECT Athlete_ID, Full_Name FROM Athletes WHERE (Coach != 1 OR Coach IS NULL) AND Side != 'Cox' ORDER BY Full_Name")
    athletes = cursor.fetchall()

    if current_user.coach:
        selected_athlete = request.args.get('athlete_id')
    else:
        selected_athlete =current_user.id
    athlete_data = []
    squad_data = []
    recent_history = []
    chart_data = []
    test_chart_data = []
    formatted_table_rows = []
    selected_name = None

    if selected_athlete:
        selected_name = next((a['Full_Name'] for a in athletes if str(a['Athlete_ID']) == str(selected_athlete)), None)
        # Athlete-specific data
        cursor.execute("""
            SELECT YEARWEEK(Session_Date, 3) AS year_week,
                   SUM(T2Minutes) AS total_minutes
            FROM Sessions
            WHERE Athlete_ID = %s
            AND Session_Date >= CURDATE() - INTERVAL 12 WEEK
            AND Session_Date <= CURDATE()
            GROUP BY year_week
            ORDER BY year_week ASC
        """, (selected_athlete,))
        raw_athlete = cursor.fetchall()

        athlete_data = {
            int(row['year_week']): row['total_minutes']
            for row in raw_athlete
        }

        # Squad average (excluding coxes and coaches)
        cursor.execute("""
            SELECT s.year_week, AVG(s.total) AS avg_minutes
            FROM (
                SELECT YEARWEEK(sess.Session_Date, 3) AS year_week,
                       SUM(sess.T2Minutes) AS total
                FROM Sessions sess
                JOIN Athletes a ON sess.Athlete_ID = a.Athlete_ID
                WHERE sess.Session_Date >= CURDATE() - INTERVAL 12 WEEK
                  AND sess.Session_Date <= CURDATE()
                  AND a.Side != 'Cox' AND (a.Coach IS NULL OR a.Coach != 1)
                GROUP BY sess.Athlete_ID, year_week
            ) s
            GROUP BY s.year_week
            ORDER BY s.year_week ASC
        """)
        raw_squad = cursor.fetchall()

        squad_data = {
            int(row['year_week']): {
                'label': (yearweek_to_date(row['year_week']) - timedelta(days=7)).strftime('%b %d'),
                'avg': row['avg_minutes']
            }
            for row in raw_squad  # rows with year_week and avg
        }

        chart_data = []

        for yw, data in squad_data.items():
            chart_data.append({
                'label': data['label'],
                'avg': data['avg'],
                'total': athlete_data.get(yw, 0)  # fallback to 0 if athlete missing
            })

        cursor.execute("""
            SELECT Date, T2Minutes, Fatigue, Fitness
            FROM History
            WHERE Athlete_ID = %s AND Date >= CURDATE() - INTERVAL 30 DAY
            ORDER BY Date
        """, (selected_athlete))
        recent_history = cursor.fetchall()

        for row in recent_history:
            date_obj = row['Date']
            day_str = format_day_suffix(date_obj.day)
            row['FormattedDate'] = date_obj.strftime(f"%a {day_str}")

        cursor.execute("""
            SELECT Session_Date, Distance, Duration, Split, 2k_Equiv, Comment
            FROM Sessions
            WHERE Athlete_ID = %s
            AND Type = 'Test'
            AND 2k_Equiv IS NOT NULL
            ORDER BY Session_Date
        """, (selected_athlete,))
        test_sessions = cursor.fetchall()

        test_chart_data = []

        for row in test_sessions:
            date_obj = row['Session_Date']
            time_val = row['2k_Equiv']

            if isinstance(time_val, time):
                total_seconds = time_val.hour * 3600 + time_val.minute * 60 + time_val.second + time_val.microsecond / 1_000_000
            elif isinstance(time_val, timedelta):
                total_seconds = time_val.total_seconds()
            else:
                continue

            minutes = int(total_seconds // 60)
            seconds = total_seconds % 60
            formatted = f"{minutes}:{seconds:04.1f}"  # e.g., 6:43.5

            test_chart_data.append({
                'date': date_obj.strftime('%Y-%m-%d'),
                'seconds': total_seconds,
                'label': formatted
            })
            cursor.execute("""
                SELECT Session_Date, Distance, Duration, Split, `2k_Equiv`, Comment
                FROM Sessions
                WHERE Athlete_ID = %s
                AND Type = 'Test'
                ORDER BY Session_Date DESC
            """, (selected_athlete,))
            test_table_rows = cursor.fetchall()

            formatted_table_rows = []

            for row in test_table_rows:
                duration = row['Duration']
                split = row['Split']
                equiv = row['2k_Equiv']

                def format_td(td):
                    if not td:
                        return ''
                    total_seconds = int(td.total_seconds())
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    return f"{minutes}:{seconds:02}"

                formatted_row = {
                    'Date': row['Session_Date'].strftime('%Y-%m-%d'),
                    'Distance': row['Distance'],
                    'Duration': format_td(duration),
                    'Split': format_td(split),
                    '2k_Equiv': format_td(equiv),
                    'Comment': row['Comment'] or ''
                }
                formatted_table_rows.append(formatted_row)

    conn.close()

    return render_template(
        'athlete_dashboard.html',
        athletes=athletes,
        selected_athlete=selected_athlete,
        recent_history=recent_history,
        selected_name=selected_name,
        chart_data = chart_data,
        test_chart_data=test_chart_data,
        test_table_data=formatted_table_rows
    )