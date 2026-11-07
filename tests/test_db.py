import sqlite3
import tempfile
import unittest
from pathlib import Path

from academy_timetable.db import Database, DEFAULT_PERIODS, validate_periods
from legacy_db import make_legacy_fixture


class DatabaseTests(unittest.TestCase):
    def test_term_defaults_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.sqlite3"
            db = Database(path)
            db.add("terms", "2026 학기")
            term_id = db.list("terms")[0][0]
            self.assertEqual(db.periods(term_id), list(DEFAULT_PERIODS))
            db.add("cohorts", "A반", term_id)
            db.add("subjects", "국어")
            subject_id = db.list("subjects")[0][0]
            db.remove("subjects", subject_id)
            self.assertEqual(db.list("subjects")[0][2], 0)
            db.conn.close()
            db = Database(path)
            self.assertEqual(db.list("cohorts", term_id)[0][1], "A반")
            self.assertEqual(db.list("subjects")[0][2], 0)
            db.conn.close()

    def test_invalid_periods_never_replace_saved_values(self):
        db = Database(":memory:")
        db.add("terms", "학기")
        term_id = db.list("terms")[0][0]
        for bad in (("09:30", "08:30"), ("09:10", "10:20"), ("24:00", "24:30"), ("9:30", "10:20")):
            periods = list(DEFAULT_PERIODS)
            periods[1] = bad
            with self.assertRaises(ValueError):
                db.save_periods(term_id, periods)
            self.assertEqual(db.periods(term_id), list(DEFAULT_PERIODS))
        periods = list(DEFAULT_PERIODS)
        periods[0] = ("08:20", "09:20")
        db.save_periods(term_id, periods)
        self.assertEqual(db.periods(term_id), periods)
        db.conn.close()

    def test_names_and_cascade(self):
        db = Database(":memory:")
        db.add("terms", "학기")
        term_id = db.list("terms")[0][0]
        with self.assertRaises(sqlite3.IntegrityError):
            db.add("terms", "학기")
        with self.assertRaises(ValueError):
            db.add("cohorts", " ", term_id)
        db.add("cohorts", "A반", term_id)
        db.remove("terms", term_id)
        self.assertEqual(db.periods(term_id), [])
        self.assertEqual(db.list("cohorts", term_id), [])
        db.conn.close()

    def test_version_three_upgrade_preserves_rooms_and_invalidates_old_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.sqlite3"
            old = Database(path)
            old.add("rooms", "101호")
            room = old.list("rooms")[0][0]
            make_legacy_fixture(old.conn, 3)
            updated = Database(path)
            self.assertEqual(updated.list("rooms"), [(room, "101호")])
            self.assertIsNone(updated.capacity_values("rooms")[room])
            with self.assertRaisesRegex(ValueError, "저장 형식을 갱신"):
                old.rename("rooms", room, "바뀐 이름")
            updated.conn.close()
            old.conn.close()

    def test_version_five_upgrade_and_teacher_subject_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.sqlite3"
            old = Database(path)
            old.add("subjects", "수학")
            old.add("teachers", "김강사")
            subject = old.list("subjects")[0][0]
            teacher = old.list("teachers")[0][0]
            old.set_facilities("subjects", subject, "빔프로젝터")
            make_legacy_fixture(old.conn, 5)
            db = Database(path)
            self.assertEqual(db.facility_values("subjects")[subject], "빔프로젝터")
            self.assertEqual(db.eligible_teachers(subject), set())
            with self.assertRaisesRegex(ValueError, "저장 형식을 갱신"):
                old.rename("teachers", teacher, "바뀐 이름")
            db.set_eligible_teachers(subject, {teacher}, expected=set())
            with self.assertRaisesRegex(ValueError, "설정이 변경"):
                db.set_eligible_teachers(subject, set(), expected=set())
            with self.assertRaisesRegex(ValueError, "강사를 찾을 수 없"):
                db.set_eligible_teachers(subject, {teacher + 1}, expected={teacher})
            self.assertEqual(db.eligible_teachers(subject), {teacher})
            db.remove("teachers", teacher)
            self.assertEqual(db.eligible_teachers(subject), set())
            db.conn.close()
            old.conn.close()


if __name__ == "__main__":
    unittest.main()
