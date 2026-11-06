import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_PERIODS = (
    ("08:30", "09:20"), ("09:30", "10:20"), ("10:30", "11:20"),
    ("11:30", "12:20"), ("13:30", "14:20"), ("14:30", "15:20"),
    ("15:40", "16:30"), ("16:40", "17:30"), ("18:40", "19:30"),
    ("19:40", "20:30"), ("20:40", "21:30"),
)
TABLES = {"terms", "cohorts", "teachers", "subjects", "rooms"}
SCHEMA_VERSION = 5
CAPACITY_COLUMNS = {"cohorts": "student_count", "rooms": "capacity"}
FACILITY_COLUMNS = {"subjects": "required_facilities", "rooms": "facilities"}
MAX_CAPACITY = 2147483647


def facility_tags(text):
    tags = {}
    for field in text.replace(",", "\n").splitlines():
        name = field.strip()
        if name:
            tags.setdefault(name.casefold(), name)
    return tuple(tags.values())


def minutes(value):
    parts = value.split(":")
    if len(parts) != 2 or any(len(p) != 2 or not p.isascii() or not p.isdigit() for p in parts):
        raise ValueError("시간은 HH:MM 형식으로 입력하세요.")
    hour, minute = map(int, parts)
    if hour > 23 or minute > 59:
        raise ValueError("올바른 시간을 입력하세요.")
    return hour * 60 + minute


def validate_periods(periods):
    previous_end = -1
    for start, end in periods:
        start, end = minutes(start), minutes(end)
        if start >= end or start < previous_end:
            raise ValueError("각 교시의 시작은 종료보다 빨라야 하며 교시가 겹치거나 역순일 수 없습니다.")
        previous_end = end


class Database:
    def __init__(self, path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("이 프로그램보다 새로운 데이터베이스입니다.")
        if version < SCHEMA_VERSION:
            self.conn.execute("BEGIN IMMEDIATE")
            with self.conn:
                version = self.conn.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise RuntimeError("이 프로그램보다 새로운 데이터베이스입니다.")
                if version == 0:
                    self.conn.execute("CREATE TABLE terms (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
                    self.conn.execute("""CREATE TABLE periods (term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                        number INTEGER NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, PRIMARY KEY(term_id, number))""")
                    self.conn.execute("""CREATE TABLE cohorts (id INTEGER PRIMARY KEY, term_id INTEGER NOT NULL
                        REFERENCES terms(id) ON DELETE CASCADE, name TEXT NOT NULL, UNIQUE(term_id, name))""")
                    self.conn.execute("CREATE TABLE teachers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
                    self.conn.execute("CREATE TABLE subjects (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1)")
                    self.conn.execute("CREATE TABLE rooms (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
                if version < 2:
                    self.conn.execute("""CREATE TABLE quotas (
                        cohort_id INTEGER NOT NULL REFERENCES cohorts(id) ON DELETE RESTRICT,
                        subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
                        weekly_periods INTEGER NOT NULL CHECK(weekly_periods > 0 AND weekly_periods <= 55),
                        session_length INTEGER NOT NULL CHECK(session_length IN (1, 2)),
                        PRIMARY KEY(cohort_id, subject_id))""")
                    self.conn.execute("""CREATE TABLE lessons (
                        id INTEGER PRIMARY KEY,
                        cohort_id INTEGER NOT NULL REFERENCES cohorts(id) ON DELETE RESTRICT,
                        subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
                        teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
                        room_id INTEGER REFERENCES rooms(id) ON DELETE RESTRICT,
                        weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 4),
                        start_period INTEGER NOT NULL CHECK(start_period BETWEEN 1 AND 11),
                        length INTEGER NOT NULL CHECK(length IN (1, 2)),
                        locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0, 1)),
                        FOREIGN KEY(cohort_id, subject_id) REFERENCES quotas(cohort_id, subject_id) ON DELETE RESTRICT)""")
                if version < 3:
                    self.conn.execute("""CREATE TABLE teacher_availability (
                        term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                        teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
                        weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 4),
                        period INTEGER NOT NULL CHECK(period BETWEEN 1 AND 11),
                        status TEXT NOT NULL CHECK(status IN ('AVAILABLE', 'UNAVAILABLE')),
                        PRIMARY KEY(term_id, teacher_id, weekday, period))""")
                if version < 4:
                    for table, column in CAPACITY_COLUMNS.items():
                        self.conn.execute(f"""ALTER TABLE {table} ADD COLUMN {column} INTEGER
                            CHECK({column} IS NULL OR (typeof({column}) = 'integer' AND {column} BETWEEN 1 AND {MAX_CAPACITY}))""")
                if version < 5:
                    for table, column in FACILITY_COLUMNS.items():
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
                    if version in (3, 4):
                        self.advance_generation()
                    self.conn.execute("PRAGMA user_version = 5")
        self.restore_generation = self.conn.execute("PRAGMA application_id").fetchone()[0]

    def advance_generation(self):
        generation = (self.conn.execute("PRAGMA application_id").fetchone()[0] + 1) % 2147483647
        self.conn.execute(f"PRAGMA application_id = {generation}")
        return generation

    def assert_current(self):
        if self.conn.execute("PRAGMA application_id").fetchone()[0] != self.restore_generation:
            raise ValueError("다른 창에서 데이터를 복원하거나 저장 형식을 갱신했습니다. 프로그램을 다시 시작한 뒤 작업하세요.")

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        with self.conn:
            self.assert_current()
            yield

    def list(self, table, term_id=None):
        if table not in TABLES:
            raise ValueError("잘못된 항목입니다.")
        if table == "cohorts":
            return self.conn.execute("SELECT id, name FROM cohorts WHERE term_id = ? ORDER BY name", (term_id,)).fetchall()
        if table == "subjects":
            return self.conn.execute("SELECT id, name, active FROM subjects ORDER BY name").fetchall()
        return self.conn.execute(f"SELECT id, name FROM {table} ORDER BY name").fetchall()

    def add(self, table, name, term_id=None):
        if table not in TABLES or not name.strip():
            raise ValueError("이름을 입력하세요.")
        name = name.strip()
        with self.transaction():
            if table == "terms":
                term_id = self.conn.execute("INSERT INTO terms(name) VALUES (?)", (name,)).lastrowid
                self.conn.executemany("INSERT INTO periods VALUES (?, ?, ?, ?)",
                                      [(term_id, i, start, end) for i, (start, end) in enumerate(DEFAULT_PERIODS, 1)])
            elif table == "cohorts":
                if term_id is None:
                    raise ValueError("먼저 학기를 선택하세요.")
                self.conn.execute("INSERT INTO cohorts(term_id, name) VALUES (?, ?)", (term_id, name))
            else:
                self.conn.execute(f"INSERT INTO {table}(name) VALUES (?)", (name,))

    def rename(self, table, row_id, name):
        if table not in TABLES or not name.strip():
            raise ValueError("이름을 입력하세요.")
        with self.transaction():
            self.conn.execute(f"UPDATE {table} SET name = ? WHERE id = ?", (name.strip(), row_id))

    def remove(self, table, row_id):
        if table not in TABLES:
            raise ValueError("잘못된 항목입니다.")
        with self.transaction():
            if table == "subjects":
                self.conn.execute("UPDATE subjects SET active = 1 - active WHERE id = ?", (row_id,))
            else:
                self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    def capacity_values(self, table):
        column = CAPACITY_COLUMNS[table]
        return dict(self.conn.execute(f"SELECT id, {column} FROM {table}"))

    def set_capacity(self, table, row_id, value):
        column = CAPACITY_COLUMNS[table]
        if value is not None and (type(value) is not int or not 1 <= value <= MAX_CAPACITY):
            raise ValueError("입력 가능한 양의 정수를 선택하거나 미설정으로 두세요.")
        with self.transaction():
            result = self.conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (value, row_id))
            if result.rowcount != 1:
                raise ValueError("선택한 항목을 찾을 수 없습니다.")

    def facility_values(self, table):
        column = FACILITY_COLUMNS[table]
        return dict(self.conn.execute(f"SELECT id, {column} FROM {table}"))

    def set_facilities(self, table, row_id, text):
        column = FACILITY_COLUMNS[table]
        with self.transaction():
            value = "\n".join(facility_tags(text))
            result = self.conn.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (value, row_id))
            if result.rowcount != 1:
                raise ValueError("선택한 항목을 찾을 수 없습니다.")

    def periods(self, term_id):
        return self.conn.execute("SELECT start, end FROM periods WHERE term_id = ? ORDER BY number", (term_id,)).fetchall()

    def save_periods(self, term_id, periods):
        if term_id is None or len(periods) != 11:
            raise ValueError("학기와 11개 교시를 확인하세요.")
        validate_periods(periods)
        with self.transaction():
            if self.conn.execute("SELECT count(*) FROM periods WHERE term_id = ?", (term_id,)).fetchone()[0] != 11:
                raise ValueError("학기의 교시표를 찾을 수 없습니다.")
            self.conn.executemany("UPDATE periods SET start = ?, end = ? WHERE term_id = ? AND number = ?",
                                  [(start, end, term_id, i) for i, (start, end) in enumerate(periods, 1)])
