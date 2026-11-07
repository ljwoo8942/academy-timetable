import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from academy_timetable.backup import backup_to, restore_from
from academy_timetable.db import Database, SCHEMA_VERSION
from academy_timetable.schedule import Schedule
from legacy_db import make_legacy_fixture


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "current.sqlite3"
        self.backup = Path(self.tmp.name) / "backup.sqlite3"
        self.db = Database(self.path)
        self.db.add("terms", "원본 학기")
        term = self.db.list("terms")[0][0]
        self.term = term
        self.db.add("cohorts", "원본 반", term)
        self.db.add("subjects", "수학")
        self.db.add("teachers", "강사")
        self.cohort = self.db.list("cohorts", term)[0][0]
        self.subject = self.db.list("subjects")[0][0]
        self.teacher = self.db.list("teachers")[0][0]
        self.schedule = Schedule(self.db)
        self.schedule.save_quota(self.cohort, self.subject, 2, 2)
        self.schedule.assign(self.cohort, self.subject, self.teacher, None, 0, 1)

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_backup_and_restore_preserve_pre_restore_copy(self):
        self.db.set_capacity("cohorts", self.cohort, 30)
        self.db.set_facilities("subjects", self.subject, "빔프로젝터")
        self.db.set_eligible_teachers(self.subject, {self.teacher}, expected=set())
        backup_to(self.db, self.backup)
        self.db.add("teachers", "나중 강사")
        self.db.set_capacity("cohorts", self.cohort, 31)
        self.db.set_facilities("subjects", self.subject, "화이트보드")
        self.db.set_eligible_teachers(self.subject, set(), expected={self.teacher})
        safety = restore_from(self.db, self.backup)
        self.assertEqual([x[1] for x in self.db.list("teachers")], ["강사"])
        self.assertEqual(len(self.schedule.lessons(self.cohort)), 1)
        self.assertEqual(self.db.capacity_values("cohorts")[self.cohort], 30)
        self.assertEqual(self.db.facility_values("subjects")[self.subject], "빔프로젝터")
        self.assertEqual(self.db.eligible_teachers(self.subject), {self.teacher})
        before = Database(safety)
        self.assertEqual([x[1] for x in before.list("teachers")], ["강사", "나중 강사"])
        self.assertEqual(before.capacity_values("cohorts")[self.cohort], 31)
        self.assertEqual(before.facility_values("subjects")[self.subject], "화이트보드")
        self.assertEqual(before.eligible_teachers(self.subject), set())
        before.conn.close()
        self.assertEqual(self.db.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_version_three_backup_restores_with_unset_capacities(self):
        self.db.add("rooms", "101호")
        room = self.db.list("rooms")[0][0]
        backup_to(self.db, self.backup)
        connection = sqlite3.connect(self.backup)
        make_legacy_fixture(connection, 3)
        connection.close()
        original = self.backup.read_bytes()
        self.db.set_capacity("cohorts", self.cohort, 30)
        self.db.set_capacity("rooms", room, 40)
        safety_path = restore_from(self.db, self.backup)
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(self.db.conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertIsNone(self.db.capacity_values("cohorts")[self.cohort])
        self.assertIsNone(self.db.capacity_values("rooms")[room])
        self.assertEqual(len(self.schedule.lessons(self.cohort)), 1)
        safety = Database(safety_path)
        self.assertEqual(safety.capacity_values("rooms")[room], 40)
        safety.conn.close()

    def test_version_four_backup_preserves_capacities_with_empty_facilities(self):
        self.db.add("rooms", "101호")
        room = self.db.list("rooms")[0][0]
        self.db.set_capacity("cohorts", self.cohort, 30)
        self.db.set_capacity("rooms", room, 40)
        backup_to(self.db, self.backup)
        connection = sqlite3.connect(self.backup)
        make_legacy_fixture(connection, 4)
        connection.close()
        original = self.backup.read_bytes()
        self.db.set_facilities("subjects", self.subject, "빔프로젝터")
        self.db.set_facilities("rooms", room, "빔프로젝터")
        restore_from(self.db, self.backup)
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(self.db.capacity_values("cohorts")[self.cohort], 30)
        self.assertEqual(self.db.capacity_values("rooms")[room], 40)
        self.assertEqual(self.db.facility_values("subjects")[self.subject], "")
        self.assertEqual(self.db.facility_values("rooms")[room], "")
        self.assertEqual(len(self.schedule.lessons(self.cohort)), 1)

    def test_version_five_backup_preserves_facilities_with_no_teacher_restrictions(self):
        self.db.set_facilities("subjects", self.subject, "빔프로젝터")
        backup_to(self.db, self.backup)
        connection = sqlite3.connect(self.backup)
        make_legacy_fixture(connection, 5)
        connection.close()
        original = self.backup.read_bytes()
        self.db.set_eligible_teachers(self.subject, {self.teacher}, expected=set())
        before = self.schedule.lessons(self.cohort)
        restore_from(self.db, self.backup)
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(self.schedule.lessons(self.cohort), before)
        self.assertEqual(self.db.facility_values("subjects")[self.subject], "빔프로젝터")
        self.assertEqual(self.db.eligible_teachers(self.subject), set())

    def test_version_six_upgrade_and_backup_restore_support_saturday(self):
        self.db.set_eligible_teachers(self.subject, {self.teacher}, expected=set())
        self.schedule.set_availability(self.term, self.teacher, {(0, 1)}, "AVAILABLE")
        backup_to(self.db, self.backup)
        old = sqlite3.connect(self.backup)
        make_legacy_fixture(old, 6)
        old.close()
        upgraded = Database(self.backup)
        try:
            schedule = Schedule(upgraded)
            self.assertEqual(upgraded.eligible_teachers(self.subject), {self.teacher})
            self.assertEqual(schedule.availability(self.term, self.teacher), [(0, 1, "AVAILABLE")])
            self.assertEqual(len(schedule.lessons(self.cohort)), 1)
            schedule.assign(self.cohort, self.subject, self.teacher, None, 5, 1, schedule.lessons(self.cohort)[0][0])
            self.assertEqual(schedule.lessons(self.cohort)[0][1], 5)
        finally:
            upgraded.conn.close()
        restore_from(self.db, self.backup)
        self.assertEqual(self.schedule.lessons(self.cohort)[0][1], 5)

    def test_invalid_or_same_database_rejected_without_changes(self):
        before = self.schedule.lessons(self.cohort)
        with self.assertRaises(ValueError):
            backup_to(self.db, self.path)
        with self.assertRaises(ValueError):
            restore_from(self.db, self.path)
        self.backup.write_text("not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            restore_from(self.db, self.backup)
        self.assertEqual(self.schedule.lessons(self.cohort), before)
        self.assertEqual(list(Path(self.tmp.name).glob("before_restore_*")), [])

    def test_backup_failure_preserves_existing_file(self):
        self.backup.write_bytes(b"original backup")
        with patch("academy_timetable.backup.os.replace", side_effect=OSError("저장 실패")):
            with self.assertRaises(OSError):
                backup_to(self.db, self.backup)
        self.assertEqual(self.backup.read_bytes(), b"original backup")
        self.assertFalse(list(Path(self.tmp.name).glob(".academy-backup-*")))

    def test_failure_during_restore_rolls_back_and_keeps_safety_backup(self):
        backup_to(self.db, self.backup)
        self.db.add("teachers", "새 강사")
        with self.db.conn:
            self.db.conn.execute("""CREATE TRIGGER reject_restore BEFORE INSERT ON teachers
                BEGIN SELECT RAISE(ABORT, '거부'); END""")
        with self.assertRaisesRegex(RuntimeError, "복원 전 백업"):
            restore_from(self.db, self.backup)
        self.assertEqual([row[1] for row in self.db.list("teachers")], ["강사", "새 강사"])
        self.assertEqual(len(self.schedule.lessons(self.cohort)), 1)
        safety_files = list(Path(self.tmp.name).glob("before_restore_*.sqlite3"))
        self.assertEqual(len(safety_files), 1)
        safety = Database(safety_files[0])
        self.assertEqual([row[1] for row in safety.list("teachers")], ["강사", "새 강사"])
        safety.conn.close()

    def test_restore_serializes_with_other_window_writes(self):
        backup_to(self.db, self.backup)
        self.db.add("teachers", "복원 전 강사")
        restore_ready = threading.Event()
        release_restore = threading.Event()
        writer_started = threading.Event()
        writer_done = threading.Event()
        results = []
        writer_results = []

        def restore():
            connection = Database(self.path)
            def pause_delete(sql):
                if sql.startswith("DELETE FROM main.teacher_availability"):
                    restore_ready.set()
                    release_restore.wait(5)
            connection.conn.set_trace_callback(pause_delete)
            try:
                results.append(restore_from(connection, self.backup))
            except Exception as exc:
                results.append(exc)
            finally:
                connection.conn.close()

        def write():
            connection = Database(self.path)
            try:
                writer_started.set()
                connection.add("teachers", "동시 저장 강사")
                writer_results.append("saved")
            except Exception as exc:
                writer_results.append(str(exc))
            finally:
                connection.conn.close()
                writer_done.set()

        restore_thread = threading.Thread(target=restore)
        write_thread = threading.Thread(target=write)
        restore_thread.start()
        try:
            self.assertTrue(restore_ready.wait(5))
            write_thread.start()
            self.assertTrue(writer_started.wait(5))
            self.assertFalse(writer_done.wait(1), "복원 중 다른 창의 쓰기는 기다려야 합니다.")
        finally:
            release_restore.set()
            restore_thread.join(5)
            if write_thread.ident is not None:
                write_thread.join(5)
        self.assertFalse(restore_thread.is_alive())
        self.assertFalse(write_thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], Path)
        self.assertEqual(len(writer_results), 1)
        self.assertIn("다른 창에서 데이터를 복원", writer_results[0])
        self.assertEqual([row[1] for row in self.db.list("teachers")], ["강사"])
        safety = Database(results[0])
        self.assertEqual([row[1] for row in safety.list("teachers")], ["강사", "복원 전 강사"])
        safety.conn.close()

    def test_gui_restore_cancel_and_success(self):
        from academy_timetable.__main__ import MainWindow
        from academy_timetable.backup_ui import BackupPage
        app = QApplication.instance() or QApplication([])
        backup_to(self.db, self.backup)
        self.db.add("teachers", "새 강사")
        window = MainWindow(self.db)
        page = window.findChild(BackupPage)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.backup), "")), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            page.restore_backup()
        self.assertEqual(len(self.db.list("teachers")), 2)
        window.period_dirty = True
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.backup), "")), \
             patch.object(QMessageBox, "question", side_effect=[QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No]):
            page.restore_backup()
        self.assertEqual(len(self.db.list("teachers")), 2)
        self.assertTrue(window.period_dirty)
        window.period_dirty = False
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.backup), "")), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "information") as info:
            page.restore_backup()
        self.assertEqual(len(self.db.list("teachers")), 1)
        self.assertEqual(window.metrics["teachers"].text(), "1명")
        self.assertIn("복원 전 데이터 백업", info.call_args.args[2])
        window.close()

    def test_backup_validates_before_replacing_existing_file(self):
        self.backup.write_bytes(b"original backup")
        with self.db.conn:
            self.db.conn.execute("CREATE TABLE extension_data (value TEXT)")
        with self.assertRaisesRegex(ValueError, "테이블 구성"):
            backup_to(self.db, self.backup)
        self.assertEqual(self.backup.read_bytes(), b"original backup")
        self.assertFalse(list(Path(self.tmp.name).glob(".academy-backup-*")))

    def test_stale_window_cannot_modify_restored_data(self):
        from academy_timetable.excel_export import snapshot
        from academy_timetable.excel_import import apply_import
        from academy_timetable.review import review_draft
        backup_to(self.db, self.backup)
        self.db.rename("subjects", self.subject, "다른 과목")
        stale = Database(self.path)
        old_schedule = Schedule(stale)
        restore_from(self.db, self.backup)
        operations = [
            lambda: stale.add("teachers", "새 강사"),
            lambda: stale.rename("subjects", self.subject, "잘못된 이름"),
            lambda: stale.remove("teachers", self.teacher),
            lambda: stale.save_periods(self.term, stale.periods(self.term)),
            lambda: old_schedule.assign(self.cohort, self.subject, self.teacher, None, 1, 1),
            lambda: old_schedule.set_availability(self.term, self.teacher, {(1, 1)}, "AVAILABLE"),
            lambda: old_schedule.lock(old_schedule.lessons(self.cohort)[0][0], True),
            lambda: apply_import(stale, self.term, [(2, (), {"teachers": "가져오기"}, [])]),
            lambda: restore_from(stale, self.backup),
            lambda: backup_to(stale, Path(self.tmp.name) / "stale.sqlite3"),
            lambda: snapshot(stale, self.term),
            lambda: review_draft(stale, self.term),
        ]
        for operation in operations:
            with self.assertRaisesRegex(ValueError, "다른 창에서 데이터를 복원"):
                operation()
        self.assertEqual(self.db.list("subjects")[0][1], "수학")
        self.assertEqual(self.schedule.lessons(self.cohort)[0][7], 0)
        stale.conn.close()
        fresh = Database(self.path)
        fresh.add("teachers", "재시작 후 강사")
        self.assertEqual(len(fresh.list("teachers")), 2)
        fresh.conn.close()

    def test_extra_table_and_locked_backup_are_rejected(self):
        backup_to(self.db, self.backup)
        with closing(sqlite3.connect(self.backup)) as connection, connection:
            connection.execute("CREATE TABLE extra_data (value TEXT)")
        with self.assertRaisesRegex(ValueError, "테이블 구성"):
            restore_from(self.db, self.backup)
        self.assertEqual(len(self.schedule.lessons(self.cohort)), 1)
        backup_to(self.db, self.backup)
        locked = sqlite3.connect(self.backup)
        try:
            locked.execute("BEGIN EXCLUSIVE")
            with self.assertRaisesRegex(sqlite3.OperationalError, "사용 중"):
                restore_from(self.db, self.backup)
        finally:
            locked.rollback()
            locked.close()
        self.assertEqual(len(self.schedule.lessons(self.cohort)), 1)

    def test_wal_restore_rejects_stale_connection(self):
        self.assertEqual(self.db.conn.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        backup_to(self.db, self.backup)
        stale = Database(self.path)
        restore_from(self.db, self.backup)
        with self.assertRaisesRegex(ValueError, "다른 창에서 데이터를 복원"):
            stale.add("teachers", "잘못된 저장")
        stale.conn.close()
        self.assertEqual([row[1] for row in self.db.list("teachers")], ["강사"])

    def test_stale_window_shows_restart_message_on_navigation(self):
        from academy_timetable.__main__ import MainWindow
        app = QApplication.instance() or QApplication([])
        backup_to(self.db, self.backup)
        stale = Database(self.path)
        window = MainWindow(stale)
        original_page = window.pages.currentIndex()
        restore_from(self.db, self.backup)
        with patch.object(QMessageBox, "warning") as warning:
            window.nav.button(6).click()
        warning.assert_called_once()
        self.assertIn("다시 시작", warning.call_args.args[2])
        self.assertEqual(window.pages.currentIndex(), original_page)
        window.close()
        stale.conn.close()

    def test_wrong_schema_version_is_rejected(self):
        backup_to(self.db, self.backup)
        connection = sqlite3.connect(self.backup)
        connection.execute("PRAGMA user_version=99")
        connection.close()
        with self.assertRaisesRegex(ValueError, "버전 3"):
            restore_from(self.db, self.backup)
        self.assertEqual(len(self.schedule.lessons(self.cohort)), 1)


if __name__ == "__main__":
    unittest.main()
