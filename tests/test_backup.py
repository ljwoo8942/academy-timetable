import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from academy_timetable.backup import backup_to, restore_from
from academy_timetable.db import Database
from academy_timetable.schedule import Schedule


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "current.sqlite3"
        self.backup = Path(self.tmp.name) / "backup.sqlite3"
        self.db = Database(self.path)
        self.db.add("terms", "원본 학기")
        term = self.db.list("terms")[0][0]
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
        backup_to(self.db, self.backup)
        self.db.add("teachers", "나중 강사")
        safety = restore_from(self.db, self.backup)
        self.assertEqual([x[1] for x in self.db.list("teachers")], ["강사"])
        self.assertEqual(len(self.schedule.lessons(self.cohort)), 1)
        before = Database(safety)
        self.assertEqual([x[1] for x in before.list("teachers")], ["강사", "나중 강사"])
        before.conn.close()
        self.assertEqual(self.db.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

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
        self.assertEqual([row[1] for row in self.db.list("teachers")], ["강사", "동시 저장 강사"])
        safety = Database(results[0])
        self.assertEqual([row[1] for row in safety.list("teachers")], ["강사", "복원 전 강사"])
        safety.conn.close()

    def test_gui_restore_cancel_and_success(self):
        from academy_timetable.__main__ import MainWindow
        app = QApplication.instance() or QApplication([])
        backup_to(self.db, self.backup)
        self.db.add("teachers", "새 강사")
        window = MainWindow(self.db)
        page = window.pages.widget(10)
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

    def test_extra_table_and_locked_backup_are_rejected(self):
        backup_to(self.db, self.backup)
        with sqlite3.connect(self.backup) as connection:
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
