import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_concurrent_assignments_cannot_exceed_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.sqlite3"
            db = Database(path)
            db.add("terms", "학기")
            term_id = db.list("terms")[0][0]
            db.add("cohorts", "A반", term_id)
            db.add("subjects", "수학")
            db.add("teachers", "강사")
            cohort = db.list("cohorts", term_id)[0][0]
            subject = db.list("subjects")[0][0]
            teacher = db.list("teachers")[0][0]
            Schedule(db).save_quota(cohort, subject, 2, 2)
            db.conn.close()

            first_ready = threading.Event()
            release_first = threading.Event()
            second_attempt = threading.Event()
            second_done = threading.Event()
            results = []

            def assign(first):
                connection = Database(path)
                if first:
                    def before_insert(sql):
                        if sql.startswith("INSERT INTO lessons("):
                            first_ready.set()
                            release_first.wait(5)
                    connection.conn.set_trace_callback(before_insert)
                try:
                    if not first:
                        second_attempt.set()
                    Schedule(connection).assign(cohort, subject, teacher, None, 0, 1)
                    results.append("saved")
                except ValueError:
                    results.append("rejected")
                finally:
                    connection.conn.close()
                    if not first:
                        second_done.set()

            first = threading.Thread(target=assign, args=(True,))
            second = threading.Thread(target=assign, args=(False,))
            first.start()
            try:
                self.assertTrue(first_ready.wait(5))
                second.start()
                self.assertTrue(second_attempt.wait(5))
                self.assertFalse(second_done.wait(1), "두 번째 작성은 첫 트랜잭션이 끝날 때까지 기다려야 합니다.")
            finally:
                release_first.set()
                first.join(5)
                if second.ident is not None:
                    second.join(5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertCountEqual(results, ["saved", "rejected"])
            db = Database(path)
            self.assertEqual(len(Schedule(db).lessons(cohort)), 1)
            db.conn.close()

    def test_teacher_availability_and_atomic_changes(self):
        s = self.schedule
        self.assertEqual(s.availability(self.term, self.t1), [])
        s.set_availability(self.term, self.t1, {(0, 2), (2, 5)}, "UNAVAILABLE")
        with self.assertRaisesRegex(ValueError, "2교시"):
            s.assign(self.a, self.math, self.t1, None, 0, 1)
        self.assertEqual(s.lessons(self.a), [])
        s.set_availability(self.term, self.t1, {(0, 2)}, "UNSET")
        s.assign(self.a, self.math, self.t1, None, 0, 1)
        with self.assertRaisesRegex(ValueError, "이미 배정"):
            s.set_availability(self.term, self.t1, {(0, 2), (1, 3)}, "UNAVAILABLE")
        self.assertEqual(s.availability(self.term, self.t1), [(2, 5, "UNAVAILABLE")])
        s.set_availability(self.term, self.t1, {(0, 1), (0, 2)}, "AVAILABLE")
        self.assertEqual(len(s.availability(self.term, self.t1)), 3)
        self.db.add("terms", "다른 학기")
        other = next(row[0] for row in self.db.list("terms") if row[1] == "다른 학기")
        self.assertEqual(s.availability(other, self.t1), [])
        self.assertEqual(s.availability(self.term, self.t2), [])

    def test_existing_v2_lessons_survive_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            old = Database(path)
            old.add("terms", "기존 학기")
            term_id = old.list("terms")[0][0]
            old.add("cohorts", "기존 반", term_id)
            old.add("subjects", "수학")
            old.add("teachers", "강사")
            cohort = old.list("cohorts", term_id)[0][0]
            subject = old.list("subjects")[0][0]
            teacher = old.list("teachers")[0][0]
            Schedule(old).save_quota(cohort, subject, 2, 2)
            Schedule(old).assign(cohort, subject, teacher, None, 0, 1)
            old.conn.execute("DROP TABLE teacher_availability")
            old.conn.execute("PRAGMA user_version=2")
            old.conn.commit()
            old.conn.close()
            upgraded = Database(path)
            self.assertEqual(upgraded.conn.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(len(Schedule(upgraded).lessons(cohort)), 1)
            self.assertEqual(Schedule(upgraded).quotas(cohort)[0][4], 2)
            self.assertEqual(upgraded.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(upgraded.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            upgraded.conn.close()

    def test_concurrent_database_initialization_and_upgrade(self):
        for version in (0, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "shared.sqlite3"
                if version == 2:
                    previous = Database(path)
                    previous.add("terms", "기존 학기")
                    previous.conn.execute("DROP TABLE teacher_availability")
                    previous.conn.execute("PRAGMA user_version=2")
                    previous.conn.commit()
                    previous.conn.close()
                else:
                    sqlite3.connect(path).close()
                barrier = threading.Barrier(2, timeout=5)
                original_connect = sqlite3.connect

                class RacingConnection(sqlite3.Connection):
                    seen_version = False

                    def execute(self, sql, parameters=()):
                        cursor = super().execute(sql, parameters)
                        if sql == "PRAGMA user_version" and not self.seen_version:
                            self.seen_version = True
                            class RacingCursor:
                                def fetchone(self):
                                    result = cursor.fetchone()
                                    barrier.wait()
                                    return result
                            return RacingCursor()
                        return cursor

                def connect(*args, **kwargs):
                    return original_connect(*args, **kwargs, factory=RacingConnection)

                results = []
                def open_database():
                    try:
                        database = Database(path)
                        results.append(database.conn.execute("PRAGMA user_version").fetchone()[0])
                        database.conn.close()
                    except Exception as exc:
                        results.append(str(exc))
                with patch("academy_timetable.db.sqlite3.connect", side_effect=connect):
                    workers = [threading.Thread(target=open_database) for _ in range(2)]
                    for worker in workers:
                        worker.start()
                    for worker in workers:
                        worker.join(10)
                self.assertTrue(all(not worker.is_alive() for worker in workers))
                self.assertEqual(results, [3, 3])
                database = Database(path)
                if version == 2:
                    self.assertEqual(database.list("terms")[0][1], "기존 학기")
                self.assertEqual(database.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                database.conn.close()

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
            self.assertEqual(upgraded.conn.execute("PRAGMA user_version").fetchone()[0], 3)
            upgraded.conn.close()


if __name__ == "__main__":
    unittest.main()
