import sqlite3
import tempfile
import unittest
from pathlib import Path

from academy_timetable.db import Database
from academy_timetable.schedule import Schedule


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.db.add("terms", "학기")
        self.term = self.db.list("terms")[0][0]
        for name in ("A반", "B반"):
            self.db.add("cohorts", name, self.term)
        self.a, self.b = [row[0] for row in self.db.list("cohorts", self.term)]
        for table, names in (("subjects", ("수학", "영어")), ("teachers", ("김", "이")), ("rooms", ("101", "102"))):
            for name in names:
                self.db.add(table, name)
        self.math, self.english = [row[0] for row in self.db.list("subjects")]
        self.t1, self.t2 = [row[0] for row in self.db.list("teachers")]
        self.r1, self.r2 = [row[0] for row in self.db.list("rooms")]
        self.schedule = Schedule(self.db)
        self.schedule.save_quota(self.a, self.math, 4, 2)
        self.schedule.save_quota(self.b, self.english, 2, 1)

    def tearDown(self):
        self.db.conn.close()

    def test_conflicts_and_boundaries_and_move(self):
        s = self.schedule
        s.assign(self.a, self.math, self.t1, self.r1, 0, 1)
        first = s.lessons(self.a)[0][0]
        for teacher, room in ((self.t1, self.r2), (self.t2, self.r1)):
            with self.assertRaisesRegex(ValueError, "중복"):
                s.assign(self.b, self.english, teacher, room, 0, 2)
        with self.assertRaisesRegex(ValueError, "반 중복"):
            s.assign(self.a, self.math, self.t2, self.r2, 0, 2)
        for start in (4, 8, 11):
            with self.assertRaises(ValueError):
                s.assign(self.a, self.math, self.t1, None, 1, start)
        s.assign(self.a, self.math, self.t1, self.r1, 0, 6, first)
        self.assertEqual(s.lessons(self.a)[0][2:4], (6, 2))
        s.assign(self.b, self.english, self.t1, self.r1, 0, 1)
        self.assertEqual(s.quotas(self.a)[0][4], 2)

    def test_quota_lock_and_restrict_delete(self):
        s = self.schedule
        with self.assertRaises(ValueError):
            s.save_quota(self.a, self.math, 3, 2)
        s.assign(self.a, self.math, self.t1, None, 0, 1)
        entry = s.lessons(self.a)[0][0]
        s.lock(entry, True)
        with self.assertRaisesRegex(ValueError, "잠금"):
            s.delete(entry)
        with self.assertRaisesRegex(ValueError, "잠금"):
            s.assign(self.a, self.math, self.t1, None, 1, 1, entry)
        with self.assertRaises(ValueError):
            s.save_quota(self.a, self.math, 1, 1)
        with self.assertRaises(ValueError):
            s.delete_quota(self.a, self.math)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.remove("teachers", self.t1)
        s.lock(entry, False)
        s.delete(entry)
        s.delete_quota(self.a, self.math)
        self.assertEqual(s.lessons(self.a), [])

    def test_failed_move_preserves_original_and_weekly_limit(self):
        s = self.schedule
        s.assign(self.a, self.math, self.t1, None, 0, 1)
        first = s.lessons(self.a)[0][0]
        s.assign(self.a, self.math, self.t1, None, 1, 1)
        s.assign(self.b, self.english, self.t2, None, 2, 1)
        with self.assertRaisesRegex(ValueError, "강사 중복"):
            s.assign(self.a, self.math, self.t2, None, 2, 1, first)
        self.assertEqual(s.lessons(self.a)[0][1:4], (0, 1, 2))
        with self.assertRaisesRegex(ValueError, "초과"):
            s.assign(self.a, self.math, self.t1, None, 3, 1)
        self.assertEqual(s.teacher_loads(self.term), [(self.t1, self.math, 4), (self.t2, self.english, 1)])

    def test_existing_v1_database_is_preserved_on_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            old = sqlite3.connect(path)
            old.executescript("""CREATE TABLE terms(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
                CREATE TABLE periods(term_id INTEGER,number INTEGER,start TEXT,end TEXT,PRIMARY KEY(term_id,number));
                CREATE TABLE cohorts(id INTEGER PRIMARY KEY,term_id INTEGER,name TEXT);
                CREATE TABLE subjects(id INTEGER PRIMARY KEY,name TEXT,active INTEGER);
                CREATE TABLE teachers(id INTEGER PRIMARY KEY,name TEXT);
                CREATE TABLE rooms(id INTEGER PRIMARY KEY,name TEXT);
                INSERT INTO terms VALUES(1,'기존 학기'); INSERT INTO cohorts VALUES(1,1,'기존 반');
                PRAGMA user_version=1;""")
            old.close()
            upgraded = Database(path)
            self.assertEqual(upgraded.list("terms"), [(1, "기존 학기")])
            self.assertEqual(upgraded.list("cohorts", 1), [(1, "기존 반")])
            self.assertEqual(upgraded.conn.execute("PRAGMA user_version").fetchone()[0], 2)
            upgraded.conn.close()


if __name__ == "__main__":
    unittest.main()
