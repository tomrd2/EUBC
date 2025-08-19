# db.py
import pymysql
from types import SimpleNamespace
from contextlib import contextmanager
from contextvars import ContextVar
from flask import g, has_request_context, current_app

# For background jobs (no request), we store the active tenant in a contextvar.
_active_tenant: ContextVar | None = ContextVar("_active_tenant", default=None)  # type: ignore[assignment]

def _get_active_tenant():
    """
    Get the active tenant dict either from Flask's request context (g.tenant)
    or from a contextvar set by tenant_context() for background jobs.
    """
    if has_request_context() and hasattr(g, "tenant"):
        return g.tenant

    if _active_tenant is not None:
        t = _active_tenant.get()
        if t:
            return t

    raise RuntimeError(
        "No active tenant bound. In web requests ensure routes are under '/<club>' "
        "and your url_value_preprocessor sets g.tenant. For background jobs, wrap the "
        "work with tenant_context(app, '<club>')."
    )

def _get_tenant_db_config():
    tenant = _get_active_tenant()
    cfg = (tenant or {}).get("db") or {}
    required = ("host", "user", "password", "database")
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        # Try to show which tenant failed, if available
        key = getattr(g, 'tenant_key', None) if has_request_context() else "<no-request>"
        raise RuntimeError(f"Tenant DB config missing keys {missing} for tenant '{key}'.")
    return {
        "host": cfg["host"],
        "user": cfg["user"],
        "password": cfg["password"],
        "database": cfg["database"],
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 5,
        "read_timeout": 15,
        "write_timeout": 15,
    }

def get_db_connection():
    """Return a new PyMySQL connection for the active tenant."""
    return pymysql.connect(**_get_tenant_db_config())

def get_param(name: str, default=None):
    """
    Fetch a parameter by name from Params and return an object with `.value`.
    Usage: foo = get_param("Foo").value
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT Value FROM Params WHERE Param = %s", (name,))
            row = cur.fetchone()
            if row is not None and "Value" in row:
                return SimpleNamespace(value=row["Value"])
            return SimpleNamespace(value=default)
    finally:
        conn.close()

def get_param_int(name, default=None):
    v = get_param(name, default).value
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default

def get_param_bool(name, default=None):
    v = str(get_param(name, default).value).strip().lower()
    if v in ("1","true","yes","on"): return True
    if v in ("0","false","no","off"): return False
    return default

# -------- Background jobs helper --------
@contextmanager
def tenant_context(app, tenant_key: str):
    """
    Use in cron/CLI tasks where there's no request.
    Example:
        from run import app
        from db import tenant_context, get_param
        with app.app_context():
            with tenant_context(app, 'sabc'):
                print(get_param('ClubTitle').value)
    """
    if app is None:
        raise RuntimeError("tenant_context requires the Flask app instance")
    tenants = app.config.get("TENANTS", {}) or {}
    key = (tenant_key or "").strip().lower()
    tenant = tenants.get(key)
    if not tenant:
        raise RuntimeError(f"Unknown tenant '{tenant_key}'. Available: {list(tenants.keys())}")

    token = _active_tenant.set(tenant)
    try:
        yield
    finally:
        _active_tenant.reset(token)
