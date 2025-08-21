#!/usr/bin/env python3
from __future__ import annotations

import io
import os
import logging
import argparse
import xml.etree.ElementTree as ET
from math import sin, cos, sqrt, atan2, radians
from datetime import datetime, timezone, timedelta
from typing import Iterator, Tuple, Optional, List
from collections import defaultdict

import boto3
from fitparse import FitFile

# 🔑 CrewOptic app & tenant plumbing
from run import app                     # Flask app (loads TENANTS)
from db import get_db_connection, tenant_context

# ── storage config (overridden per-tenant in main() or by callers) ────────
S3_BUCKET = os.getenv("S3_BUCKET", "eubctrackingdata")
S3_PREFIX = os.getenv("S3_PREFIX", "fitfiles")   # will become f"{base}/{tenant}"
s3 = boto3.client("s3")                          # ~/.aws/credentials

def configure_storage(bucket: str, prefix: str, client=None) -> None:
    """Allow callers to set S3 bucket/prefix and client (keeps this module importable)."""
    global S3_BUCKET, S3_PREFIX, s3
    S3_BUCKET = bucket
    S3_PREFIX = prefix
    if client is not None:
        s3 = client

# Helper – FIT stores lat/lon as “semicircles”
SEMICIRCLES_TO_DEGREES = 180.0 / 2**31

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────

def norm(name: Optional[str]) -> Optional[str]:
    if name is None: return None
    return name.rsplit("/", 1)[-1].strip().lower()

def row_val(row, key_or_idx):
    if isinstance(row, dict): return row.get(key_or_idx)
    return row[key_or_idx]

def iter_athletes_with_links(cur) -> Iterator[Tuple[int, str]]:
    cur.execute(
        "SELECT Athlete_ID, DropBox "
        "FROM Athletes "
        "WHERE DropBox IS NOT NULL"
    )
    for row in cur.fetchall():
        if isinstance(row, dict):
            aid = row["Athlete_ID"]; link = row["DropBox"]
        else:
            aid, link = row
        yield int(aid), link

def iter_fit_keys_for_athlete(aid: int) -> Iterator[str]:
    # NOTE: S3_PREFIX is tenant-namespaced in main()
    pref = f"{S3_PREFIX}/{aid}/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=pref):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith(".fit"):
                yield key

def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def get_points(points):
    Smooth_Points = 4
    total_distance = 0
    prev_point = None

    for point in points:
        if point['pt_no'] == 0 or prev_point is None:
            point['distance'] = 0
            point['total_distance'] = 0
            point['pace'] = timedelta(minutes=10)
            point['smoothed'] = timedelta(hours=1)
        else:
            distance = get_distance(
                radians(point['latitude']),  radians(point['longitude']),
                radians(prev_point['latitude']), radians(prev_point['longitude'])
            ) or 0.00001

            point['distance'] = distance
            total_distance += distance
            point['total_distance'] = total_distance
            point['pace'] = (point['time'] - prev_point['time']) * 500 / distance

            if point['pt_no'] >= Smooth_Points:
                point['smoothed'] = (
                    (point['time'] - points[point['pt_no']-Smooth_Points]['time']) * 500 /
                    (total_distance - points[point['pt_no']-Smooth_Points]['total_distance'])
                )
            else:
                point['smoothed'] = point['pace']

        prev_point = point
    return points

def parse_fit(fitfile):
    points, pt_no = [], 0
    for record in fitfile.get_messages('record'):
        lat_semis = record.get_value('position_lat')
        lon_semis = record.get_value('position_long')
        ts        = record.get_value('timestamp')
        if lat_semis is None or lon_semis is None or ts is None:
            continue
        latitude  = lat_semis * SEMICIRCLES_TO_DEGREES
        longitude = lon_semis * SEMICIRCLES_TO_DEGREES
        points.append({
            'pt_no': pt_no, 'latitude': latitude, 'longitude': longitude,
            'time': ts, 'distance': 0, 'total_distance': 0,
            'pace': timedelta(minutes=10), 'smoothed': timedelta(hours=1)
        })
        pt_no += 1
    return get_points(points)

def parse_tcx_bytes(buf: bytes):
    ns = {'tcx': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}
    root = ET.fromstring(buf)
    trackpoints = root.findall('.//tcx:Trackpoint', ns)

    points = []; pt_no = 0
    for tp in trackpoints:
        time_node = tp.find("tcx:Time", ns)
        pos_node  = tp.find("tcx:Position", ns)
        if time_node is None or pos_node is None:
            continue
        lat_node = pos_node.find("tcx:LatitudeDegrees", ns)
        lon_node = pos_node.find("tcx:LongitudeDegrees", ns)
        if lat_node is None or lon_node is None:
            continue
        try:
            timestamp = datetime.fromisoformat(time_node.text.replace("Z", "+00:00"))
            lat = float(lat_node.text); lon = float(lon_node.text)
        except Exception:
            continue
        points.append({
            'pt_no': pt_no, 'latitude': lat, 'longitude': lon,
            'time': timestamp, 'distance': 0, 'total_distance': 0,
            'pace': timedelta(minutes=10), 'smoothed': timedelta(hours=1),
        })
        pt_no += 1
    return get_points(points)

def parse_fit_bytes(buf: bytes):
    fit = FitFile(io.BytesIO(buf)); fit.parse()
    return parse_fit(fit)

def parse_file_bytes(key: str, buf: bytes):
    if key.lower().endswith(".tcx"):
        return parse_tcx_bytes(buf)
    elif key.lower().endswith(".fit"):
        return parse_fit_bytes(buf)
    else:
        raise ValueError(f"Unsupported file type for key: {key}")

def get_outings(ts: datetime, aid: int, cur):
    dt = ts.date()
    cur.execute("""
        SELECT s.Athlete_ID, s.Crew_ID, o.Outing_ID, s.Athlete_Name, s.Seat,
               o.Outing_Date, c.Boat_Type
          FROM Seats s
          JOIN Crews c  ON s.Crew_ID  = c.Crew_ID
          JOIN Outings o ON c.Outing_ID = o.Outing_ID
         WHERE o.Outing_Date = %s
           AND s.Athlete_ID  = %s
         ORDER BY o.Outing_ID
    """, (dt, aid))
    return cur.fetchall()

def get_pieces(outingid: int, cur):
    cur.execute("SELECT * FROM Pieces WHERE Outing_ID = %s", (outingid,))
    return cur.fetchall()

def get_gmt(boat_type: str, distance: float, time: timedelta, cur) -> Optional[float]:
    cur.execute("SELECT GMT FROM GMTs WHERE Boat_Type = %s", (boat_type,))
    row = cur.fetchone()
    if not row or ('GMT' not in row if isinstance(row, dict) else False):
        print(f"⚠️ No GMT entry found for Boat_Type '{boat_type}'"); return None

    gmt_value = row['GMT'] if isinstance(row, dict) else row[0]
    gmt_seconds = gmt_value.total_seconds()
    actual_seconds = time.total_seconds()
    if actual_seconds == 0: return None
    # percent of GMT over 2k scaled to piece distance
    return (gmt_seconds * distance) / (actual_seconds * 2000)

def get_results(points, pieces):
    pieces.sort(key=lambda x: x['Distance'], reverse=True)
    for piece in pieces:
        piece['start'] = -1; piece['end'] = -1; piece['time'] = timedelta(days=1)

    for i, piece in enumerate(pieces):
        for start_index, point in enumerate(points):
            end_index = start_index
            while (end_index < len(points) - 1 and
                   points[end_index]['total_distance'] - point['total_distance'] < piece['Distance']):
                end_index += 1
            if end_index >= len(points): continue

            time_taken = points[end_index]['time'] - point['time']
            distance_covered = points[end_index]['total_distance'] - point['total_distance']

            if time_taken < piece['time'] and distance_covered >= piece['Distance']:
                proposed_start = point['pt_no']; proposed_end = points[end_index]['pt_no']
                # avoid overlaps with earlier (longer) pieces we already placed
                overlap = any(not (proposed_end <= p['start'] or proposed_start >= p['end'])
                              for p in pieces[:i])
                if not overlap:
                    piece['start'] = proposed_start
                    piece['end']   = proposed_end
                    piece['time']  = time_taken * piece['Distance'] / (
                        points[piece['end']]['total_distance'] - points[piece['start']]['total_distance']
                    )
    return pieces

def reorder_same_distance_pieces(pieces):
    groups = defaultdict(list)
    for piece in pieces: groups[piece['Distance']].append(piece)
    reordered = []
    for _, group in groups.items():
        if len(group) == 1:
            reordered.extend(group); continue
        matched_results = [
            {'start': p['start'], 'end': p['end'], 'time': p['time']}
            for p in sorted(group, key=lambda p: p['start'])
        ]
        sorted_by_id = sorted(group, key=lambda p: p['Piece_ID'])
        for piece, result in zip(sorted_by_id, matched_results):
            piece['start'] = result['start']; piece['end'] = result['end']; piece['time'] = result['time']
        reordered.extend(sorted_by_id)
    pieces[:] = reordered

def check_chronological_validity(pieces):
    chronological = sorted(pieces, key=lambda p: p['start'])
    piece_ids = [p['Piece_ID'] for p in chronological]
    return piece_ids == sorted(piece_ids), chronological

def format_time(dt):
    if isinstance(dt, datetime):
        return dt.strftime('%H:%M:%S.%f')[:-4]  # TIME(2) precision
    if isinstance(dt, timedelta):
        total_ms = int(dt.total_seconds() * 100)  # 1/100 s
        hours, rem = divmod(total_ms, 360000)
        minutes, rem = divmod(rem, 6000)
        seconds, centi = divmod(rem, 100)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{centi:02}"
    return None

def is_crew_unrateable(cur, crew_id: int) -> bool:
    cur.execute("""
        SELECT EXISTS (
            SELECT 1
              FROM Seats s
              LEFT JOIN Athletes a ON a.Athlete_ID = s.Athlete_ID
             WHERE s.Crew_ID = %s
               AND (s.Athlete_ID IS NULL OR a.Coach = 1)
        ) AS unrateable
    """, (crew_id,))
    row = cur.fetchone()
    val = row["unrateable"] if isinstance(row, dict) else row[0]
    return bool(val)

def insert_results(cursor, pieces, points, outings, aid):
    crew_id = outings[0]['Crew_ID']
    unrated = 1 if is_crew_unrateable(cursor, crew_id) else 0

    for piece in pieces:
        if piece['start'] < 0 or piece['end'] < 0:  # skip unmatched pieces
            continue

        piece_id   = piece['Piece_ID']
        start_time = format_time(points[piece['start']]['time'])
        end_time   = format_time(points[piece['end']]['time'])
        time_taken = format_time(piece['time'])

        gmt_ratio = get_gmt(outings[0]['Boat_Type'], piece['Distance'], piece['time'], cursor)
        gmt_percent = 100 * gmt_ratio if gmt_ratio is not None else None

        sql = """
        INSERT INTO Results (
            Piece_ID, Crew_ID, Start, Finish, Time, Source, GMT_Percent, Unrated
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            Start       = VALUES(Start),
            Finish      = VALUES(Finish),
            Time        = VALUES(Time),
            Source      = VALUES(Source),
            GMT_Percent = VALUES(GMT_Percent),
            Unrated     = VALUES(Unrated)
        """
        cursor.execute(sql, (
            piece_id, crew_id, start_time, end_time, time_taken,
            aid, gmt_percent, unrated
        ))

def process_single_result(cur, aid: int, key: str):
    try:
        buf = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    except Exception as e:
        logger.error("    ! S3 download failed: %s", e)
        return

    try:
        points = parse_file_bytes(key, buf)
    except Exception as e:
        logger.error("    ! File parsing failed: %s", e)
        return

    if not points or len(points) < 2:
        print("No points"); return

    print("Points:", points[-1]['pt_no'], points[1]['time'])

    outings = get_outings(points[1]['time'], aid, cur)
    if not outings:
        print("No outings"); return

    print("Outing:", outings[0]['Outing_ID'])

    for outing in outings:
        pieces = get_pieces(outing['Outing_ID'], cur)
        if not pieces:
            print("No pieces"); continue

        pieces = get_results(points, pieces)
        reorder_same_distance_pieces(pieces)

        is_valid, ordered_pieces = check_chronological_validity(pieces)
        if is_valid:
            print("✅ Pieces are in valid chronological order.")
            for piece in pieces:
                if piece['start'] >= 0 and piece['end'] >= 0:
                    print(
                        f"Piece {piece['Piece_ID']}: start={piece['start']} end={piece['end']} "
                        f"time={piece['time']} distance={points[piece['end']]['total_distance'] - points[piece['start']]['total_distance']}"
                    )
            insert_results(cur, pieces, points, outings, aid)
        else:
            print("❌ Pieces are NOT in valid chronological order.")
            print("Chronological Piece_IDs:", [p['Piece_ID'] for p in ordered_pieces])

# ── main loop ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True, help="Tenant key, e.g. 'eubc' or 'sabc'")
    parser.add_argument("--aid", type=int, help="Athlete ID")
    parser.add_argument("--file", type=str, help="S3 key to process (tenant-namespaced)")
    args = parser.parse_args()

    with app.app_context():
        tenants = app.config.get("TENANTS", {})
        if args.tenant not in tenants:
            raise SystemExit(f"Unknown tenant '{args.tenant}'. Available: {list(tenants.keys())}")

        cfg   = tenants[args.tenant]
        bucket= cfg.get("s3_bucket", S3_BUCKET)
        base  = cfg.get("s3_prefix", "fitfiles")
        prefix= f"{base}/{args.tenant}"  # namespace keys by tenant

        # Use tenant storage settings
        configure_storage(bucket=bucket, prefix=prefix)

        with tenant_context(app, args.tenant):
            conn = get_db_connection(); cur = conn.cursor()
            logger.info("Importing FIT results from s3://%s/%s → MySQL (%s) …", S3_BUCKET, S3_PREFIX, args.tenant)

            if args.aid and args.file:
                process_single_result(cur, args.aid, args.file)
            else:
                for aid, _ in iter_athletes_with_links(cur):
                    for key in iter_fit_keys_for_athlete(aid):
                        process_single_result(cur, aid, key)

            conn.commit(); cur.close(); conn.close()
            logger.info("✓ All done")

if __name__ == "__main__":
    main()
