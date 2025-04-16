import pymysql
from werkzeug.security import generate_password_hash

# DB config
db_config = {
    'host': 'eubcdb-2.cp6ymm2sk6ub.eu-west-2.rds.amazonaws.com',
    'user': 'admin',
    'password': 'Flockhart',
    'database': 'eubcdb',
    'cursorclass': pymysql.cursors.DictCursor
}

def set_default_passwords():
    conn = pymysql.connect(**db_config)
    with conn.cursor() as cursor:
        # Get all athletes who don't yet have a password
        cursor.execute("SELECT Athlete_ID, Initials FROM Athletes")
        athletes = cursor.fetchall()

        for athlete in athletes:
            athlete_id = athlete['Athlete_ID']
            initials = athlete['Initials']

            # You can choose your default password pattern here
            default_password = f"{initials.lower()}_eubc"  # e.g., "jd_123"
            hashed = generate_password_hash(default_password)

            # Update database with the hashed password
            cursor.execute(
                "UPDATE Athletes SET Password_Hash = %s WHERE Athlete_ID = %s",
                (hashed, athlete_id)
            )
            print(f"Set password for Athlete_ID {athlete_id} to '{default_password}'")

        conn.commit()
    conn.close()

if __name__ == "__main__":
    set_default_passwords()
