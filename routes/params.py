from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from functools import wraps
from db import get_db_connection

params_bp = Blueprint("params", __name__)

def coach_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        # Treat any truthy "Coach" as coach access
        if not getattr(current_user, "coach", False):
            abort(403)
        return view(*args, **kwargs)
    return wrapped

@params_bp.route("/params")
@coach_required
def list_params():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT Param, Value, COALESCE(Description,'') AS Description FROM Params ORDER BY Param")
            rows = cur.fetchall()
    finally:
        conn.close()
    return render_template("params_list.html", rows=rows)

@params_bp.route("/params/new", methods=["GET", "POST"])
@coach_required
def new_param():
    if request.method == "POST":
        param = (request.form.get("Param") or "").strip()
        value = (request.form.get("Value") or "").strip()
        desc  = (request.form.get("Description") or "").strip() or None

        if not param:
            flash("Param name is required.", "error")
            return redirect(url_for("params.new_param"))

        if len(param) > 20:
            flash("Param name must be ≤ 20 characters.", "error")
            return redirect(url_for("params.new_param"))

        if len(value) > 45:
            flash("Value must be ≤ 45 characters.", "error")
            return redirect(url_for("params.new_param"))

        if desc and len(desc) > 256:
            flash("Description must be ≤ 256 characters.", "error")
            return redirect(url_for("params.new_param"))

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO Params (Param, Value, Description) VALUES (%s, %s, %s)",
                    (param, value, desc)
                )
            conn.commit()
            flash(f"Parameter '{param}' created.", "success")
            return redirect(url_for("params.list_params"))
        except Exception as e:
            conn.rollback()
            flash(f"Could not create parameter: {e}", "error")
            return redirect(url_for("params.new_param"))
        finally:
            conn.close()

    return render_template("params_edit.html", mode="new", row={"Param": "", "Value": "", "Description": ""})

@params_bp.route("/params/edit/<param>", methods=["GET", "POST"])
@coach_required
def edit_param(param):
    param = (param or "").strip()
    conn = get_db_connection()
    try:
        if request.method == "POST":
            value = (request.form.get("Value") or "").strip()
            desc  = (request.form.get("Description") or "").strip() or None

            if len(value) > 45:
                flash("Value must be ≤ 45 characters.", "error")
                return redirect(url_for("params.edit_param", param=param))

            if desc and len(desc) > 256:
                flash("Description must be ≤ 256 characters.", "error")
                return redirect(url_for("params.edit_param", param=param))

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE Params SET Value=%s, Description=%s WHERE Param=%s",
                    (value, desc, param)
                )
            conn.commit()
            flash(f"Parameter '{param}' updated.", "success")
            return redirect(url_for("params.list_params"))

        # GET: fetch row
        with conn.cursor() as cur:
            cur.execute("SELECT Param, Value, COALESCE(Description,'') AS Description FROM Params WHERE Param=%s", (param,))
            row = cur.fetchone()
        if not row:
            abort(404)
        return render_template("params_edit.html", mode="edit", row=row)
    finally:
        conn.close()

@params_bp.route("/params/delete/<param>", methods=["POST"])
@coach_required
def delete_param(param):
    param = (param or "").strip()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM Params WHERE Param=%s", (param,))
        conn.commit()
        flash(f"Parameter '{param}' deleted.", "success")
    finally:
        conn.close()
    return redirect(url_for("params.list_params"))
