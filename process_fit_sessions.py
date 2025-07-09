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

import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Iterator, Tuple

import boto3
from fitparse import FitFile
from db import get_db_connection

# ── configuration ────────────────────────────────────────────────────────
S3_BUCKET = "eubctrackingdata"
S3_PREFIX = "fitfiles"

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)-7s %(message)s")
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
            if key.lower().endswith(".fit"):
                yield key

# ── HR helpers ───────────────────────────────────────────────────────────

def get_athlete_hr(cur, aid: int) -> tuple[int | None, int | None]:
    cur.execute("SELECT Rest_HR, Max_HR FROM Athletes WHERE Athlete_ID=%s", (aid,))
    r = cur.fetchone()
    if not r:
        return None, None
    return row_val(r, 0), row_val(r, 1)


def sport_factor(activity: str) -> float:
    return {
        "Water": 1.00, "Erg": 1.35, "Static Bike": 0.95,
        "Bike": 0.80, "Run": 1.40, "Swim": 1.20, "Brisk Walk": 0.50,
    }.get(activity, 0.60)

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

    mapping = {("cycling","indoor_cycling"):"Static Bike",("cycling",None):"Bike",
               ("rowing","indoor_rowing"):"Erg",("rowing",None):"Water",
               ("walking",None):"Brisk Walk",("running",None):"Run",
               ("swimming",None):"Swim"}
    activity = mapping.get((sport, sub)) or mapping.get((sport, None)) or "Other"
    comment  = f"Sport: {sport} | Sub: {sub or 'n/a'}"

    t2 = 0
    if rest_hr and max_hr and max_hr > rest_hr:
        zones = [0]*6; last = None
        for rec in fit.get_messages("record"):
            hr = rec.get_value("heart_rate"); ts = rec.get_value("timestamp")
            if hr is None or ts is None: continue
            if last is None: last = ts; continue
            dsec = (ts-last).total_seconds(); last = ts
            hr_pct = (hr-rest_hr)/(max_hr-rest_hr)
            if hr_pct < .60: continue
            idx = (0 if hr_pct<.75 else 1 if hr_pct<.83 else 2 if hr_pct<.88 else
                   3 if hr_pct<.93 else 4 if hr_pct<.99 else 5)
            zones[idx] += dsec
        weights=[0.9,1.0,1.35,2.1,5.0,9.0]
        t2_raw=sum(z*w for z,w in zip(zones,weights))/60
        t2=int(round(t2_raw*sport_factor(activity)))

    return dt, activity, dur_s, dist_m, comment, t2

# ── UPSERT (merged) ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
# helper: insert one row
def insert_session(cur, aid, dt, activity,
                   dur_s, dist_m, comment, t2, source):
    """
    Write a single session row.  `source` is already normalised before call.
    """
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
            source,               # store the normalised filename
        ),
    )
    logger.info("    + session saved (src=%s)", source)
# ---------------------------------------------------------------------------


def upsert_session(cur, aid: int, dt: datetime, activity: str,
                   dur_s: int, dist_m: int, comment: str, t2: int, source_raw: str):
    """
    Handle duplicates exactly per spec:

    1. No existing row → insert.
    2. Row with Source IS NULL → delete & insert.
    3. Rows exist but none with the SAME filename → insert alongside.
    4. Row with same filename → skip.
    """
    # normalise the incoming filename (lower-case, trim, base-name only)
    source = source_raw.rsplit("/", 1)[-1].strip().lower()

    # fetch existing rows for (Athlete, Date, Activity)
    cur.execute(
        """SELECT Session_ID, Source
             FROM Sessions
            WHERE Athlete_ID = %s
              AND Session_Date = %s
              AND Activity = %s""",
        (aid, dt.date(), activity),
    )
    rows = cur.fetchall()

    # --- scenario 1: nothing there yet ---
    if not rows:
        insert_session(cur, aid, dt, activity, dur_s, dist_m, comment, t2, source)
        return

    # helper to read tuple or dict rows
    def col(row, key, idx):
        return row[key] if isinstance(row, dict) else row[idx]

    # --- scenario 2: replace NULL-source row ---
    for r in rows:
        if col(r, "Source", 1) is None:
            cur.execute("DELETE FROM Sessions WHERE Session_ID = %s",
                        (col(r, "Session_ID", 0),))
            insert_session(cur, aid, dt, activity, dur_s, dist_m,
                           comment, t2, source)
            return

    # --- scenario 4: duplicate filename?  then skip ---
    if any( (col(r, "Source", 1) or "").rsplit("/", 1)[-1].strip().lower() == source
            for r in rows ):
        logger.debug("    · duplicate (same source) – skipped")
        return

    # --- scenario 3: same A/D/A but new filename → insert alongside ---
    insert_session(cur, aid, dt, activity, dur_s, dist_m, comment, t2, source)
# ---------------------------------------------------------------------------



# ── main loop ─────────────────────────────────────────────────────────────

def main():
    conn = get_db_connection(); cur = conn.cursor()
    logger.info("Importing FIT sessions from S3 → MySQL …")

    for aid, _ in iter_athletes_with_links(cur):
        logger.info("Athlete %s", aid)
        for key in iter_fit_keys_for_athlete(aid):
            try:
                buf = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
            except Exception as e:
                logger.error("    ! S3 download failed: %s", e); continue

            rest,max_hr = get_athlete_hr(cur, aid)
            try:
                dt, act, dur_s, dist_m, comment, t2 = parse_fit_bytes(buf, rest, max_hr)
            except Exception as e:
                logger.error("    ! FIT parse failed: %s", e); continue

            fname = key.rsplit("/",1)[-1]
            upsert_session(cur, aid, dt, act, dur_s, dist_m, comment, t2, fname)

    conn.commit(); cur.close(); conn.close()
    logger.info("✓ All done")

if __name__ == "__main__":
    main()
