#!/usr/bin/env python3
# fit_to_gpx.py

import os
import sys
from fitparse import FitFile
import gpxpy
import gpxpy.gpx

def fit_to_gpx(fit_file_path):
    # Create the output file name by replacing .fit with .gpx
    base_name = os.path.splitext(fit_file_path)[0]
    gpx_file_path = f"{base_name}.gpx"

    # Load the FIT file
    fitfile = FitFile(fit_file_path)

    # Create a new GPX object
    gpx = gpxpy.gpx.GPX()
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)

    # Iterate over all records in the FIT file
    for record in fitfile.get_messages('record'):
        record_data = {data.name: data.value for data in record}

        lat_raw = record_data.get('position_lat')
        lon_raw = record_data.get('position_long')

        if lat_raw is not None and lon_raw is not None:
            # Convert semicircles to degrees
            lat = lat_raw * (180 / 2**31)
            lon = lon_raw * (180 / 2**31)
            ele = record_data.get('altitude')
            time = record_data.get('timestamp')

            gpx_point = gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon, elevation=ele, time=time)
            gpx_segment.points.append(gpx_point)


    # Write GPX to file
    with open(gpx_file_path, 'w') as f:
        f.write(gpx.to_xml())

    print(f"Converted '{fit_file_path}' -> '{gpx_file_path}'")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <file.fit>")
        sys.exit(1)

    fit_file = sys.argv[1]
    if not os.path.isfile(fit_file):
        print(f"Error: File '{fit_file}' does not exist.")
        sys.exit(1)

    fit_to_gpx(fit_file)
