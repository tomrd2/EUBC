
from __future__ import annotations

import io
import logging
import argparse
from math import sin, cos, sqrt, atan2, radians
from datetime import datetime, timezone, timedelta
from typing import Iterator, Tuple
from collections import defaultdict

import boto3
from fitparse import FitFile
from db import get_db_connection

# ── configuration ────────────────────────────────────────────────────────
S3_BUCKET = "eubctrackingdata"
S3_PREFIX = "fitfiles"

# Helper – FIT stores lat/lon as “semicircles”
SEMICIRCLES_TO_DEGREES = 180.0 / 2**31

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


def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000

    dlon = lon2 - lon1
    dlat = lat2- lat1

    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = R * c
    return distance

def get_points(points):
    #Attempt to use the smoothed points  entered, otherwise use default

    Smooth_Points = 4

    total_distance = 0

    for point in points:

        if point['pt_no'] == 0:

            point['distance'] = 0

        else:

            distance = get_distance(radians(point['latitude']),radians(point['longitude']),radians(prev_point['latitude']),radians(prev_point['longitude']))
            if distance == 0:
                distance = 0.00001

            point['distance'] = distance

            total_distance = total_distance + distance
            point['total_distance'] = total_distance

            point['pace'] = (point['time'] - prev_point['time']) * 500 / distance

            if point['pt_no'] >= Smooth_Points :
                point['smoothed'] = (point['time'] - points[point['pt_no']-Smooth_Points]['time']) * 500 / (total_distance - points[point['pt_no']-Smooth_Points]['total_distance'])

            else :
                point['smoothed'] = point['pace']


        prev_point = point

    return points

def parse_fit(fitfile):
    """
    Parse a FIT file and return a list of points that mirrors the structure
    produced by `parse_gpx`.

    Each list item is a dict with:
        pt_no, latitude, longitude, time,
        distance, total_distance, pace, smoothed
    """

    points  = []
    pt_no   = 0

    # Iterate over every "record" message (the one that carries GPS data)
    for record in fitfile.get_messages('record'):
        lat_semis = record.get_value('position_lat')
        lon_semis = record.get_value('position_long')
        ts        = record.get_value('timestamp')

        # Skip records that don’t have valid coordinates/time
        if lat_semis is None or lon_semis is None or ts is None:
            continue

        # Convert to decimal degrees
        latitude  = lat_semis * SEMICIRCLES_TO_DEGREES
        longitude = lon_semis * SEMICIRCLES_TO_DEGREES

        points.append({
            'pt_no'        : pt_no,
            'latitude'     : latitude,
            'longitude'    : longitude,
            'time'         : ts,                       # already a datetime object
            'distance'     : 0,                        # to be filled later
            'total_distance': 0,                       # to be filled later
            'pace'         : timedelta(minutes=10),
            'smoothed'     : timedelta(hours=1),
        })

        pt_no += 1

    points = get_points(points)

    return points


# ── FIT parsing ───────────────────────────────────────────────────────────

def parse_fit_bytes(buf: bytes):
    fit = FitFile(io.BytesIO(buf)); fit.parse()

    points = parse_fit(fit)

    return points


def get_outings(ts,aid,cur):

    dt = str(ts.date())

    query = "select s.Athlete_ID, s.Crew_ID, o.Outing_ID, s.Athlete_Name, s.Seat, o.Outing_Date, c.Boat_Type "
    query += "FROM Seats s "
    query += "inner join Crews c on s.Crew_ID = c.Crew_ID "
    query += "inner join Outings o on c.Outing_ID = o.Outing_ID "
    query += "where o.Outing_date = '" + dt + "' "
    query += "and s.Athlete_ID = " + str(aid)
    query += " ORDER BY o.Outing_ID "

    #print(query)

    cur.execute(query)

    return cur.fetchall()

def get_pieces(outingid,cur):

    query = "Select * from Pieces WHERE Outing_ID="+str(outingid)

    cur.execute(query)

    return cur.fetchall()

def get_gmt(boat_type, distance, time, cur):
    cur.execute("SELECT GMT FROM GMTs WHERE Boat_Type = %s", (boat_type,))
    row = cur.fetchone()
    
    if not row or 'GMT' not in row or not row['GMT']:
        print(f"⚠️ No GMT entry found for Boat_Type '{boat_type}'")
        return None

    gmt_value = row['GMT']

    # Convert time and GMT to total seconds
    gmt_seconds = gmt_seconds = gmt_value.total_seconds()
    actual_seconds = time.total_seconds()

    if actual_seconds == 0:
        return None  # Avoid division by zero

    # Calculate GMT percent
    gmt_percent = (gmt_seconds * distance) / (actual_seconds * 2000)

    return gmt_percent


def get_results(points, pieces):

    # Sort longest-first
    pieces.sort(key=lambda x: x['Distance'], reverse=True)

    # Initialize placeholders
    for piece in pieces:
        piece['start'] = -1
        piece['end'] = -1
        piece['time'] = timedelta(days=1)

    for i, piece in enumerate(pieces):
        for start_index, point in enumerate(points):

            end_index = start_index
            while (
                end_index < len(points) - 1 and
                points[end_index]['total_distance'] - point['total_distance'] < piece['Distance']
            ):
                end_index += 1

            if end_index >= len(points):
                continue

            time_taken = points[end_index]['time'] - point['time']
            distance_covered = points[end_index]['total_distance'] - point['total_distance']

            if time_taken < piece['time'] and distance_covered >= piece['Distance']:
                # Proposed start and end
                proposed_start = point['pt_no']
                proposed_end = points[end_index]['pt_no']

                # Check for overlap with previously assigned pieces
                overlap = False
                for j in range(i):  # only check against already-filled pieces
                    p = pieces[j]
                    if not (proposed_end <= p['start'] or proposed_start >= p['end']):
                        overlap = True
                        break

                if not overlap:
                    piece['start'] = proposed_start
                    piece['end'] = proposed_end
                    piece['time'] = time_taken * piece['Distance'] / (points[piece['end']]['total_distance'] - points[piece['start']]['total_distance'])

    return pieces

def reorder_same_distance_pieces(pieces):
    # Group pieces by Distance
    groups = defaultdict(list)
    for piece in pieces:
        groups[piece['Distance']].append(piece)

    reordered = []

    for distance, group in groups.items():
        if len(group) == 1:
            reordered.extend(group)
            continue

        # Extract the matched results separately
        matched_results = [
            {'start': p['start'], 'end': p['end'], 'time': p['time']}
            for p in sorted(group, key=lambda p: p['start'])  # sort by workout order
        ]

        # Now assign those results to pieces sorted by Piece_ID
        sorted_by_id = sorted(group, key=lambda p: p['Piece_ID'])

        for piece, result in zip(sorted_by_id, matched_results):
            piece['start'] = result['start']
            piece['end'] = result['end']
            piece['time'] = result['time']

        reordered.extend(sorted_by_id)

    # Overwrite original list with reordered one
    pieces[:] = reordered

def check_chronological_validity(pieces):
    # Step 1: Sort by workout order (start point number)
    chronological = sorted(pieces, key=lambda p: p['start'])

    # Step 2: Extract Piece_IDs in that order
    piece_ids = [p['Piece_ID'] for p in chronological]

    # Step 3: Check if Piece_IDs are in ascending order
    is_valid = piece_ids == sorted(piece_ids)

    return is_valid, chronological

def format_time(dt):
    """Format a datetime or timedelta as TIME(2) SQL string."""
    if isinstance(dt, datetime):
        return dt.strftime('%H:%M:%S.%f')[:-4]  # TIME(2) precision
    elif isinstance(dt, timedelta):
        total_seconds = int(dt.total_seconds())
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        milliseconds = int(dt.microseconds / 10000)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:02}"
    return None

def insert_results(cursor, pieces, points, outings, aid):
    for piece in pieces:
        piece_id = piece['Piece_ID']
        crew_id = outings[0]['Crew_ID']
        start_time = format_time(points[piece['start']]['time'])
        end_time = format_time(points[piece['end']]['time'])
        time_taken = format_time(piece['time'])

        gmt_percent = 100 * get_gmt(outings[0]['Boat_Type'], piece['Distance'],piece['time'],cursor)

        sql = """
        INSERT INTO Results (
            Piece_ID, Crew_ID, Start, Finish, Time, Source, GMT_Percent
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            Start = VALUES(Start),
            Finish = VALUES(Finish),
            Time = VALUES(Time),
            Source = VALUES(Source),
            GMT_Percent = VALUES(GMT_Percent)
        """

        cursor.execute(sql, (
            piece_id,
            crew_id,
            start_time,
            end_time,
            time_taken,
            aid,
            gmt_percent
        ))

def process_single_result(cur, aid: int, key: str):
    try:
        buf = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    except Exception as e:
        logger.error("    ! S3 download failed: %s", e)
        return

    points = parse_fit_bytes(buf)

    if not points:
        print("No points")
        return

    print("Points:", points[-1]['pt_no'], points[1]['time'])

    outings = get_outings(points[1]['time'], aid, cur)
    if not outings:
        print("No outings")
        return

    print("Outing:", outings[0]['Outing_ID'])

    for outing in outings:
        pieces = get_pieces(outing['Outing_ID'], cur)

        if not pieces:
            print("No pieces")
            continue

        pieces = get_results(points, pieces)
        reorder_same_distance_pieces(pieces)

        is_valid, ordered_pieces = check_chronological_validity(pieces)

        if is_valid:
            print("✅ Pieces are in valid chronological order.")
            for piece in pieces:
                print(
                    f"Piece {piece['Piece_ID']}: start={piece['start']} end={piece['end']} "
                    f"time={piece['time']} distance={points[piece['end']]['total_distance'] - points[piece['start']]['total_distance']}"
                )
            insert_results(cur, pieces, points, outings, aid)
        else:
            print("❌ Pieces are NOT in valid chronological order.")
            print("Chronological Piece_IDs:", [p['Piece_ID'] for p in ordered_pieces])



# ── main loop ─────────────────────────────────────────────────────────────

import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aid", type=int, help="Athlete ID")
    parser.add_argument("--file", type=str, help="S3 key to process")
    args = parser.parse_args()

    conn = get_db_connection(); cur = conn.cursor()
    logger.info("Importing FIT results from S3 → MySQL …")

    if args.aid and args.file:
        process_single_result(cur, args.aid, args.file)
    else:
        # fallback to process all (legacy batch behavior)
        for aid, _ in iter_athletes_with_links(cur):
            for key in iter_fit_keys_for_athlete(aid):
                process_single_result(cur, aid, key)

    conn.commit(); cur.close(); conn.close()
    logger.info("✓ All done")


if __name__ == "__main__":
    main()
