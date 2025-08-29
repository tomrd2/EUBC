from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from db import get_db_connection
from datetime import datetime, date, timedelta, time as dt_time

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
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get athletes (non-coaches, non-coxes)
    cursor.execute("""
        SELECT Athlete_ID, Full_Name
        FROM Athletes
        WHERE (Coach != 1 OR Coach IS NULL) AND Side != 'Cox'
        ORDER BY Full_Name
    """)
    athletes = cursor.fetchall()

    selected_athlete = request.args.get('athlete_id') if current_user.coach else current_user.id

    recent_history = []
    chart_data = []
    test_chart_data = []
    formatted_table_rows = []
    selected_name = None
    elo_history = []

    if selected_athlete:
        selected_name = next(
            (a['Full_Name'] for a in athletes if str(a['Athlete_ID']) == str(selected_athlete)),
            None
        )

        # --- Athlete weekly zone minutes (Z1..Z5), fallback to Sessions.T2Minutes into Z1 when no Zones exist ---
        cursor.execute("""
            SELECT
                YEARWEEK(s.Session_Date, 3) AS year_week,
                -- Zone 1 takes all of Sessions.T2Minutes when a session has no zones
                SUM(CASE WHEN hz.has_zones = 1 THEN COALESCE(z1.z_t2, 0) ELSE COALESCE(s.T2Minutes, 0) END) AS z1,
                SUM(CASE WHEN hz.has_zones = 1 THEN COALESCE(z2.z_t2, 0) ELSE 0 END) AS z2,
                SUM(CASE WHEN hz.has_zones = 1 THEN COALESCE(z3.z_t2, 0) ELSE 0 END) AS z3,
                SUM(CASE WHEN hz.has_zones = 1 THEN COALESCE(z4.z_t2, 0) ELSE 0 END) AS z4,
                SUM(CASE WHEN hz.has_zones = 1 THEN COALESCE(z5.z_t2, 0) ELSE 0 END) AS z5
            FROM Sessions s
            LEFT JOIN (SELECT Session_ID, 1 AS has_zones FROM Zones GROUP BY Session_ID) hz
                   ON hz.Session_ID = s.Session_ID
            LEFT JOIN (SELECT Session_ID, SUM(`T2 Minutes`) AS z_t2 FROM Zones WHERE Zone = 1 GROUP BY Session_ID) z1
                   ON z1.Session_ID = s.Session_ID
            LEFT JOIN (SELECT Session_ID, SUM(`T2 Minutes`) AS z_t2 FROM Zones WHERE Zone = 2 GROUP BY Session_ID) z2
                   ON z2.Session_ID = s.Session_ID
            LEFT JOIN (SELECT Session_ID, SUM(`T2 Minutes`) AS z_t2 FROM Zones WHERE Zone = 3 GROUP BY Session_ID) z3
                   ON z3.Session_ID = s.Session_ID
            LEFT JOIN (SELECT Session_ID, SUM(`T2 Minutes`) AS z_t2 FROM Zones WHERE Zone = 4 GROUP BY Session_ID) z4
                   ON z4.Session_ID = s.Session_ID
            LEFT JOIN (SELECT Session_ID, SUM(`T2 Minutes`) AS z_t2 FROM Zones WHERE Zone = 5 GROUP BY Session_ID) z5
                   ON z5.Session_ID = s.Session_ID
            WHERE s.Athlete_ID = %s
              AND s.Session_Date >= CURDATE() - INTERVAL 12 WEEK
              AND s.Session_Date <= CURDATE()
            GROUP BY year_week
            ORDER BY year_week ASC
        """, (selected_athlete,))
        raw_athlete_zones = cursor.fetchall()

        athlete_zones_by_week = {
            int(r['year_week']): {
                'z1': int(r['z1'] or 0),
                'z2': int(r['z2'] or 0),
                'z3': int(r['z3'] or 0),
                'z4': int(r['z4'] or 0),
                'z5': int(r['z5'] or 0),
            } for r in raw_athlete_zones
        }

        # --- Squad average (your existing total-minutes logic) ---
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
        squad_by_week = { int(r['year_week']): (r['avg_minutes'] or 0) for r in raw_squad }

        # --- Build a continuous 12-week window (ISO Monday starts) ---
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())   # Monday of this ISO week
        weeks = []
        for i in range(12):
            wk_start = this_monday - timedelta(weeks=11 - i)
            iso_year, iso_week, _ = wk_start.isocalendar()
            year_week = iso_year * 100 + iso_week
            label = wk_start.strftime('%b %d')
            weeks.append((year_week, label))

        # --- Assemble chart_data with zones + squad avg ---
        chart_data = []
        for yw, label in weeks:
            z = athlete_zones_by_week.get(yw, {'z1':0,'z2':0,'z3':0,'z4':0,'z5':0})
            chart_data.append({
                'label': label,
                'avg': float(squad_by_week.get(yw, 0) or 0),
                'z1': z['z1'], 'z2': z['z2'], 'z3': z['z3'], 'z4': z['z4'], 'z5': z['z5'],
            })

        # --- Recent 30 days history (fixed param tuple) ---
        cursor.execute("""
            SELECT Date, T2Minutes, Fatigue, Fitness
            FROM History
            WHERE Athlete_ID = %s AND Date >= CURDATE() - INTERVAL 30 DAY
            ORDER BY Date
        """, (selected_athlete,))
        recent_history = cursor.fetchall()
        for row in recent_history:
            date_obj = row['Date']
            day_str = format_day_suffix(date_obj.day)
            row['FormattedDate'] = date_obj.strftime(f"%a {day_str}")

        # --- Test sessions (chart) ---
        cursor.execute("""
            SELECT Session_Date, Distance, Duration, Split, `2k_Equiv`, Comment
            FROM Sessions
            WHERE Athlete_ID = %s
              AND Type = 'Test'
              AND `2k_Equiv` IS NOT NULL
            ORDER BY Session_Date
        """, (selected_athlete,))
        test_sessions = cursor.fetchall()

        test_chart_data = []
        for row in test_sessions:
            date_obj = row['Session_Date']
            time_val = row['2k_Equiv']

            if isinstance(time_val, dt_time):
                total_seconds = (
                    time_val.hour * 3600 +
                    time_val.minute * 60 +
                    time_val.second +
                    time_val.microsecond / 1_000_000
                )
            elif isinstance(time_val, timedelta):
                total_seconds = time_val.total_seconds()
            else:
                continue

            minutes = int(total_seconds // 60)
            seconds = total_seconds % 60
            formatted = f"{minutes}:{seconds:04.1f}"

            test_chart_data.append({
                'date': date_obj.strftime('%Y-%m-%d'),
                'seconds': total_seconds,
                'label': formatted
            })

        # --- Test sessions (table) ---
        cursor.execute("""
            SELECT Session_Date, Distance, Duration, Split, `2k_Equiv`, Comment
            FROM Sessions
            WHERE Athlete_ID = %s
              AND Type = 'Test'
            ORDER BY Session_Date DESC
        """, (selected_athlete,))
        test_table_rows = cursor.fetchall()

        def format_td(td):
            if not td:
                return ''
            total_seconds = int(td.total_seconds())
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}:{seconds:02}"

        formatted_table_rows = []
        for row in test_table_rows:
            formatted_table_rows.append({
                'Date': row['Session_Date'].strftime('%Y-%m-%d'),
                'Distance': row['Distance'],
                'Duration': format_td(row['Duration']),
                'Split': format_td(row['Split']),
                '2k_Equiv': format_td(row['2k_Equiv']),
                'Comment': row['Comment'] or ''
            })

        # --- OTW ELO history ---
        cursor.execute("""
            SELECT Date AS EloDate, OTW_ELO AS EloValue
            FROM History
            WHERE Athlete_ID = %s
            ORDER BY Date
        """, (selected_athlete,))
        elo_history = cursor.fetchall()

    conn.close()

    return render_template(
        'athlete_dashboard.html',
        page_title='Athlete Dashboard',
        athletes=athletes,
        selected_athlete=selected_athlete,
        recent_history=recent_history,
        selected_name=selected_name,
        chart_data=chart_data,
        test_chart_data=test_chart_data,
        test_table_data=formatted_table_rows,
        elo_history=elo_history
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