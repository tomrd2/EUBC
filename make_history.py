#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, datetime, timedelta
from collections import defaultdict
import argparse
import logging

# ✅ CrewOptic app + tenant context
from run import app
from db import get_db_connection, tenant_context, get_param
from add_elo import add_elo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
log = logging.getLogger(__name__)

def _parse_season_start(raw: str | None) -> date | None:
    """Parse 'YYYY-MM-DD' → date, or None if invalid/missing."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def make_history(elo_history=None):
    """
    Rebuild the History table for the CURRENT TENANT (tenant bound via db.get_db_connection()).
    Processes days from Season_Start → today.
    """
    # If caller didn’t pass elo_history, compute it now for this tenant
    if elo_history is None:
        log.info("No elo_history provided; computing via add_elo()…")
        elo_history = add_elo()  # tenant-aware if run under tenant_context

    conn = get_db_connection()
    cursor = conn.cursor()

    # 0) Resolve season start
    season_start_str = (get_param("Season_Start").value
                        if get_param("Season_Start") else None)
    season_start = _parse_season_start(season_start_str)

    if not season_start:
        # Fallback: earliest session date, else today
        cursor.execute("SELECT MIN(Session_Date) AS Earliest FROM Sessions")
        row = cursor.fetchone()
        season_start = row["Earliest"] or date.today()
        log.warning("Season_Start param missing/invalid. Falling back to %s.", season_start)

    end_date = date.today()
    if season_start > end_date:
        log.info("Season_Start (%s) is after today; nothing to rebuild.", season_start)
        cursor.execute("DELETE FROM History")
        conn.commit()
        conn.close()
        return

    # 1) Start fresh
    cursor.execute("DELETE FROM History")

    # 2) Eligible athletes
    cursor.execute("""
        SELECT Athlete_ID
          FROM Athletes
         WHERE Side != 'Cox' AND (Coach IS NULL OR Coach != 1)
    """)
    athletes = [row['Athlete_ID'] for row in cursor.fetchall()]

    # 3) Build date range: Season_Start → today
    all_dates = [season_start + timedelta(days=i)
                 for i in range((end_date - season_start).days + 1)]

    # 4) T2 per athlete/day (limit to season for efficiency)
    cursor.execute("""
        SELECT Athlete_ID, Session_Date, SUM(T2Minutes) AS Total_T2
          FROM Sessions
         WHERE Session_Date >= %s
         GROUP BY Athlete_ID, Session_Date
    """, (season_start,))
    raw_sessions = cursor.fetchall()

    t2_lookup = defaultdict(int)
    for row in raw_sessions:
        t2_lookup[(row['Athlete_ID'], row['Session_Date'])] = row['Total_T2'] or 0

    # 5/6) Build History rows (with OTW_ELO)
    history_records = []
    for athlete_id in athletes:
        per_athlete_elo = elo_history.get(athlete_id, {}) if elo_history else {}
        for current_date in all_dates:
            # Fatigue: short (5-day) weighted sum (only looking back within the season window)
            fatigue = 0.0
            for offset, weight in enumerate([1.0, 0.8, 0.6, 0.4, 0.2]):
                day = current_date - timedelta(days=offset)
                if day >= season_start:
                    fatigue += weight * float(t2_lookup.get((athlete_id, day), 0.0))

            # Fitness: long (100-day) decayed sum (only within season window)
            fitness = 0.0
            for d in range(100):
                day = current_date - timedelta(days=d)
                if day >= season_start:
                    decay = (100 - d) / 100.0
                    fitness += decay * float(t2_lookup.get((athlete_id, day), 0.0))

            t2  = int(t2_lookup.get((athlete_id, current_date), 0))
            # ELO history is already daily; if missing for a day, fall back to 1000.0
            elo = round(per_athlete_elo.get(current_date, 1000.0), 2)

            history_records.append((
                athlete_id,
                current_date,
                t2,
                round(fatigue/3,    2),
                round(fitness/50.5, 2),
                elo
            ))

    if history_records:
        cursor.executemany("""
            INSERT INTO History (Athlete_ID, Date, T2Minutes, Fatigue, Fitness, OTW_ELO)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, history_records)

    conn.commit()
    conn.close()
    log.info("✅ History table refreshed for %s → %s (%d rows).",
             season_start, end_date, len(history_records))


def main():
    parser = argparse.ArgumentParser(description="Rebuild History for a tenant.")
    parser.add_argument("--tenant", required=True, help="Tenant key, e.g. 'eubc' or 'sabc'")
    args = parser.parse_args()

    # Bind tenant so add_elo() and get_db_connection() use the right schema
    with app.app_context():
        tenants = app.config.get("TENANTS", {})
        if args.tenant not in tenants:
            raise SystemExit(f"Unknown tenant '{args.tenant}'. Available: {list(tenants.keys())}")

        with tenant_context(app, args.tenant):
            elo_history = add_elo()     # compute ELO first (tenant-aware)
            make_history(elo_history)   # then write History for the season window


if __name__ == "__main__":
    main()
