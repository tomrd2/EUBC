from flask import Blueprint, Flask, render_template, request, redirect, url_for, session, flash, current_app
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import os, secrets, string, smtplib, ssl
from email.message import EmailMessage
from flask import current_app, g, abort
from typing import Optional  # add this import

import datetime
import pymysql
from pymysql import IntegrityError
from db import get_db_connection

athletes_bp = Blueprint('athletes', __name__)

def _generate_temp_password(length: int = 12) -> str:
    # at least one lower, one upper, one digit
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = ''.join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw

def _send_mail(to_email: str, subject: str, text: str, html: Optional[str] = None) -> None:
    # Prefer tenant-specific mail config, fall back to env vars
    tcfg = (current_app.config.get("TENANTS", {}).get(getattr(g, "tenant_key", ""), {}) or {})
    m = tcfg.get("mail", {}) if isinstance(tcfg, dict) else {}

    host = m.get("smtp_host", os.getenv("SMTP_HOST"))
    port = int(m.get("smtp_port", os.getenv("SMTP_PORT", "587")))
    user = m.get("smtp_user", os.getenv("SMTP_USER"))
    pwd  = m.get("smtp_pass", os.getenv("SMTP_PASS"))
    from_email = m.get("from_email", os.getenv("FROM_EMAIL", "no-reply@crewoptic.com"))
    from_name  = m.get("from_name",  os.getenv("FROM_NAME",  "CrewOptic"))

    if not all([host, port, user, pwd, from_email]):
        raise RuntimeError("SMTP settings are missing for this tenant")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port) as s:
        s.starttls(context=context)
        s.login(user, pwd)
        s.send_message(msg)


# Athletes Page
@athletes_bp.route('/athletes')
@login_required
def athletes():
    if not current_user.coach:
        return redirect(url_for('core.app_menu'))

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM Athletes ORDER By Coach, Full_Name")
        data = cursor.fetchall()
    conn.close()
    return render_template('athletes.html', athletes=data)

from pymysql.err import IntegrityError
from flask import current_app, flash, redirect, url_for

from pymysql.err import IntegrityError
from flask import flash, redirect, url_for, current_app

@athletes_bp.route('/add', methods=['POST'])
@login_required
def add_athlete():
    data = request.form

    # Normalize inputs
    full_name = data.get('Full_Name', '').strip()
    initials  = data.get('Initials', '').strip().upper()
    m_w       = data.get('M_W', '').strip()
    side      = _none_if_empty(data.get('Side', '').strip())
    joined    = _none_if_empty(data.get('Joined', '').strip())
    email     = _none_if_empty(data.get('Email', '').strip())
    sculls_value = 1 if 'Sculls' in data else 0
    cox_value    = 1 if 'Cox' in data else 0

    if not initials:
        flash("Please enter initials.", "danger")
        return redirect(url_for('athletes.athletes'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # One-shot, race-safe insert: insert only if no row with same initials exists.
            cursor.execute("""
                INSERT INTO Athletes (Full_Name, Initials, M_W, Side, Sculls, Cox, Joined, Email)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s
                FROM DUAL
                WHERE NOT EXISTS (
                    SELECT 1 FROM Athletes WHERE Initials = %s
                )
            """, (full_name, initials, m_w, side, sculls_value, cox_value, joined, email, initials))

            # rowcount == 1 -> inserted; rowcount == 0 -> duplicate
            if cursor.rowcount == 1:
                conn.commit()
                flash("Athlete added.", "success")
            else:
                conn.rollback()
                flash(f'Initials "{initials}" are already in use. Please choose unique initials.', "danger")
                # optional: drive the UI to reopen the modal/focus the field
                return redirect(url_for('athletes.athletes', error='dup_initials', initials=initials))

        return redirect(url_for('athletes.athletes'))
    finally:
        conn.close()


@athletes_bp.route('/edit/<int:athlete_id>', methods=['POST'])
@login_required
def edit_athlete(athlete_id):
    data = request.form
    sculls_value = 1 if 'Sculls' in data else 0
    coach_value  = 1 if 'Coach'  in data else 0  # <-- NEW

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE Athletes
            SET Full_Name=%s,
                Initials=%s,
                M_W=%s,
                Side=%s,
                Sculls=%s,
                Coach=%s,
                Joined=%s,
                Email=%s
            WHERE Athlete_ID=%s
        """, (
            data['Full_Name'], data['Initials'], data['M_W'], data['Side'],
            sculls_value, coach_value, data['Joined'], data['Email'], athlete_id
        ))
        conn.commit()
    conn.close()
    return redirect(url_for('athletes.athletes'))


@athletes_bp.route('/reset_password/<int:athlete_id>', methods=['POST'])
@login_required
def reset_password(athlete_id):
    if not getattr(current_user, "coach", False):
        abort(403)

    # Get athlete + email
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT Athlete_ID, Full_Name, Email FROM Athletes WHERE Athlete_ID=%s", (athlete_id,))
            athlete = cur.fetchone()
            if not athlete:
                flash("Athlete not found.", "error")
                return redirect(url_for('athletes.athletes'))

            full_name = athlete["Full_Name"] if isinstance(athlete, dict) else athlete[1]
            email     = athlete["Email"]     if isinstance(athlete, dict) else athlete[2]
            if not email:
                flash("No email on file for this athlete.", "error")
                return redirect(url_for('athletes.athletes'))

            # Generate + save new password (hashed)
            new_pw  = _generate_temp_password(12)
            hashed  = generate_password_hash(new_pw)
            cur.execute("UPDATE Athletes SET Password_Hash=%s WHERE Athlete_ID=%s", (hashed, athlete_id))
            conn.commit()
    finally:
        conn.close()

    # Build login link for this tenant (ProxyFix is already set up)
    login_url = url_for('core.login', _external=True)
    club_name = (getattr(g, "tenant", {}) or {}).get("display_name", getattr(g, "tenant_key", "your club")).upper()

    text = f"""Hi {full_name},

A new password has been set for your CrewOptic account ({club_name}).

Temporary password: {new_pw}

Sign in here: {login_url}

For your security, please log in and change your password immediately (Menu → Change Password).
If you didn’t request this, please contact your coach.
"""
    html = f"""<p>Hi {full_name},</p>
<p>A new password has been set for your CrewOptic account (<strong>{club_name}</strong>).</p>
<p><strong>Temporary password:</strong> <code>{new_pw}</code></p>
<p>Sign in here: <a href="{login_url}">{login_url}</a></p>
<p>For your security, please log in and change your password immediately (Menu → <em>Change Password</em>).</p>
<p>If you didn’t request this, please contact your coach.</p>
"""

    try:
        _send_mail(email, f"{club_name} – Your new CrewOptic password", text, html)
        flash(f"Password reset. Email sent to {email}.", "success")
    except Exception as e:
        # Password is already reset; surface email issue to coach
        flash(f"Password reset, but email failed: {e}", "error")

    return redirect(url_for('athletes.athletes'))


def _none_if_empty(v):
    v = v.strip() if isinstance(v, str) else v
    return None if v in ("", None) else v

@athletes_bp.route('/athlete/<int:athlete_id>', methods=['GET', 'POST'], endpoint='athlete_detail')
@login_required
def athlete_detail(athlete_id):
    conn = get_db_connection()
    try:
        is_coach = bool(current_user.coach)

        with conn.cursor() as cur:
            if request.method == 'POST':
                # Always editable for both
                full_name = request.form.get('Full_Name', '').strip()
                initials  = request.form.get('Initials', '').strip()
                email     = _none_if_empty(request.form.get('Email', ''))
                dropbox   = _none_if_empty(request.form.get('DropBox', ''))
                max_hr    = _none_if_empty(request.form.get('Max_HR', ''))
                rest_hr   = _none_if_empty(request.form.get('Rest_HR', ''))
                if isinstance(max_hr, str) and max_hr.lstrip('-').isdigit(): max_hr = int(max_hr)
                if isinstance(rest_hr, str) and rest_hr.lstrip('-').isdigit(): rest_hr = int(rest_hr)

                cols = [
                    ("Full_Name", full_name),
                    ("Initials",  initials),
                    ("Email",     email),
                    ("DropBox",   dropbox),
                    ("Max_HR",    max_hr),
                    ("Rest_HR",   rest_hr),
                ]

                if is_coach:
                    # Coaches can also edit these, incl. Start_Rating
                    m_w    = request.form.get('M_W', '').strip()
                    side   = _none_if_empty(request.form.get('Side', ''))
                    joined = _none_if_empty(request.form.get('Joined', ''))
                    sculls = 1 if 'Sculls' in request.form else 0
                    cox    = 1 if 'Cox'    in request.form else 0
                    coach  = 1 if 'Coach'  in request.form else 0

                    start_rating = _none_if_empty(request.form.get('Start_Rating', ''))
                    if isinstance(start_rating, str) and start_rating.lstrip('-').isdigit():
                        start_rating = int(start_rating)

                    cols += [
                        ("M_W",          m_w),
                        ("Side",         side),
                        ("Joined",       joined),
                        ("Sculls",       sculls),
                        ("Cox",          cox),
                        ("Coach",        coach),
                        ("Start_Rating", start_rating),  # ✅ coach-only editable
                    ]

                set_clause = ", ".join([f"{c}=%s" for c,_ in cols])
                params = [v for _,v in cols] + [athlete_id]
                cur.execute(f"UPDATE Athletes SET {set_clause} WHERE Athlete_ID=%s", params)

                # Password change
                new_password = request.form.get('New_Password', '').strip()
                if new_password:
                    cur.execute(
                        "UPDATE Athletes SET Password_Hash=%s WHERE Athlete_ID=%s",
                        (generate_password_hash(new_password), athlete_id)
                    )

                conn.commit()
                flash("Athlete details updated.", "success")
                return redirect(url_for('athletes.athletes'))

            # GET
            cur.execute("SELECT * FROM Athletes WHERE Athlete_ID = %s", (athlete_id,))
            athlete = cur.fetchone()
            if not athlete:
                return "Athlete not found", 404

        # pass is_coach so the template can disable the field for athletes
        return render_template('athlete_detail.html', athlete=athlete, is_coach=is_coach)

    finally:
        conn.close()
