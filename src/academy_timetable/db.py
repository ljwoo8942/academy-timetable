import sqlite3
from pathlib import Path

DEFAULT_PERIODS = (
    ("08:30", "09:20"), ("09:30", "10:20"), ("10:30", "11:20"),
    ("11:30", "12:20"), ("13:30", "14:20"), ("14:30", "15:20"),
    ("15:40", "16:30"), ("16:40", "17:30"), ("18:40", "19:30"),
    ("19:40", "20:30"), ("20:40", "21:30"),
)
TABLES = {"terms", "cohorts", "teachers", "subjects", "rooms"}


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
        if version > 1:
            raise RuntimeError("이 프로그램보다 새로운 데이터베이스입니다.")
        if version == 0:
            self.conn.executescript("""
                CREATE TABLE terms (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE periods (term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                    PRIMARY KEY(term_id, number));
                CREATE TABLE cohorts (id INTEGER PRIMARY KEY, term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, UNIQUE(term_id, name));
                CREATE TABLE teachers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE subjects (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE rooms (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                PRAGMA user_version = 1;
            """)

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
        with self.conn:
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
        with self.conn:
            self.conn.execute(f"UPDATE {table} SET name = ? WHERE id = ?", (name.strip(), row_id))

    def remove(self, table, row_id):
        if table not in TABLES:
            raise ValueError("잘못된 항목입니다.")
        with self.conn:
            if table == "subjects":
                self.conn.execute("UPDATE subjects SET active = 1 - active WHERE id = ?", (row_id,))
            else:
                self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    def periods(self, term_id):
        return self.conn.execute("SELECT start, end FROM periods WHERE term_id = ? ORDER BY number", (term_id,)).fetchall()

    def save_periods(self, term_id, periods):
        if term_id is None or len(periods) != 11:
            raise ValueError("학기와 11개 교시를 확인하세요.")
        validate_periods(periods)
        with self.conn:
            if self.conn.execute("SELECT count(*) FROM periods WHERE term_id = ?", (term_id,)).fetchone()[0] != 11:
                raise ValueError("학기의 교시표를 찾을 수 없습니다.")
            self.conn.executemany("UPDATE periods SET start = ?, end = ? WHERE term_id = ? AND number = ?",
                                  [(start, end, term_id, i) for i, (start, end) in enumerate(periods, 1)])
