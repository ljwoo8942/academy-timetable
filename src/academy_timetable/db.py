import sqlite3
from contextlib import contextmanager
from pathlib import Path

DAYS = ("월", "화", "수", "목", "금", "토")
DEFAULT_PERIODS = (
    ("08:30", "09:20"), ("09:30", "10:20"), ("10:30", "11:20"),
    ("11:30", "12:20"), ("13:30", "14:20"), ("14:30", "15:20"),
    ("15:40", "16:30"), ("16:40", "17:30"), ("18:40", "19:30"),
    ("19:40", "20:30"), ("20:40", "21:30"),
)
TABLES = {"terms", "cohorts", "teachers", "subjects", "rooms", "subject_areas"}
SCHEMA_VERSION = 8
CAPACITY_COLUMNS = {"cohorts": "student_count", "rooms": "capacity"}
FACILITY_COLUMNS = {"subjects": "required_facilities", "rooms": "facilities"}
MAX_CAPACITY = 2147483647


LESSONS_SCHEMA = """CREATE TABLE {table} (
    id INTEGER PRIMARY KEY,
    cohort_id INTEGER NOT NULL REFERENCES cohorts(id) ON DELETE RESTRICT,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    room_id INTEGER REFERENCES rooms(id) ON DELETE RESTRICT,
    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 5),
    start_period INTEGER NOT NULL CHECK(start_period BETWEEN 1 AND 11),
    length INTEGER NOT NULL CHECK(length IN (1, 2)),
    locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0, 1)),
    FOREIGN KEY(cohort_id, subject_id) REFERENCES quotas(cohort_id, subject_id) ON DELETE RESTRICT)"""

AVAILABILITY_SCHEMA = """CREATE TABLE {table} (
    term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 5),
    period INTEGER NOT NULL CHECK(period BETWEEN 1 AND 11),
    status TEXT NOT NULL CHECK(status IN ('AVAILABLE', 'UNAVAILABLE')),
    PRIMARY KEY(term_id, teacher_id, weekday, period))"""


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
                    self.conn.execute(LESSONS_SCHEMA.format(table="lessons"))
                if version < 3:
                    self.conn.execute(AVAILABILITY_SCHEMA.format(table="teacher_availability"))
                if version < 4:
                    for table, column in CAPACITY_COLUMNS.items():
                        self.conn.execute(f"""ALTER TABLE {table} ADD COLUMN {column} INTEGER
                            CHECK({column} IS NULL OR (typeof({column}) = 'integer' AND {column} BETWEEN 1 AND {MAX_CAPACITY}))""")
                if version < 5:
                    for table, column in FACILITY_COLUMNS.items():
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
                if version < 6:
                    self.conn.execute("""CREATE TABLE teacher_subjects (
                        subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                        teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
                        PRIMARY KEY(subject_id, teacher_id))""")
                if version < 7:
                    for minimum, table, schema in (
                        (2, "lessons", LESSONS_SCHEMA), (3, "teacher_availability", AVAILABILITY_SCHEMA)
                    ):
                        if version >= minimum:
                            replacement = f"{table}_new"
                            self.conn.execute(schema.format(table=replacement))
                            self.conn.execute(f"INSERT INTO {replacement} SELECT * FROM {table}")
                            self.conn.execute(f"DROP TABLE {table}")
                            self.conn.execute(f"ALTER TABLE {replacement} RENAME TO {table}")
                    if version >= 3:
                        self.advance_generation()
                if version < 8:
                    self.conn.execute("CREATE TABLE subject_areas (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
                    self.conn.execute("ALTER TABLE subjects ADD COLUMN area_id INTEGER REFERENCES subject_areas(id) ON DELETE RESTRICT")
                    self.conn.execute("""CREATE TABLE cohort_scopes (
                        cohort_id INTEGER PRIMARY KEY REFERENCES cohorts(id) ON DELETE CASCADE,
                        area_id INTEGER REFERENCES subject_areas(id) ON DELETE RESTRICT,
                        subject_id INTEGER REFERENCES subjects(id) ON DELETE RESTRICT,
                        CHECK((area_id IS NOT NULL) != (subject_id IS NOT NULL)))""")
                    if version >= 7:
                        self.advance_generation()
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
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

    def eligible_teachers(self, subject_id):
        return {row[0] for row in self.conn.execute(
            "SELECT teacher_id FROM teacher_subjects WHERE subject_id=?", (subject_id,)
        )}

    def _area_id(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("교과 이름을 입력하세요.")
        name = name.strip()
        self.conn.execute("INSERT OR IGNORE INTO subject_areas(name) VALUES (?)", (name,))
        return self.conn.execute("SELECT id FROM subject_areas WHERE name=?", (name,)).fetchone()[0]

    def subject_area(self, subject_id):
        row = self.conn.execute("""SELECT a.name FROM subjects s
            LEFT JOIN subject_areas a ON a.id=s.area_id WHERE s.id=?""", (subject_id,)).fetchone()
        return row[0] if row else None

    def set_subject_area(self, subject_id, name):
        with self.transaction():
            self._set_subject_area(subject_id, name)

    def _set_subject_area(self, subject_id, name):
        if not self.conn.execute("SELECT 1 FROM subjects WHERE id=?", (subject_id,)).fetchone():
            raise ValueError("과목을 찾을 수 없습니다.")
        area_id = self._area_id(name) if name else None
        if self.conn.execute("""SELECT 1 FROM quotas q JOIN cohort_scopes cs ON cs.cohort_id=q.cohort_id
            WHERE q.subject_id=? AND cs.area_id IS NOT NULL AND cs.area_id IS NOT ? LIMIT 1""",
                             (subject_id, area_id)).fetchone():
            raise ValueError("이 과목을 사용하는 교과 반의 기존 시수를 먼저 조정하세요.")
        self.conn.execute("UPDATE subjects SET area_id=? WHERE id=?", (area_id, subject_id))

    def cohort_scope(self, cohort_id):
        row = self.conn.execute("""SELECT cs.area_id, a.name, s.name FROM cohort_scopes cs
            LEFT JOIN subject_areas a ON a.id=cs.area_id LEFT JOIN subjects s ON s.id=cs.subject_id
            WHERE cs.cohort_id=?""", (cohort_id,)).fetchone()
        return ("COMMON", None) if row is None else ("AREA", row[1]) if row[0] is not None else ("SUBJECT", row[2])

    def allowed_subject_ids(self, cohort_id):
        row = self.conn.execute("SELECT area_id,subject_id FROM cohort_scopes WHERE cohort_id=?", (cohort_id,)).fetchone()
        if row is None:
            return None
        if row[1] is not None:
            return {row[1]}
        return {subject_id for subject_id, in self.conn.execute("SELECT id FROM subjects WHERE area_id=?", (row[0],))}

    def validate_cohort_subject(self, cohort_id, subject_id):
        allowed = self.allowed_subject_ids(cohort_id)
        if allowed is not None and subject_id not in allowed:
            raise ValueError("반 기준에 맞는 교과 또는 등록 과목만 배정할 수 있습니다.")

    def _set_cohort_scope(self, cohort_id, kind, target):
        area_id = subject_id = None
        if kind == "AREA":
            area_id = self._area_id(target)
            allowed = {row[0] for row in self.conn.execute("SELECT id FROM subjects WHERE area_id=?", (area_id,))}
        elif kind == "SUBJECT":
            row = self.conn.execute("SELECT id FROM subjects WHERE name=?", (target,)).fetchone()
            if row is None:
                raise ValueError("반 기준으로 사용할 등록 과목을 선택하세요.")
            subject_id = row[0]
            allowed = {subject_id}
        elif kind == "COMMON":
            self.conn.execute("DELETE FROM cohort_scopes WHERE cohort_id=?", (cohort_id,))
            return
        else:
            raise ValueError("반 구분을 선택하세요.")
        if any(row[0] not in allowed for row in self.conn.execute("SELECT subject_id FROM quotas WHERE cohort_id=?", (cohort_id,))):
            raise ValueError("기존 시수에 새 반 기준과 맞지 않는 과목이 있습니다. 시수를 먼저 조정하세요.")
        self.conn.execute("""INSERT INTO cohort_scopes VALUES (?,?,?) ON CONFLICT(cohort_id)
            DO UPDATE SET area_id=excluded.area_id,subject_id=excluded.subject_id""", (cohort_id, area_id, subject_id))

    def save_cohort(self, term_id, name, kind, target, *, cohort_id=None, expected=None):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("국어 A, 수학 A처럼 반 이름을 입력하세요.")
        with self.transaction():
            if cohort_id is None:
                cohort_id = self.conn.execute("INSERT INTO cohorts(term_id,name) VALUES (?,?)", (term_id, name.strip())).lastrowid
            else:
                row = self.conn.execute("SELECT name FROM cohorts WHERE id=? AND term_id=?", (cohort_id, term_id)).fetchone()
                if row is None:
                    raise ValueError("반을 찾을 수 없습니다.")
                if expected is not None and (row[0], *self.cohort_scope(cohort_id)) != expected:
                    raise ValueError("반 설정이 변경되었습니다. 다시 열어 확인하세요.")
                self.conn.execute("UPDATE cohorts SET name=? WHERE id=?", (name.strip(), cohort_id))
            self._set_cohort_scope(cohort_id, kind, target)
        return cohort_id

    def set_eligible_teachers(self, subject_id, teacher_ids, *, expected):
        selected = set(teacher_ids)
        with self.transaction():
            if not self.conn.execute("SELECT 1 FROM subjects WHERE id=?", (subject_id,)).fetchone():
                raise ValueError("선택한 과목을 찾을 수 없습니다.")
            current = self.eligible_teachers(subject_id)
            if current != expected:
                raise ValueError("담당 강사 설정이 변경되었습니다. 목록을 다시 열어 확인하세요.")
            if not selected.issubset(teacher_id for teacher_id, _ in self.list("teachers")):
                raise ValueError("선택한 강사를 찾을 수 없습니다. 목록을 다시 열어 확인하세요.")
            self.conn.execute("DELETE FROM teacher_subjects WHERE subject_id=?", (subject_id,))
            self.conn.executemany("INSERT INTO teacher_subjects(subject_id, teacher_id) VALUES (?, ?)",
                                  ((subject_id, teacher_id) for teacher_id in selected))

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
