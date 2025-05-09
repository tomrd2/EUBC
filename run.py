from flask import Blueprint, Flask, render_template, request, redirect, url_for, session, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import pymysql

import os
from dotenv import load_dotenv
# Load the .env file
load_dotenv()

#Adding a comment to test GIT

from db import get_db_connection
from routes.athletes import athletes_bp
from routes.hulls import hulls_bp
from routes.sessions import sessions_bp
from routes.outings import outings_bp
from routes.lineups import lineups_bp
from routes.pieces import pieces_bp
from routes.timing import timing_bp
from routes.results import results_bp
from routes.view_lineups import view_lineups_bp

from sockets import socketio  # ✅ Import the initialized socketio instance

app = Flask(__name__)  # ✅ NOW define the app
# Accessing the secret key from the variable defined as SECRET_KEY in .env file (export SECRET_KEY={your_secret_key'})
app.secret_key = os.getenv('SECRET_KEY')

socketio.init_app(app)  # ✅ Now initialize socketio AFTER defining app

# Register Blueprints
app.register_blueprint(athletes_bp)
app.register_blueprint(hulls_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(outings_bp)
app.register_blueprint(lineups_bp)
app.register_blueprint(view_lineups_bp)
app.register_blueprint(pieces_bp)
app.register_blueprint(timing_bp)
app.register_blueprint(results_bp)

# Flask-Login setup
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)


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

@app.before_request
def require_login():
    # Allow access to login page and static files without being logged in
    allowed_routes = ['login', 'static']

    if request.endpoint is None:
        return

    if request.endpoint not in allowed_routes and not current_user.is_authenticated:
        return redirect(url_for('login'))


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form['current_password']
        new_pw = request.form['new_password']
        confirm_pw = request.form['confirm_password']

        if new_pw != confirm_pw:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('change_password'))

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT Password_Hash FROM Athletes WHERE Athlete_ID = %s", (current_user.id,))
            user = cursor.fetchone()

            if user and check_password_hash(user['Password_Hash'], current_pw):
                print("Password correct")
            else:
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('change_password'))

            hashed_pw = generate_password_hash(new_pw)
            cursor.execute("UPDATE Athletes SET Password_Hash = %s WHERE Athlete_ID = %s", (hashed_pw, current_user.id))
            conn.commit()
        conn.close()

        flash('Password changed successfully.', 'success')
        if current_user.coach:
            return redirect(url_for('coach_home'))
        else:
            return redirect(url_for('athlete_home'))

    return render_template('change_password.html')

if __name__ == '__main__':
    from sockets import socketio
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
