import sys
import gpxpy
from math import sin, cos, sqrt, atan2, radians
import datetime
from datetime import datetime as dt
import tkinter as tk
from tkinter import filedialog
import tkinter.font as tkFont
import subprocess
import csv

def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000

    dlon = lon2 - lon1
    dlat = lat2- lat1

    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = R * c
    return distance

def get_points(file_name):
    #Attempt to use the smoothed points  entered, otherwise use default
    Smooth_Points_str = smooth_text.get()

    try:
        Smooth_Points = int(Smooth_Points_str)
    except:
        Smooth_Points = 4
        #print(Smooth_Points)
        smooth_text.delete(0, tk.END)
        smooth_text.insert(tk.END, str(Smooth_Points))

    if file_name[-3:] == "gpx":

        points = parse_gpx(file_name)
    
    else:
        #If it's not a gpx file then it must be a SpeedCoach CSV - right?
        points = parse_speedcoach(file_name)

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
    

def parse_gpx(file_path):

    with open(file_path, 'r') as gpx_file:

        print("GPX File")
        gpx = gpxpy.parse(gpx_file)
        
        points = []
        pt_no = 0
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:

                    points.append({
                        'pt_no' : pt_no,
                        'latitude': point.latitude,
                        'longitude': point.longitude,
                        'time': point.time,
                        'distance': 0,
                        'total_distance': 0,
                        'pace': datetime.timedelta(minutes=10),
                        'smoothed': datetime.timedelta(hours=1)   

                    })
                    
                    pt_no +=  1
        
        return points

def parse_speedcoach(file_path):

    if file_path[-3:]!= "csv":
        messagebox.showerror("Error", "Doesn't look like a Speedcoach file to me") 
        sys.exit()

    print("CSV File")
    #Attempt to use the smoothed points  entered, otherwise use default
    Smooth_Points_str = smooth_text.get()

    try:
        Smooth_Points = int(Smooth_Points_str)
    except:
        Smooth_Points = 4
        #print(Smooth_Points)
        smooth_text.delete(0, tk.END)
        smooth_text.insert(tk.END, str(Smooth_Points))

    rows = []

    with open(file_path, 'r') as csvfile:
        # creating a csv reader object
        csvreader = csv.reader(csvfile)

        for row in csvreader:
            rows.append(row)

        points = []
        #Start_Time = datetime.now()
        pt_no = 0
        SC_State = 0
        #The SC_State goes to:
        #  - 1 when the file is confirmed as a speedcoach file
        #  - 2 when the start time is read
        #  - 3 when the "Per Stroke Data" heading is read
        #  - 4 when it gets to the actual data

        for row in rows:

            columns = []

            for col in row:
                columns.append(col)
                #print(col)

            if len(columns) >0:

                if SC_State == 0:
                    if columns[0] == "Session Information:":
                        SC_State = 1
                        print("Valid SpeedCoach File")

                elif SC_State == 1:
                    if columns[0] == "Start Time:":
                        SC_State = 2
                        start_time = dt.strptime(columns[1], '%m/%d/%Y %H:%M:%S')
                        print("Start Time: " + str(start_time))

                elif SC_State == 2:
                    if columns[0] == "Per-Stroke Data:":
                        SC_State = 3
                        print("Per Stroke Heading Found")

                elif SC_State == 3:
                    if columns[0] == "(Interval)":
                        SC_State = 4
                        print("Starting Point Addition")
                
                else:
                    t = dt.strptime(columns[3] + "00000",'%H:%M:%S.%f')

                    points.append({
                            'pt_no' : pt_no,
                            'latitude': float(columns[22]),
                            'longitude': float(columns[23]),
                            'time': start_time + datetime.timedelta(hours=t.hour,minutes=t.minute,seconds=t.second,microseconds=t.microsecond),
                            'distance': 0,
                            'total_distance': 0,
                            'pace': datetime.timedelta(minutes=10),
                            'smoothed': datetime.timedelta(hours=1)   

                        })
                    
                    pt_no +=  1

                    
        return points


def Save_CSV(points, file_name):

 #Export the points to CSV

    csv_filename = file_name[:-4] +"Points.csv"
    fields = ['pt_no', 'latitude', 'longitude', 'time','distance','total_distance','pace','smoothed'] 

    with open(csv_filename, 'w') as f:  
        write = csv.writer(f)
        
        write.writerow(['pt_no', 'latitude', 'longitude', 'time','distance','total_distance','pace','smoothed'] )
        for point in points:
            write.writerow([point['pt_no'],
                            point['latitude'],
                            point['longitude'],
                            point['time'],
                            point['distance'],
                            point['total_distance'],
                            point['pace'],
                            point['smoothed']])


def Find_Pieces(file_name):

    points = get_points(file_name)

    print("Point Count: " + str(len(points)))

    set_metrics(points)

    if CSV_selected.get() == 1:
        Save_CSV(points, file_name)

    Pieces = []

    #Attempt to use the minimum piece length entered, otherwise use default
    min_dist_str = min_dist_text.get()
    try:
        min_distance = int(min_dist_str)
    except:
        min_distance = 250
        #print(min_distance)
        min_dist_text.delete(0, tk.END)
        min_dist_text.insert(tk.END, str(min_distance))

    #Attempt to use the threshold pace entered, otherwise calculate from max speed
    min_pace_str = threshold_text.get()
    try:
        min_pace = datetime.timedelta(minutes = int(min_pace_str[:1]),seconds = int(min_pace_str[2:]))
    except:
        min_pace =   min(point['smoothed']for point in points) * 1.2
        #print(min_pace)
        threshold_text.delete(0, tk.END)
        threshold_text.insert(tk.END, str(min_pace)[3:7])


    #Attempt to use the gap, otherwise use default
    gap_str = gap_text.get()
    try:
        gap = int(gap_str)
    except:
        gap = 30
        #print(gap)
        gap_text.delete(0, tk.END)
        gap_text.insert(tk.END, str(gap))


    #extract piece start and finishes
    start_index = 0
    In_Piece = False
    Piece_Count = 0

    for end_point in points:
        #print(f"Time: {end_point['time']} , Distance: {end_point['distance']} , Total: {end_point['total_distance']} , Pace: {end_point['pace']} , Smoothed: {end_point['smoothed']}")

        if In_Piece:
            if end_point['smoothed'] > min_pace :
                
                #This is the end of the piece
                In_Piece = False

                Pieces.append({
                    'ID' : Piece_Count,
                    'Start_Point': start_point['pt_no'],
                    'Start_Time': start_point['time'],
                    'Start_Distance' : round(start_point['total_distance'],2),
                    'time' : end_point['time'] - start_point['time'],
                    'End_Point': end_point['pt_no'],
                    'End_Distance' : round(end_point['total_distance'],2),
                    'Pace': (end_point['time'] - start_point['time']) * 500 / (end_point['total_distance'] - start_point['total_distance']),
                    'distance': round(end_point['total_distance'] - start_point['total_distance'],2),
                    'fade' : 0,

                    'Peak_Pace' : 0,
                    'start_type' : ""
                    })

        else :

            if end_point['smoothed'] < min_pace :

                #This is the start of the piece
                In_Piece = True

                #Check if it should be joined to the previous piece
                if Piece_Count >0 :

                    #Concatenate pieces if the last piece ended less than 'Gap' seconds beforee the start of this one
                    if  end_point['time'] - (Pieces[-1]['Start_Time'] + Pieces[-1]['time']) < datetime.timedelta(seconds=gap) :
                        #Delete the last piece and leave the start of this one at the start of that one
                        Pieces.pop() 
                    else :

                        Piece_Count = Piece_Count +1
                        start_point = end_point
                else :
                    Piece_Count = Piece_Count +1
                    start_point = end_point

    if In_Piece:
        #The file has ended while in a piece

        end_point = points[-1]

        Pieces.append({
            'ID' : Piece_Count,
            'Start_Point': start_point['pt_no'],
            'Start_Time': start_point['time'],
            'Start_Distance' : round(start_point['total_distance'],2),
            'time' : end_point['time'] - start_point['time'],
            'End_Point': end_point['pt_no'],
            'End_Distance' : round(end_point['total_distance'],2),
            'Pace': (end_point['time'] - start_point['time']) * 500 / (end_point['total_distance'] - start_point['total_distance']),
            'distance': round(end_point['total_distance'] - start_point['total_distance'],2),
            'fade' : 0,

            'Peak_Pace' : 0,
            'start_type' : ""
            })

    #Adjust the start and end of the pieces
    for piece in Pieces :
        piece['start_type'] = tune_starts(piece, points)
        print(piece['Pace'])

        tune_finishes(min_pace, piece, points) 
    
    #Remove pieces that are too short or too slow
    Pieces = [piece for piece in Pieces if piece['distance']> min_distance]
    Pieces = [piece for piece in Pieces if piece['Pace']< min_pace + datetime.timedelta(seconds=4)]

    #Renumber
    Piece_Count = 0
    for piece in Pieces :
        Piece_Count = Piece_Count +1
        piece['ID'] = Piece_Count

    #Now output the piece table    
    from prettytable import PrettyTable
    t = PrettyTable(['ID','Start Time','Start Distance','Time','End Distance','Pace','Distance','Start Type'])

    for piece in Pieces:
        t.add_row([piece['ID'],piece['Start_Time'].strftime("%H:%M:%S"),piece['Start_Distance'],str(piece['time'])[2:9],piece['End_Distance'],str(piece['Pace'])[3:10],piece['distance'],piece['start_type']])

    return t

def tune_starts(piece, points):
    
    #Identifies the type of start (standing or rolling) and tunes the start points of the piece

    start_time = points[piece['Start_Point'] - int(smooth_text.get())]['time'] - datetime.timedelta(seconds=10)

    print("Comparing:" +str(start_time) + " AND " + str(points[0]['time']))

    if piece['Start_Time'] < points[0]['time'] + datetime.timedelta(seconds=20):
        #The start is the start of the file
        start_point = points[0]
        start_time = start_point['time']
        print("Start of File!!")
    else:
        start_point = points[get_point(start_time,points)]

    end_point = points[piece['End_Point']]

    print("Initial start time: " + str(piece['Start_Time']))
    print("Initial Search Point: "+ str(start_point['time']))
    
    if start_point['pace'] > datetime.timedelta(minutes=5) or start_point['pt_no'] == 0:
        #This is standing start - Need to find the point when you start to move.

        while start_point['pt_no'] <= piece['Start_Point']:

            if start_point['pace'] < datetime.timedelta(minutes=4):
                piece['Start_Point'] =  start_point['pt_no']
                piece['Start_Time'] = start_point['time']
                piece['Start_Distance'] = round(start_point['total_distance'],2)
                piece['time'] = end_point['time'] - start_point['time']
                piece['Pace'] = (end_point['time'] - start_point['time']) * 500 / (end_point['total_distance'] - start_point['total_distance'])
                piece['distance'] = round(end_point['total_distance'] - start_point['total_distance'],2)

                print("Revised Start Time: "+ str(start_point['time']))

                return "Standing"

            start_point = points[start_point['pt_no']+1]
        
    else:
        #This is a rolling start - find the point when fully up to speed (i.e. stopped accelerating and close to piece average)

        while start_point['pt_no'] < piece['Start_Point']+20:
            
            if start_point['pace'] > points[start_point['pt_no']-1]['pace'] - datetime.timedelta(seconds=1) and \
                start_point['pace']< piece['Pace'] + datetime.timedelta(seconds=2):
                
                piece['Start_Point'] =  start_point['pt_no']
                piece['Start_Time'] = start_point['time']
                piece['Start_Distance'] = round(start_point['total_distance'],2)
                piece['time'] = end_point['time'] - start_point['time']
                piece['Pace'] = (end_point['time'] - start_point['time']) * 500 / (end_point['total_distance'] - start_point['total_distance'])
                piece['distance'] = round(end_point['total_distance'] - start_point['total_distance'],2)

                print("Revised Start Time: "+ str(start_point['time']))

                return "Rolling"

            start_point = points[start_point['pt_no']+1]

    
    return "Rolling*"

def tune_finishes(min_pace, piece, points):

    start_point = points[piece['Start_Point']]

    if trim_selected.get() == 1:
        #Trim the piece to nearest 250m

        new_distance = round((piece['distance']+10)/250,0)*250

        if new_distance < 250:
            new_distance = 250
        print(new_distance)

        end_point = start_point

        while end_point['total_distance'] - start_point['total_distance'] < new_distance:
            end_point = points[end_point['pt_no']+1]

        excess = (end_point['total_distance'] - piece['Start_Distance'] - new_distance)/end_point['distance']
        piece['time'] = end_point['time'] - piece['Start_Time'] - ((end_point['time'] - points[end_point['pt_no']-1]['time'])*excess)

        print(piece['Start_Time'], end_point['time'], piece['time'])

        piece['Pace'] = piece['time'] * 500 / new_distance
        piece['distance'] = new_distance
        piece['End_Point'] = end_point['pt_no']
        piece['End_Distance'] =  round(piece['Start_Distance'] + new_distance,2)

    else:
        end_time = points[piece['End_Point'] - int(smooth_text.get())]['time'] - datetime.timedelta(seconds=10)
        end_point = points[get_point(end_time,points)]

        print("Initial end time: " + str(piece['Start_Time'] + piece['time']))
        print("Initial Search Point: "+ str(end_point['time']))

        while end_point['pace'] < min_pace:
            end_point = points[end_point['pt_no'] + 1]
        
        print("Revised finish time: " + str(end_point['time']))

        if end_point['pt_no'] == piece['Start_Point']:
            end_point = points[end_point['pt_no'] + 1]

        piece['End_Point'] = end_point['pt_no']
        piece['End_Distance'] = round(end_point['total_distance'],2)
        piece['distance'] = round(piece['End_Distance'] - piece['Start_Distance'] ,2)
        #print("Start Distance: " + str(piece['Start_Distance']) + ",  End Distance: " + str(piece['End_Distance']))
        piece['time'] = end_point['time'] - piece['Start_Time']
        piece['pace'] = piece['time'] *500 /piece['distance']



def get_point(time,points):
    #gets the point closest to the specifed time

    timegap = datetime.timedelta(hours=1)
    ret_point = 0

    for mypoint in points:
        if abs(mypoint['time']-time) < timegap:
            ret_point = mypoint['pt_no']
            timegap = abs(mypoint['time']-time)

    return ret_point

def set_metrics(points):
    max_pace.configure(text=str(min(point['smoothed']for point in points))[3:7]+" sec/500m") 

    last_point = points[-1]
    wo_distance.configure(text=str(round(last_point['total_distance'],0))+ " m")
    wo_time.configure(text=str(last_point['time']- points[0]['time']))

    move_time = datetime.timedelta(seconds=0)
    move_dist = 0

    for mypoint in points:
        if mypoint['smoothed'] < datetime.timedelta(minutes=5):
            move_time = move_time + mypoint['time'] - mylastpoint['time']
            move_dist = move_dist + mypoint['distance']

        mylastpoint = mypoint
    
    moving_time.configure(text=str(move_time))
    moving_pace.configure(text=str(move_time*500/move_dist)[3:9]+ " sec/500m")

    gps_readings.configure(text=str(len(points)))
    gps_interval.configure(text=str(round((last_point['time']- points[0]['time']).total_seconds()/len(points),2))+ "sec")



def select_file():
    """Open file dialog to select a file and display its path in the text box."""
    file_path = filedialog.askopenfilename()
    if file_path:
        file_path_var.set(file_path)
        result_text.delete(1.0, tk.END)  # Clear previous results

def process_file():
    """Pass the selected file to an external script and display the returned string."""
    file_path = file_path_var.get()
    if file_path:
        try:
            # Run the external script and pass the file path
            result = Find_Pieces(file_path)
            # Display the result in the result text box
            result_text.delete(1.0, tk.END)
            result_text.insert(tk.END, result)
        except subprocess.CalledProcessError as e:
            result_text.delete(1.0, tk.END)
            result_text.insert(tk.END, f"Error: {e}\n{e.stderr}")
    else:
        result_text.delete(1.0, tk.END)
        result_text.insert(tk.END, "Please select a file first.")

# Create the main window and all widgets on the interface
root = tk.Tk()
root.title("Rowing Piecify Interface")

# Variable to hold the selected file path
file_path_var = tk.StringVar()
min_pace_str = tk.StringVar()
CSV_selected = tk.IntVar()
trim_selected = tk.IntVar()

file_frame = tk.Frame(root, height=50)
file_frame.grid(column=0, row=0, sticky=tk.W, padx=5, pady=5)

# UI Elements
file_label = tk.Label(file_frame, text="Data File:")
file_label.grid(column=0, row=0, sticky=tk.W, padx=5, pady=5)

file_path_entry = tk.Entry(file_frame, textvariable=file_path_var, width=70)
file_path_entry.grid(column=1, row=0, sticky=tk.W, padx=5, pady=5)

browse_button = tk.Button(file_frame, text="Browse", command=select_file)
browse_button.grid(column=2, row=0, sticky=tk.W, padx=5, pady=5)

csv_check = tk.Checkbutton(file_frame, text="Save as CSV", variable=CSV_selected,onvalue=1, offvalue=0)
csv_check.grid(column=3, row=0, sticky=tk.W, padx=5, pady=5)

tools_frame = tk.Frame(root)
tools_frame.grid(column=0, row=1, sticky=tk.W, padx=5, pady=5)

param_frame = tk.Frame(tools_frame,highlightbackground="black",highlightthickness=0.5)
param_frame.grid(column=0, row=0, sticky=tk.W, padx=5, pady=5)

param_label = tk.Label(param_frame, text="Piece Paramaters",font=("Helvetica", 11, "bold"))
param_label.grid(column=0, row=0, sticky=tk.W, padx=5, pady=5)

threshold_label = tk.Label(param_frame, text="Piece Threshold (m:ss):")
threshold_label.grid(column=0, row=1, sticky=tk.W, padx=5, pady=5)

threshold_text = tk.Entry(param_frame, width=11)
threshold_text.grid(column=1, row=1, sticky=tk.W, padx=5, pady=5)

smooth_label = tk.Label(param_frame, text="GPS readings to smooth:")
smooth_label.grid(column=0, row=2, sticky=tk.W, padx=5, pady=5)

smooth_text = tk.Entry(param_frame, width=11)
smooth_text.grid(column=1, row=2, sticky=tk.W, padx=5, pady=5)

min_dist_label = tk.Label(param_frame, text="Minimum Piece length (m):")
min_dist_label.grid(column=0, row=3, sticky=tk.W, padx=5, pady=5)

min_dist_text = tk.Entry(param_frame, width=11)
min_dist_text.grid(column=1, row=3, sticky=tk.W, padx=5, pady=5)

gap_label = tk.Label(param_frame, text="Time gap to ignore (sec):")
gap_label.grid(column=0, row=4, sticky=tk.W, padx=5, pady=5)

gap_text = tk.Entry(param_frame, width=11)
gap_text.grid(column=1, row=4, sticky=tk.W, padx=5, pady=5)

trim_check = tk.Checkbutton(param_frame, text="Trim to 250m", variable=trim_selected,onvalue=1, offvalue=0)
trim_check.grid(column=0, row=5, sticky=tk.W, padx=5, pady=5)

process_button = tk.Button(param_frame, text="Find Pieces", command=process_file)
process_button.grid(column=1, row=5, sticky=tk.W, padx=5, pady=5)

metric_frame = tk.Frame(tools_frame,highlightbackground="black",highlightthickness=0.5)
metric_frame.grid(column=1, row=0, sticky=tk.W, padx=5, pady=5)

metric_label = tk.Label(metric_frame, text="Piece Metrics",font=("Helvetica", 11, "bold"))
metric_label.grid(column=0, row=0, sticky=tk.W, padx=5, pady=5)

wo_distance_label = tk.Label(metric_frame, text="Total Workout Distance:")
wo_distance_label.grid(column=0, row=1, sticky=tk.W, padx=5, pady=5)

wo_distance = tk.Label(metric_frame, text="0 m")
wo_distance.grid(column=1, row=1, sticky=tk.W, padx=5, pady=5)

font: dict[str, any] = tkFont.Font(font=wo_distance['font']).actual()
wo_distance.configure(font=(font['family'], font['size'], 'bold'))

wo_time_label = tk.Label(metric_frame, text="Total workout time:")
wo_time_label.grid(column=0, row=2, sticky=tk.W, padx=5, pady=5)

wo_time = tk.Label(metric_frame, text="00:00:00")
wo_time.grid(column=1, row=2, sticky=tk.W, padx=5, pady=5)
wo_time.configure(font=(font['family'], font['size'], 'bold'))

moving_time_label = tk.Label(metric_frame, text="Total moving time:",justify="right")
moving_time_label.grid(column=0, row=3, sticky=tk.W, padx=5, pady=5)

moving_time = tk.Label(metric_frame, text="00:00:00")
moving_time.grid(column=1, row=3, sticky=tk.W, padx=5, pady=5)
moving_time.configure(font=(font['family'], font['size'], 'bold'))

moving_pace_label = tk.Label(metric_frame, text="Average moving pace:")
moving_pace_label.grid(column=0, row=4, sticky=tk.W, padx=5, pady=5)

moving_pace = tk.Label(metric_frame, text="0:00 sec/500m")
moving_pace.grid(column=1, row=4, sticky=tk.W, padx=5, pady=5)
moving_pace.configure(font=(font['family'], font['size'], 'bold'))

max_pace_label = tk.Label(metric_frame, text="Maximum pace:",justify="right")
max_pace_label.grid(column=0, row=5, sticky=tk.W, padx=5, pady=5)

max_pace = tk.Label(metric_frame, text="0:00 sec/500m")
max_pace.grid(column=1, row=5, sticky=tk.W, padx=5, pady=5)
max_pace.configure(font=(font['family'], font['size'], 'bold'))

gps_readings_label = tk.Label(metric_frame, text="GPS readings:")
gps_readings_label.grid(column=2, row=1, sticky=tk.W, padx=5, pady=5)

gps_readings = tk.Label(metric_frame, text="0")
gps_readings.grid(column=3, row=1, sticky=tk.W, padx=5, pady=5)
gps_readings.configure(font=(font['family'], font['size'], 'bold'))

gps_interval_label = tk.Label(metric_frame, text="Average reading interval:")
gps_interval_label.grid(column=2, row=2, sticky=tk.W, padx=5, pady=5)

gps_interval = tk.Label(metric_frame, text="0 sec")
gps_interval.grid(column=3, row=2, sticky=tk.W, padx=5, pady=5)
gps_interval.configure(font=(font['family'], font['size'], 'bold'))

result_text = tk.Text(root, height=20, width=95)
result_text.grid(column=0, row=2, sticky=tk.W, padx=5, pady=5)

# Run the main loop
root.mainloop()
