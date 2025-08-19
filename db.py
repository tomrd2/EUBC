import pymysql
from types import SimpleNamespace

# Central DB config
# We can also place sensitive db credentials in a .env file and load them using dotenv
db_config = {
    'host': 'eubcdb-2.cp6ymm2sk6ub.eu-west-2.rds.amazonaws.com',
    'user': 'admin',
    'password': 'Flockhart',
    'database': 'eubcdb',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_db_connection():
    return pymysql.connect(**db_config)

def get_param(name: str, default=None):
    """
    Fetch a parameter by name from Params and return an object with a `.value` attribute.
    Usage:
        foo = get_param("Foo").value
        bar = get_param("Missing", default="fallback").value
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT Value FROM Params WHERE Param = %s", (name,))
            row = cur.fetchone()
            if row is not None and 'Value' in row:
                return SimpleNamespace(value=row['Value'])
            return SimpleNamespace(value=default)
    finally:
        conn.close()

def get_param_int(name, default=None):
    v = get_param(name, default).value
    try: return int(v) if v is not None else default
    except (TypeError, ValueError): return default

def get_param_bool(name, default=None):
    v = str(get_param(name, default).value).strip().lower()
    if v in ("1","true","yes","on"): return True
    if v in ("0","false","no","off"): return False
    return default