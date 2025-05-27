import pymysql

# DB config
db_config = {
    'host': 'eubcdb-2.cp6ymm2sk6ub.eu-west-2.rds.amazonaws.com',
    'user': 'admin',
    'password': 'Flockhart',
    'database': 'eubcdb',
    'cursorclass': pymysql.cursors.DictCursor
}

def set_t2_minutes():
    conn = pymysql.connect(**db_config)
    with conn.cursor() as cursor:
        # Get all athletes who don't yet have a password
        cursor.execute("SELECT * FROM Sessions")
        sessions = cursor.fetchall()

        s_count = 0

        for session in sessions:
            s_count +=1
            activity = session['Activity']
            duration = session['Duration']

            t2_min = duration.total_seconds()/60

            if activity == "Water":
                t2_min = t2_min * 1
            elif activity == "Erg":
                t2_min = t2_min * 1.35
            elif activity == "Static Bike":
                t2_min = t2_min * 0.95
            elif activity == "Road Bike":
                t2_min = t2_min * 0.8
            elif activity == "Run":
                t2_min = t2_min * 1.4
            elif activity == "Swim":
                t2_min = t2_min * 1.2
            elif activity == "Brisk Walk":
                t2_min = t2_min * 0.5
            else:
                t2_min = t2_min * 0.6

            # Update database with the hashed password
            cursor.execute(
                "UPDATE Sessions SET T2_Minutes = %s WHERE Session_ID = %s",
                (t2_min, session['Session_ID'])
            )

            if s_count % 500 == 0:
                print(s_count)

        conn.commit()
    conn.close()

if __name__ == "__main__":
    set_t2_minutes()
