#!/usr/bin/env python3
"""
process_fit_sessions.py  (merged insert/upsert)
==============================================
• Downloads all *.fit files from S3 (eubctrackingdata/fitfiles/<Athlete_ID>/).
• Parses them with fitparse, derives Activity, Distance, Duration and HR‑based
  T2Minutes.
• Inserts into **Sessions** while handling duplicates exactly as requested:

  ─ If no row for (Athlete, Date, Activity) → insert.
  ─ If an existing row for that triple has Source IS NULL → delete it, insert new.
  ─ If rows exist but none match the filename → insert alongside (not duplicate).
  ─ If a row already has the same Source → skip.

Requirements: boto3, fitparse, db.get_db_connection()
"""

from __future__ import annotations
import argparse
import io
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Iterator, Tuple

import boto3
from fitparse import FitFile
from db import get_db_connection,get_param

# ── configuration ────────────────────────────────────────────────────────
S3_BUCKET = "eubctrackingdata"
S3_PREFIX = "fitfiles"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

logger = logging.getLogger(__name__)

s3 = boto3.client("s3")  # ~/.aws/credentials

# ── helpers ──────────────────────────────────────────────────────────────

def norm(name: str | None) -> str | None:
    """
    Return lowercase, trimmed base-name of a path (or None).
    Examples:
        "FITFILES/55/A.BC.FIT" → "a.bc.fit"
        "/foo/bar/abc.fit "    → "abc.fit"
    """
    if name is None:
        return None
    return name.rsplit("/", 1)[-1].strip().lower()

def row_val(row, key_or_idx):
    if isinstance(row, dict):
        # Assume key_or_idx is a column name
        return row.get(key_or_idx)
    else:
        # Assume row is a tuple, so index is okay
        return row[key_or_idx]

def iter_athletes_with_links(cur) -> Iterator[Tuple[int, str]]:
    """
    Yield (Athlete_ID, DropBox) regardless of cursor type.
    """
    cur.execute(
        "SELECT Athlete_ID, DropBox "
        "FROM Athletes "
        "WHERE DropBox IS NOT NULL"
    )

    for row in cur.fetchall():
        if isinstance(row, dict):        # DictCursor
            aid  = row["Athlete_ID"]
            link = row["DropBox"]
        else:                            # regular tuple
            aid, link = row
        yield int(aid), link



def iter_fit_keys_for_athlete(aid: int) -> Iterator[str]:
    pref = f"{S3_PREFIX}/{aid}/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=pref):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".fit", ".tcx")):
                yield key

# ── HR helpers ───────────────────────────────────────────────────────────

def get_athlete_hr(cur, aid: int) -> tuple[int | None, int | None]:
    cur.execute("SELECT Rest_HR, Max_HR FROM Athletes WHERE Athlete_ID=%s", (aid,))
    r = cur.fetchone()
    if not r:
        logger.warning("No HR row found for Athlete_ID=%s", aid)
        return None, None
    logger.debug("Fetched HR for %s: %s", aid, r)
    # Access as tuple or dict
    try:
        return r["Rest_HR"], r["Max_HR"]
    except (TypeError, KeyError):
        # Fall back to positional access
        return r[0], r[1]

def sport_factor(activity: str) -> float:
    # Normalize spacing & case to match Params table keys
    activity_key = activity.strip().title()

    try:
        return float(get_param(activity_key).value)
    except Exception:
        # Fallback to "Other" if no match
        return float(get_param("Other").value)

def calculate_t2(
    hr_data: list[tuple[datetime, int]],
    rest_hr: int | None,
    max_hr: int | None,
    activity: str
) -> tuple[int, list[float], float, list[float]]:
    """
    Compute T2Minutes and also return:
      - zones_sec: list of 6 elements with seconds in each zone
      - activity_factor
      - weights list
    """
    if not (rest_hr and max_hr and max_hr > rest_hr):
        return 0, [0]*6, sport_factor(activity), [
            float(get_param("HR_Z0_W").value),
            float(get_param("HR_Z1_W").value),
            float(get_param("HR_Z2_W").value),
            float(get_param("HR_Z3_W").value),
            float(get_param("HR_Z4_W").value),
            float(get_param("HR_Z5_W").value),
        ]

    zones = [0.0] * 6
    last_ts = None

    # thresholds
    hr_z0 = float(get_param("HR_Z0").value)
    hr_z1 = float(get_param("HR_Z1").value)
    hr_z2 = float(get_param("HR_Z2").value)
    hr_z3 = float(get_param("HR_Z3").value)
    hr_z4 = float(get_param("HR_Z4").value)
    hr_z5 = float(get_param("HR_Z5").value)

    for ts, hr in hr_data:
        if last_ts:
            dsec = (ts - last_ts).total_seconds()
            hr_pct = (hr - rest_hr) / (max_hr - rest_hr)

            if hr_pct >= hr_z0:
                idx = (
                    0 if hr_pct < hr_z1 else
                    1 if hr_pct < hr_z2 else
                    2 if hr_pct < hr_z3 else
                    3 if hr_pct < hr_z4 else
                    4 if hr_pct < hr_z5 else 5
                )
                zones[idx] += dsec
        last_ts = ts

    weights = [
        float(get_param("HR_Z0_W").value),
        float(get_param("HR_Z1_W").value),
        float(get_param("HR_Z2_W").value),
        float(get_param("HR_Z3_W").value),
        float(get_param("HR_Z4_W").value),
        float(get_param("HR_Z5_W").value),
    ]
    activity_factor = sport_factor(activity)

    t2_raw = sum(z * w for z, w in zip(zones, weights)) / 60
    t2 = int(round(t2_raw * activity_factor))

    logger.debug("Zones(sec): %s", zones)
    logger.debug("T2 raw: %.2f × act=%.2f → T2=%s", t2_raw, activity_factor, t2)

    return t2, zones, activity_factor, weights

def classify_activity(sport: str | None, sub: str | None) -> str:
    s  = (sport or "").strip().lower()
    ss = (sub or "").strip().lower()

    # Sub-sport overrides (handles fitness_equipment + indoor_rowing, etc.)
    sub_map = {
        "indoor_rowing":  "Erg",
        "indoor-rowing":  "Erg",
        "rower":          "Erg",
        "erg":            "Erg",
        "ergometer":      "Erg",

        "indoor_cycling": "Static Bike",
        "indoor-cycling": "Static Bike",
        "spin":           "Static Bike",
        "spinning":       "Static Bike",
        "stationary_cycling": "Static Bike",
        "stationary-bike":    "Static Bike",
    }
    if ss in sub_map:
        return sub_map[ss]

    # Fall back to sport-only mapping
    sport_map = {
        "rowing":   "Water",
        "cycling":  "Bike",
        "walking":  "Brisk Walk",
        "running":  "Run",
        "swimming": "Swim",
    }
    return sport_map.get(s, "Other")


# ── FIT parsing ───────────────────────────────────────────────────────────

def parse_fit_bytes(buf: bytes, rest_hr: int | None, max_hr: int | None):
    fit = FitFile(io.BytesIO(buf)); fit.parse()
    sport = sub = "unknown"; dur_s = dist_m = 0; dt: datetime | None = None

    for msg in fit.get_messages("session"):
        d = {f.name: f.value for f in msg}
        sport = str(d.get("sport", sport)).lower()
        sub   = str(d.get("sub_sport", "")).lower() or None
        dur_s = int(d.get("total_elapsed_time") or d.get("total_timer_time") or 0)
        dist_m= int(d.get("total_distance") or 0)
        dt    = d.get("start_time", dt); break

    if not dt:
        for msg in fit.get_messages("activity"):
            dt = msg.get_value("timestamp"); break
    dt = dt or datetime.now(timezone.utc)

    mapping = None  # no longer used
    activity = classify_activity(sport, sub)
    comment  = f"Sport: {sport} | Sub: {sub or 'n/a'}"

    # 🆕 Standardised HR data
    hr_data = []
    for rec in fit.get_messages("record"):
        hr = rec.get_value("heart_rate")
        ts = rec.get_value("timestamp")
        if hr is not None and ts is not None:
            hr_data.append((ts, hr))

    t2, zones, act_factor, weights = calculate_t2(hr_data, rest_hr, max_hr, activity)
    return dt, activity, dur_s, dist_m, comment, t2, zones, act_factor, weights


def parse_tcx_bytes(buf: bytes, rest_hr: int | None, max_hr: int | None):
    ns = {'tcx': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}
    root = ET.fromstring(buf)
    activity_node = root.find(".//tcx:Activity", ns)
    if activity_node is None:
        raise ValueError("No Activity found in TCX")

    sport = activity_node.attrib.get("Sport", "Other")
    activity = sport.title()
    comment = f"Sport: {sport}"

    id_node = activity_node.find("tcx:Id", ns)
    dt = datetime.fromisoformat(id_node.text.replace("Z", "+00:00")) if id_node is not None else datetime.now(timezone.utc)

    dist_m = dur_s = 0
    hr_data = []

    for tp in root.findall(".//tcx:Trackpoint", ns):
        ts_node = tp.find("tcx:Time", ns)
        hr_node = tp.find("tcx:HeartRateBpm/tcx:Value", ns)
        dist_node = tp.find("tcx:DistanceMeters", ns)

        if ts_node is None or hr_node is None:
            continue

        ts = datetime.fromisoformat(ts_node.text.replace("Z", "+00:00"))
        hr = int(hr_node.text)
        hr_data.append((ts, hr))

        if dist_node is not None and dist_node.text:
            dist_m = int(float(dist_node.text))  # will keep getting overwritten

    if hr_data:
        dur_s = int((hr_data[-1][0] - dt).total_seconds())

    t2, zones, act_factor, weights = calculate_t2(hr_data, rest, max_hr, activity)
    return dt, activity, dur_s, dist_m, comment, t2, zones, act_factor, weights

def _to_time(seconds: int):
    return (datetime.min + timedelta(seconds=int(seconds))).time()

def insert_zones(cur, session_id: int, zones_sec: list[float],
                 activity_factor: float, weights: list[float]):
    """
    Insert/Upsert per-zone details for this session.
    `zones_sec` is seconds in zone (len == 6).
    """
    for zone_idx, sec in enumerate(zones_sec):
        t2_minutes = int(round((sec * weights[zone_idx]) / 60.0 * activity_factor))
        cur.execute(
            "INSERT INTO Zones (Session_ID, Zone, Time_In_Zone, Activity_Factor, Zone_Factor, `T2 Minutes`)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON DUPLICATE KEY UPDATE "
            "   Time_In_Zone=VALUES(Time_In_Zone),"
            "   Activity_Factor=VALUES(Activity_Factor),"
            "   Zone_Factor=VALUES(Zone_Factor),"
            "   `T2 Minutes`=VALUES(`T2 Minutes`)",
            (
                session_id,
                zone_idx,
                _to_time(int(sec)),
                float(activity_factor),
                float(weights[zone_idx]),
                t2_minutes,
            )
        )



# ── UPSERT (merged) ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
# helper: insert one row
def insert_session(cur, aid, dt, activity, dur_s, dist_m, comment, t2, source) -> int:
    cur.execute(
        """INSERT INTO Sessions (
               Athlete_ID, Session_Date, Activity, Duration,
               Distance, Comment, T2Minutes, Source)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            aid,
            dt.date(),
            activity,
            (datetime.min + timedelta(seconds=dur_s)).time(),
            dist_m,
            comment,
            t2,
            source,
        ),
    )
    session_id = cur.lastrowid  # <-- capture the new PK
    logger.info("    + session saved (src=%s, id=%s)", source, session_id)
    return session_id
# ---------------------------------------------------------------------------


def upsert_session(cur, aid: int, dt: datetime, activity: str,
                   dur_s: int, dist_m: int, comment: str,
                   t2: int, zones: list[float], act_factor: float, weights: list[float],
                   source_raw: str):
    source = source_raw.rsplit("/", 1)[-1].strip().lower()

    cur.execute(
        """SELECT Session_ID, Source
             FROM Sessions
            WHERE Athlete_ID = %s
              AND Session_Date = %s
              AND Activity = %s""",
        (aid, dt.date(), activity),
    )
    rows = cur.fetchall()

    def col(row, key, idx):
        return row[key] if isinstance(row, dict) else row[idx]

    # 1) nothing there yet → insert
    if not rows:
        sid = insert_session(cur, aid, dt, activity, dur_s, dist_m, comment, t2, source)
        insert_zones(cur, sid, zones, act_factor, weights)
        return

    # 2) replace NULL-source row
    for r in rows:
        if col(r, "Source", 1) is None:
            cur.execute("DELETE FROM Sessions WHERE Session_ID = %s",
                        (col(r, "Session_ID", 0),))
            sid = insert_session(cur, aid, dt, activity, dur_s, dist_m, comment, t2, source)
            insert_zones(cur, sid, zones, act_factor, weights)
            return

    # 4) duplicate filename? skip
    if any(((col(r, "Source", 1) or "").rsplit("/", 1)[-1].strip().lower() == source) for r in rows):
        logger.debug("    · duplicate (same source) – skipped")
        return

    # 3) same A/D/A but new filename → insert alongside
    sid = insert_session(cur, aid, dt, activity, dur_s, dist_m, comment, t2, source)
    insert_zones(cur, sid, zones, act_factor, weights)

# ---------------------------------------------------------------------------

def process_single_file(cur, aid, key):
    try:
        buf = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    except Exception as e:
        logger.error("    ! S3 download failed: %s", e)
        return

    rest, max_hr = get_athlete_hr(cur, aid)
    fname = key.rsplit("/", 1)[-1].lower()

    try:
        if fname.endswith(".fit"):
            dt, act, dur_s, dist_m, comment, t2, zones, act_factor, weights = parse_fit_bytes(buf, rest, max_hr)
        elif fname.endswith(".tcx"):
            dt, act, dur_s, dist_m, comment, t2, zones, act_factor, weights = parse_tcx_bytes(buf, rest, max_hr)
        else:
            logger.warning("    ! Unsupported file type: %s", fname)
            return
    except Exception as e:
        logger.error("    ! File parse failed (%s): %s", fname, e)
        return

    upsert_session(cur, aid, dt, act, dur_s, dist_m, comment, t2, zones, act_factor, weights, fname)


# ── main loop ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--aid', type=int, help="Athlete ID")
    parser.add_argument('--file', help="Specific S3 key of FIT file to process")
    args = parser.parse_args()

    conn = get_db_connection(); cur = conn.cursor()
    logger.info("Importing FIT sessions from S3 → MySQL …")

    if args.aid and args.file:
        process_single_file(cur, args.aid, args.file)
    else:
        for aid, _ in iter_athletes_with_links(cur):
            logger.info("Athlete %s", aid)
            for key in iter_fit_keys_for_athlete(aid):
                process_single_file(cur, aid, key)

    conn.commit(); cur.close(); conn.close()
    logger.info("✓ All done")

if __name__ == "__main__":
    main()
