import xml.etree.ElementTree as ET
import csv
import argparse
import os
from math import radians, cos, sin, sqrt, atan2
from datetime import datetime

def haversine(lat1, lon1, lat2, lon2):
    # Earth radius in meters
    R = 6371000  
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)
    a = sin(d_phi/2)**2 + cos(phi1) * cos(phi2) * sin(d_lambda/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

def tcx_to_csv(tcx_file_path):
    if not tcx_file_path.lower().endswith('.tcx'):
        raise ValueError("Input file must have a .tcx extension.")
    
    csv_file_path = os.path.splitext(tcx_file_path)[0] + '.csv'

    namespaces = {
        'tcx': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'
    }

    tree = ET.parse(tcx_file_path)
    root = tree.getroot()

    trackpoints = []
    for tp in root.findall('.//tcx:Trackpoint', namespaces):
        time_str = tp.findtext('tcx:Time', default='', namespaces=namespaces)
        time = datetime.fromisoformat(time_str.replace('Z', '+00:00')) if time_str else None

        pos = tp.find('tcx:Position', namespaces)
        lat = float(pos.findtext('tcx:LatitudeDegrees', default='nan', namespaces=namespaces)) if pos is not None else None
        lon = float(pos.findtext('tcx:LongitudeDegrees', default='nan', namespaces=namespaces)) if pos is not None else None

        hr_elem = tp.find('tcx:HeartRateBpm/tcx:Value', namespaces)
        hr = int(hr_elem.text) if hr_elem is not None else None

        if time and lat is not None and lon is not None:
            trackpoints.append({
                'time': time,
                'lat': lat,
                'lon': lon,
                'hr': hr
            })

    # Calculate distance, pace, and smoothed pace
    total_distance = 0.0
    rows = []
    for i, pt in enumerate(trackpoints):
        # Total distance
        if i > 0:
            prev = trackpoints[i - 1]
            segment_dist = haversine(prev['lat'], prev['lon'], pt['lat'], pt['lon'])
            time_diff = (pt['time'] - prev['time']).total_seconds()
        else:
            segment_dist = 0.0
            time_diff = 0.0

        total_distance += segment_dist

        # Pace for current segment (time per 500m)
        pace = (500 * time_diff / segment_dist) if segment_dist > 0 else None

        # Smoothed pace (last 4 points)
        smoothed_distance = 0.0
        smoothed_time = 0.0
        count = 0
        for j in range(max(0, i - 3), i):
            p1, p2 = trackpoints[j], trackpoints[j + 1]
            d = haversine(p1['lat'], p1['lon'], p2['lat'], p2['lon'])
            t = (p2['time'] - p1['time']).total_seconds()
            smoothed_distance += d
            smoothed_time += t
            count += 1
        smoothed_pace = (500 * smoothed_time / smoothed_distance) if smoothed_distance > 0 else None

        rows.append([
            pt['time'].isoformat(),
            pt['lat'],
            pt['lon'],
            pt['hr'] if pt['hr'] is not None else '',
            round(total_distance, 2),
            round(pace, 2) if pace else '',
            round(smoothed_pace, 2) if smoothed_pace else ''
        ])

    # Write to CSV
    with open(csv_file_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow([
            'Timestamp', 'Latitude', 'Longitude', 'Heart Rate',
            'Total Distance (m)', 'Pace (s/500m)', 'Smoothed Pace (s/500m)'
        ])
        csvwriter.writerows(rows)

    print(f"CSV file saved to: {csv_file_path}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert a TCX file to CSV with GPS, HR, and pace.')
    parser.add_argument('tcx_file', help='Path to the TCX file')

    args = parser.parse_args()
    tcx_to_csv(args.tcx_file)
