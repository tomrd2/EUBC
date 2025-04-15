from flask import Flask, render_template, request, redirect, url_for
import pymysql
import datetime

app = Flask(__name__)
app.secret_key = "72c26493ac0fcd6849b76f0069d1384d"  # Replace with a secure value

# MySQL Config
db_config = {
    'host': 'eubcdb-2.cp6ymm2sk6ub.eu-west-2.rds.amazonaws.com',
    'user': 'admin',
    'password': 'Flockhart',
    'database': 'eubcdb',
    'cursorclass': pymysql.cursors.DictCursor  # So we can use dict-style access
}

def get_db_connection():
    return pymysql.connect(**db_config)

# Home Page
@app.route('/')
def home():
    return render_template('home.html')

# Athletes Page
@app.route('/athletes')
def athletes():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Athletes")
        data = cursor.fetchall()
    conn.close()
    return render_template('index.html', athletes=data)

@app.route('/add', methods=['POST'])
def add_athlete():
    data = request.form
    sculls_value = 1 if 'Sculls' in data else 0
    cox_value = 1 if 'Cox' in data else 0

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Athletes (Athlete_ID, Full_Name, Initials, M_W, Side, Sculls, Cox, Joined, Email)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data['Athlete_ID'], data['Full_Name'], data['Initials'], data['M_W'],
            data['Side'], sculls_value, cox_value, data['Joined'], data['Email']
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('athletes'))

@app.route('/edit/<int:athlete_id>', methods=['POST'])
def edit_athlete(athlete_id):
    data = request.form
    sculls_value = 1 if 'Sculls' in data else 0
    cox_value = 1 if 'Cox' in data else 0

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE Athletes SET Full_Name=%s, Initials=%s, M_W=%s, Side=%s, Sculls=%s, Cox=%s, Joined=%s, Email=%s
            WHERE Athlete_ID=%s
        """, (
            data['Full_Name'], data['Initials'], data['M_W'], data['Side'],
            sculls_value, cox_value, data['Joined'], data['Email'], athlete_id
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('athletes'))

# Hulls Page
@app.route('/hulls')
def hulls():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Hulls")
        hulls = cursor.fetchall()
    conn.close()
    return render_template('hulls.html', hulls=hulls)

@app.route('/add_hull', methods=['POST'])
def add_hull():
    data = request.form
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Hulls (Hull_ID, Hull_Name, Boat_Type, Max_Weight)
            VALUES (%s, %s, %s, %s)
        """, (
            data['Hull_ID'], data['Hull_Name'], data['Boat_Type'], data['Max_Weight']
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('hulls'))

@app.route('/edit_hull/<int:hull_id>', methods=['POST'])
def edit_hull(hull_id):
    data = request.form
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE Hulls SET Hull_Name=%s, Boat_Type=%s, Max_Weight=%s
            WHERE Hull_ID=%s
        """, (
            data['Hull_Name'], data['Boat_Type'], data['Max_Weight'], hull_id
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('hulls'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

