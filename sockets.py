# sockets.py
from flask_socketio import SocketIO, emit, join_room
from flask_login import current_user
from flask import current_app, g, session as sock_session
from db import get_db_connection, tenant_context

# Reuse Flask session for Flask-Login
socketio = SocketIO(logger=True, engineio_logger=True)  # 👈 verbose logs

def _require_tenant(payload_club=None):
    """Figure out the tenant key for this socket, preferring the socket session."""
    tenant = (
        sock_session.get("tenant_key")
        or payload_club
        or getattr(current_user, "tenant_key", None)
        or getattr(g, "tenant_key", None)
    )
    return (tenant or "").strip().lower() or None

def _outing_room(tenant: str, outing_id: int) -> str:
    return f"outing_{tenant}_{outing_id}"

def _piece_room(tenant: str, piece_id: int) -> str:
    return f"piece_{tenant}_{piece_id}"


@socketio.on("join_piece")
def sio_join_piece(data):
    piece_id = data.get("piece_id")
    tenant = _require_tenant(data.get("club"))
    if not tenant or not piece_id:
        return
    sock_session["tenant_key"] = tenant
    join_room(_piece_room(tenant, piece_id))

@socketio.on("result_update")
def sio_result_update(data):
    if not current_user.is_authenticated or not current_user.coach:
        return

    tenant   = _require_tenant()
    piece_id = data.get("piece_id")
    crew_id  = data.get("crew_id")
    field    = data.get("field")
    value    = data.get("value")

    if not tenant or piece_id is None or crew_id is None or not field:
        return

    with tenant_context(current_app, tenant):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"UPDATE Results SET {field}=%s WHERE Piece_ID=%s AND Crew_ID=%s",
                               (value, piece_id, crew_id))
            conn.commit()
        finally:
            conn.close()

    emit("result_updated", {
        "piece_id": piece_id, "crew_id": crew_id, "field": field, "value": value
    }, room=_piece_room(tenant, piece_id), include_self=False)
