def make_legacy_fixture(connection, version):
    """보존할 행은 남기고 현재 테스트 DB를 이전 열 구성으로 되돌린다."""
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("BEGIN")
    with connection:
        capacity_column = ", capacity INTEGER" if version == 4 else ""
        room_columns = "id, name, capacity" if version == 4 else "id, name"
        connection.execute(f"CREATE TABLE old_rooms (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE{capacity_column})")
        connection.execute(f"INSERT INTO old_rooms SELECT {room_columns} FROM rooms")
        connection.execute("DROP TABLE rooms")
        connection.execute("ALTER TABLE old_rooms RENAME TO rooms")
        connection.execute("CREATE TABLE old_subjects (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1)")
        connection.execute("INSERT INTO old_subjects SELECT id,name,active FROM subjects")
        connection.execute("DROP TABLE subjects")
        connection.execute("ALTER TABLE old_subjects RENAME TO subjects")
        if version <= 3:
            connection.execute("""CREATE TABLE old_cohorts (id INTEGER PRIMARY KEY, term_id INTEGER NOT NULL
                REFERENCES terms(id) ON DELETE CASCADE, name TEXT NOT NULL, UNIQUE(term_id, name))""")
            connection.execute("INSERT INTO old_cohorts SELECT id,term_id,name FROM cohorts")
            connection.execute("DROP TABLE cohorts")
            connection.execute("ALTER TABLE old_cohorts RENAME TO cohorts")
        if version == 2:
            connection.execute("DROP TABLE teacher_availability")
        connection.execute(f"PRAGMA user_version = {version}")
    connection.execute("PRAGMA foreign_keys = ON")
