from flask import Flask, render_template, request, redirect, url_for, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql
import datetime

app = Flask(__name__)
app.secret_key = "72c26493ac0fcd6849b76f0069d1384d"

# Flask-Login setup
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# MySQL Config
db_config = {
    'host': 'eubcdb-2.cp6ymm2sk6ub.eu-west-2.rds.amazonaws.com',
    'user': 'admin',
    'password': 'Flockhart',
    'database': 'eubcdb',
    'cursorclass': pymysql.cursors.DictCursor  # So we can use dict-style access
}

class User(UserMixin):
    def __init__(self, athlete_data):
        self.id = athlete_data['Athlete_ID']
        self.name = athlete_data['Full_Name']
        self.email = athlete_data['Email']
        self.coach = athlete_data['Coach']

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Athletes WHERE Athlete_ID = %s", (user_id,))
        user = cursor.fetchone()
    conn.close()
    return User(user) if user else None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM Athletes WHERE Email = %s", (email,))
            user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['Password_Hash'], password):
            login_user(User(user))
            if user['Coach']:
                return redirect(url_for('coach_home'))
            else:
                return redirect(url_for('athlete_home'))
        else:
            return "Invalid credentials", 401

    return render_template('login.html')

@app.route('/')
@login_required
def coach_home():
    if not current_user.coach:
        return render_template('athlete_home.html', user=current_user)
    return render_template('index.html', user=current_user)

@app.route('/athlete_home')
@login_required
def athlete_home():
    return render_template('athlete_home.html', user=current_user)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

def get_db_connection():
    return pymysql.connect(**db_config)

# Athletes Page
@app.route('/athletes')
def athletes():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Athletes where Coach IS NULL")
        data = cursor.fetchall()
    conn.close()
    return render_template('athletes.html', athletes=data)

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
    if not current_user.coach:
        return render_template('athlete_home.html', user=current_user)
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

@app.before_request
def require_login():
    # Allow access to login page and static files without being logged in
    allowed_routes = ['login', 'static']

    if request.endpoint is None:
        return

    if request.endpoint not in allowed_routes and not current_user.is_authenticated:
        return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

