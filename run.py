from flask import Blueprint, Flask, render_template, request, redirect, url_for, session, flash, g, abort,send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
import os
from dotenv import load_dotenv

load_dotenv()

from db import get_db_connection  # <-- your new tenant-aware db.py
from routes.athletes import athletes_bp
from routes.hulls import hulls_bp
from routes.sessions import sessions_bp
from routes.outings import outings_bp
from routes.lineups import lineups_bp
from routes.pieces import pieces_bp
from routes.timing import timing_bp
from routes.results import results_bp
from routes.view_lineups import view_lineups_bp
from routes.dashboard import dashboard_bp
from routes.params import params_bp

from sockets import socketio  # ✅

# ---------------------------
# App + tenant plumbing
# ---------------------------
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.secret_key = os.getenv('SECRET_KEY')

# If you’re loading tenants from YAML/SSM, inject here; for now assume you did in create_app earlier.
# Example placeholder (replace with your real loader):
import yaml, os

def load_tenants():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, 'tenants.yaml')
    with open(path, 'r') as f:
        data = yaml.safe_load(f) or {}
    # normalize to lowercase keys
    return {str(k).strip().lower(): v for k, v in data.items()}

app.config['TENANTS'] = load_tenants()
print("TENANTS LOADED:", list(app.config['TENANTS'].keys()))

def _tenant_exists(club):
    return bool(club) and club in app.config.get('TENANTS', {})

@app.url_value_preprocessor
def pull_tenant(endpoint, values):
    # Only do tenant plumbing for routes that have <club> in the URL
    if not values or 'club' not in values:
        return

    club = (values.pop('club') or '').strip().lower()
    if not _tenant_exists(club):
        abort(404, description="Unknown club")

    g.tenant_key = club
    g.tenant = app.config['TENANTS'][club]

@app.url_defaults
def add_tenant(endpoint, values):
    if values is None:
        return
    if endpoint == 'static':   # skip Flask's built-in static
        return
    if 'club' not in values and hasattr(g, 'tenant_key'):
        values['club'] = g.tenant_key

# ---------------------------
# Socket.IO
# ---------------------------
socketio.init_app(app)

# ---------------------------
# Flask-Login
# ---------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'core.login'  # endpoint inside our core blueprint

class User(UserMixin):
    def __init__(self, athlete_data, tenant_key):
        self.id = athlete_data['Athlete_ID']
        self.name = athlete_data['Full_Name']
        self.email = athlete_data['Email']
        self.coach = athlete_data['Coach']
        self.tenant_key = tenant_key

    def get_id(self):
        # store "tenant:user_id" in the session
        return f"{self.tenant_key}:{self.id}"

@login_manager.user_loader
def load_user(composite_id: str):
    try:
        tenant_key, user_id = composite_id.split(':', 1)
    except ValueError:
        return None
    if tenant_key != getattr(g, 'tenant_key', None):
        return None

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM Athletes WHERE Athlete_ID = %s", (user_id,))
            row = cursor.fetchone()
            return User(row, tenant_key) if row else None
    finally:
        conn.close()

# Optional: ensure redirects to login keep the correct club in the URL
@login_manager.unauthorized_handler
def _unauth():
    # url_defaults will inject g.tenant_key automatically
    return redirect(url_for('core.login'))

public_bp = Blueprint("public", __name__)

@public_bp.route("/")
def landing():
    clubs = []
    for key, cfg in app.config.get("TENANTS", {}).items():
        display = cfg.get("display_name", key.upper())
        logo    = cfg.get("logo", "Logo.png")
        clubs.append({
            "key": key,
            "name": display,
            "logo_url": url_for("club_static", club=key, filename=logo),
            "login_url": url_for("core.login", club=key),
        })
    return render_template("landing.html", clubs=clubs)

@public_bp.route("/privacy")
def privacy():
    # Use a global/static background (not tenant-specific) so it works publicly
    return render_template("privacy.html")

# ---------------------------
# Core blueprint (auth + home)
# ---------------------------
core_bp = Blueprint('core', __name__)

@core_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM Athletes WHERE Email = %s", (email,))
                user = cursor.fetchone()
            if user and check_password_hash(user['Password_Hash'], password):
                u = User(user, g.tenant_key)
                login_user(u)
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE Athletes SET Last_Login = NOW() WHERE Athlete_ID = %s",
                        (user['Athlete_ID'],)
                    )
                conn.commit()
                return redirect(url_for('core.app_menu'))
            else:
                flash("Invalid credentials", "login_error")
                return redirect(url_for('core.login'))
        finally:
            conn.close()
    return render_template('login.html')


@core_bp.route('/menu')
@login_required
def app_menu():
    return render_template('home.html', user=current_user)

@core_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('core.login'))

@core_bp.before_app_request
def require_login():
    if request.endpoint is None:
        return

    # Allow requests that are not for a tenant route (i.e., no <club> in view args)
    va = getattr(request, "view_args", None) or {}
    if "club" not in va:
        return  # public / non-tenant page (e.g., "/"), let it through

    # Allow tenant login + tenant static without auth
    if request.endpoint in {"core.login", "core.app_privacy", "club_static"}:
        return

    if not current_user.is_authenticated:
        club = va.get("club")
        return redirect(url_for("core.login", club=club))

    
@core_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw     = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')

        if new_pw != confirm_pw:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('core.change_password'))

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Verify current password
                cursor.execute(
                    "SELECT Password_Hash FROM Athletes WHERE Athlete_ID = %s",
                    (current_user.id,)
                )
                row = cursor.fetchone()
                if not (row and check_password_hash(row['Password_Hash'], current_pw)):
                    flash('Current password is incorrect.', 'error')
                    return redirect(url_for('core.change_password'))

                # Update to new password
                hashed_pw = generate_password_hash(new_pw)
                cursor.execute(
                    "UPDATE Athletes SET Password_Hash = %s WHERE Athlete_ID = %s",
                    (hashed_pw, current_user.id)
                )
            conn.commit()
            flash('Password changed successfully.', 'success')
            return redirect(url_for('core.app_menu'))
        finally:
            conn.close()

    return render_template('change_password.html')

@app.route('/<club>/static/<path:filename>')
def club_static(filename):  # ← remove `club` here
    key = (getattr(g, 'tenant_key', '') or '').strip().lower()
    tenant = app.config['TENANTS'].get(key)
    if not tenant:
        abort(404)

    root = tenant.get('static_root', '')
    if not os.path.isabs(root):
        root = os.path.join(os.path.dirname(__file__), root)

    full_path = os.path.normpath(os.path.join(root, filename))
    print("SERVE STATIC", {"club": key, "root": root, "file": filename,
                           "exists": os.path.isfile(full_path)})

    # harden against path traversal
    if not os.path.abspath(full_path).startswith(os.path.abspath(root) + os.sep):
        abort(403)
    if not os.path.isfile(full_path):
        abort(404)

    return send_from_directory(root, filename, conditional=True)


# ---------------------------
# Register blueprints UNDER '/<club>'
# (No changes inside the blueprints themselves.)
# ---------------------------

app.register_blueprint(public_bp)   # note: no url_prefix
app.register_blueprint(core_bp,          url_prefix='/<club>')
app.register_blueprint(athletes_bp,      url_prefix='/<club>')
app.register_blueprint(hulls_bp,         url_prefix='/<club>')
app.register_blueprint(sessions_bp,      url_prefix='/<club>')
app.register_blueprint(outings_bp,       url_prefix='/<club>')
app.register_blueprint(lineups_bp,       url_prefix='/<club>')
app.register_blueprint(view_lineups_bp,  url_prefix='/<club>')
app.register_blueprint(pieces_bp,        url_prefix='/<club>')
app.register_blueprint(timing_bp,        url_prefix='/<club>')
app.register_blueprint(results_bp,       url_prefix='/<club>')
app.register_blueprint(dashboard_bp,     url_prefix='/<club>')
app.register_blueprint(params_bp, url_prefix='/<club>')

# ---------------------------
# Gunicorn/socketio exports
# ---------------------------
application = app
socketio_app = app

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
