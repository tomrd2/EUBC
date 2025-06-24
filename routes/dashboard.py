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
    #make_history()
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
    elo_history = []

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
        # get full OTW‐ELO history for the selected athlete
        cursor.execute(
            """
            SELECT Date      AS EloDate,
                OTW_ELO   AS EloValue
            FROM   History
            WHERE  Athlete_ID = %s
            ORDER  BY Date
            """,
            (selected_athlete,)          # or current_user.athlete_id if not coach-driven
        )
        elo_history = cursor.fetchall()     # list of rows with EloDate / EloValue

    conn.close()

    return render_template(
        'athlete_dashboard.html',
        page_title='Athlete Dashboard',
        athletes=athletes,
        selected_athlete=selected_athlete,
        recent_history=recent_history,
        selected_name=selected_name,
        chart_data = chart_data,
        test_chart_data=test_chart_data,
        test_table_data=formatted_table_rows,
        elo_history = elo_history
    )

@dashboard_bp.route('/squad_dash')
@login_required
def squad_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(Date) as latest FROM History")
    row = cursor.fetchone()
    today = row["latest"]
    start_date = today - timedelta(weeks=12)

    # Get gender filter from query string
    selected_gender = request.args.get('gender', 'All')

    # Dynamic SQL WHERE clause
    gender_clause = ""
    gender_params = []

    if selected_gender in ['M', 'W']:
        gender_clause = "AND a.M_W = %s"
        gender_params = [selected_gender]

    # 1. Weekly total T2Minutes
    cursor.execute(f"""
        SELECT
            STR_TO_DATE(CONCAT(YEARWEEK(h.Date, 3), ' Monday'), '%%X%%V %%W') AS week_start,
            SUM(h.T2Minutes) AS total_minutes
        FROM History h
        JOIN Athletes a ON h.Athlete_ID = a.Athlete_ID
        WHERE h.Date >= %s {gender_clause}
        GROUP BY YEARWEEK(h.Date, 3)
        ORDER BY week_start
    """, [start_date] + gender_params)
    weekly_t2 = cursor.fetchall()

    # 2. Avg fatigue/fitness for each Sunday
    cursor.execute(f"""
        SELECT
            h.Date AS sunday,
            AVG(h.Fatigue) AS avg_fatigue,
            AVG(h.Fitness) AS avg_fitness
        FROM History h
        JOIN Athletes a ON h.Athlete_ID = a.Athlete_ID
        WHERE WEEKDAY(h.Date) = 6 AND h.Date >= %s {gender_clause}
        GROUP BY h.Date
        ORDER BY h.Date
    """, [start_date] + gender_params)
    fatigue_fitness = cursor.fetchall()

    # Build combined chart data
    squad_load = []
    for week in weekly_t2:
        sunday = week["week_start"] + timedelta(days=6)
        ff_match = next((ff for ff in fatigue_fitness if ff["sunday"] == sunday), None)
        squad_load.append({
            "week": week["week_start"].strftime("%Y-%m-%d"),
            "t2": week["total_minutes"] or 0,
            "fatigue": ff_match["avg_fatigue"] if ff_match else None,
            "fitness": ff_match["avg_fitness"] if ff_match else None
        })

    thirty_days_ago = today - timedelta(days=30)

    cursor.execute(f"""
        SELECT a.Full_Name, h1.Athlete_ID, h1.OTW_ELO AS today_elo, h2.OTW_ELO AS past_elo
        FROM Athletes a
        LEFT JOIN History h1 ON h1.Athlete_ID = a.Athlete_ID AND h1.Date = %s
        LEFT JOIN History h2 ON h2.Athlete_ID = a.Athlete_ID AND h2.Date = %s
        WHERE a.Side != 'Cox' AND (a.Coach IS NULL OR a.Coach != 1)
        { "AND a.M_W = %s" if selected_gender in ['M', 'W'] else "" }
        ORDER BY h1.OTW_ELO DESC
    """, [today, thirty_days_ago] + ([selected_gender] if selected_gender in ['M', 'W'] else []))

    elo_table_data = []
    for row in cursor.fetchall():
        if row["today_elo"] is not None:
            movement = None
            if row["past_elo"] is not None:
                movement = round(row["today_elo"] - row["past_elo"])
                elo_table_data.append({
                    "id": row["Athlete_ID"],
                    "name": row["Full_Name"],
                    "elo": round(row["today_elo"]),
                    "movement": movement
                })

    # 3. Weekly T2Minutes split by Activity
    cursor.execute(f"""
        SELECT
            STR_TO_DATE(CONCAT(YEARWEEK(s.Session_Date, 3), ' Monday'), '%%X%%V %%W') AS week_start,
            s.Activity,
            SUM(s.T2Minutes) AS total_minutes
        FROM Sessions s
        JOIN Athletes a ON s.Athlete_ID = a.Athlete_ID
        WHERE s.Session_Date >= %s {gender_clause}
        GROUP BY YEARWEEK(s.Session_Date, 3), s.Activity
        ORDER BY week_start
    """, [start_date] + gender_params)

    raw_split_minutes = cursor.fetchall()

    # Organize into stacked format
    activity_summary = {}
    for row in raw_split_minutes:
        week = row["week_start"].strftime("%Y-%m-%d")
        activity = row["Activity"] or "Other"
        if week not in activity_summary:
            activity_summary[week] = {"Water": 0, "Erg": 0, "Other": 0}
        if activity in activity_summary[week]:
            activity_summary[week][activity] += row["total_minutes"]
        else:
            activity_summary[week]["Other"] += row["total_minutes"]

    activity_chart_data = []
    for week, values in sorted(activity_summary.items()):
        activity_chart_data.append({
            "week": week,
            "Water": values["Water"],
            "Erg": values["Erg"],
            "Other": values["Other"]
        })

    conn.close()
    return render_template(
        "squad_dashboard.html",
        squad_load=squad_load,
        elo_table_data = elo_table_data,
        activity_chart_data=activity_chart_data,
        selected_gender=selected_gender
    )