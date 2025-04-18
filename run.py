from flask import Blueprint, Flask, render_template, request, redirect, url_for, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import pymysql
from db import get_db_connection
from routes.athletes import athletes_bp
from routes.hulls import hulls_bp

app = Flask(__name__)
app.secret_key = "72c26493ac0fcd6849b76f0069d1384d"

app.register_blueprint(athletes_bp)
app.register_blueprint(hulls_bp)

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

