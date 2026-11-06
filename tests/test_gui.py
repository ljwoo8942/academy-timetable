import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from academy_timetable.__main__ import MainWindow
from academy_timetable.db import Database
from academy_timetable.schedule import Schedule


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.db.add("terms", "1학기")
        self.db.add("terms", "2학기")
        self.window = MainWindow(self.db)

    def tearDown(self):
        self.window.period_dirty = False
        self.window.close()
        self.db.conn.close()

    def test_navigation_and_crud_refresh_counts(self):
        self.window.nav.button(2).click()
        self.assertEqual(self.window.heading.text(), "강사 관리")
        with patch.object(QInputDialog, "getText", return_value=("홍길동", True)):
            self.window.edit("teachers", "add")
        self.assertEqual(self.window.metrics["teachers"].text(), "1명")
        self.window.lists["teachers"].setCurrentRow(0)
        with patch.object(QInputDialog, "getText", return_value=("김강사", True)):
            self.window.edit("teachers", "rename")
        self.assertEqual(self.window.lists["teachers"].item(0).text(), "김강사")
        self.window.lists["teachers"].setCurrentRow(0)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.edit("teachers", "remove")
        self.assertEqual(self.window.metrics["teachers"].text(), "0명")

    def test_period_edit_survives_navigation_and_cancelled_term_change(self):
        self.window.nav.button(5).click()
        first = self.window.term.currentData()
        self.window.period_table.item(0, 0).setText("08:20")
        self.window.nav.button(2).click()
        self.window.nav.button(5).click()
        self.assertEqual(self.window.period_table.item(0, 0).text(), "08:20")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.window.term.setCurrentIndex(1)
        self.assertEqual(self.window.term.currentData(), first)
        self.window.save_periods()
        self.assertEqual(self.db.periods(first)[0], ("08:20", "09:20"))
        self.window.term.setCurrentIndex(1)
        self.assertEqual(self.window.period_table.item(0, 0).text(), "08:30")

    def test_schedule_page_quota_lesson_and_lock(self):
        term = self.window.term.currentData()
        self.db.add("cohorts", "A반", term)
        self.db.add("subjects", "수학")
        self.db.add("teachers", "강사")
        self.window.refresh_all()
        self.window.nav.button(6).click()
        page = self.window.schedule_page
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            page.edit_quota()
            page.grid.setCurrentCell(0, 0)
            page.edit_lesson()
        self.assertEqual(page.quota_table.item(0, 2).text(), "2 / 0")
        self.assertEqual(page.grid.item(0, 0).data(256), page.grid.item(1, 0).data(256))
        page.grid.setCurrentCell(1, 0)
        page.toggle_lock()
        self.assertTrue(page.selected_lesson()[7])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "warning") as warning:
            page.delete_lesson()
        warning.assert_called_once()
        self.assertEqual(len(page.schedule.lessons(page.cohort.currentData())), 1)
        self.window.nav.button(7).click()
        load_table = self.window.teacher_load_page.table
        self.assertEqual(load_table.item(0, 1).text(), "2")
        self.assertEqual(load_table.item(1, 2).text(), "2")
        self.window.term.setCurrentIndex(1)
        self.assertEqual(load_table.item(0, 1).text(), "0")

    def test_availability_page_updates_and_blocks_conflict(self):
        term = self.window.term.currentData()
        self.db.add("cohorts", "A반", term)
        self.db.add("subjects", "수학")
        self.db.add("teachers", "강사")
        self.window.refresh_all()
        page = self.window.availability_page
        self.window.nav.button(8).click()
        page.grid.setCurrentCell(1, 0)
        page.apply("UNAVAILABLE")
        self.assertEqual(page.grid.item(1, 0).text(), "불가")
        cohort = self.db.list("cohorts", term)[0][0]
        subject = self.db.list("subjects")[0][0]
        teacher = self.db.list("teachers")[0][0]
        page.schedule.save_quota(cohort, subject, 2, 2)
        with self.assertRaises(ValueError):
            page.schedule.assign(cohort, subject, teacher, None, 0, 1)
        page.apply("UNSET")
        page.schedule.assign(cohort, subject, teacher, None, 0, 1)
        with patch.object(QMessageBox, "warning") as warning:
            page.apply("UNAVAILABLE")
        warning.assert_called_once()
        self.assertEqual(page.grid.item(1, 0).text(), "미설정")
        self.window.term.setCurrentIndex(1)
        self.assertEqual(page.grid.item(1, 0).text(), "미설정")
        self.window.nav.button(2).click()
        page.schedule.set_availability(self.window.term.currentData(), teacher, {(1, 3)}, "UNAVAILABLE")
        self.window.nav.button(8).click()
        self.assertEqual(page.grid.item(2, 1).text(), "불가")

    def test_review_page_updates_for_selected_term(self):
        first = self.window.term.currentData()
        self.db.add("cohorts", "A반", first)
        self.window.refresh_all()
        self.window.nav.button(9).click()
        page = self.window.review_page
        self.assertIn("확인 필요", page.summary.text())
        self.assertTrue(any(page.table.item(row, 1).text() == "시수 미설정" for row in range(page.table.rowCount())))
        self.window.term.setCurrentIndex(1)
        self.assertFalse(any("A반" in page.table.item(row, 2).text() for row in range(page.table.rowCount())))

    def test_room_assignment_saves_to_the_timetable_and_follows_the_selected_term(self):
        term = self.window.term.currentData()
        self.db.add("cohorts", "A반", term)
        self.db.add("subjects", "수학")
        self.db.add("teachers", "강사")
        self.db.add("rooms", "101호")
        self.db.add("rooms", "102호")
        self.db.add("rooms", "103호")
        cohort = self.db.list("cohorts", term)[0][0]
        subject = self.db.list("subjects")[0][0]
        teacher = self.db.list("teachers")[0][0]
        room = self.db.list("rooms")[0][0]
        schedule = Schedule(self.db)
        schedule.save_quota(cohort, subject, 2, 2)
        schedule.assign(cohort, subject, teacher, None, 0, 1)
        self.window.refresh_all()
        self.window.lists["cohorts"].setCurrentRow(0)
        with patch.object(QInputDialog, "getInt", return_value=(30, True)):
            self.window.edit("cohorts", "capacity")
        self.assertIn("인원 30명", self.window.lists["cohorts"].item(0).text())
        self.window.lists["rooms"].setCurrentRow(1)
        with patch.object(QInputDialog, "getInt", return_value=(20, True)):
            self.window.edit("rooms", "capacity")
        self.assertIn("정원 20명", self.window.lists["rooms"].item(1).text())
        self.window.lists["subjects"].setCurrentRow(0)
        with patch.object(QInputDialog, "getMultiLineText", return_value=("빔프로젝터", True)):
            self.window.edit("subjects", "facilities")
        self.assertIn("필수 시설 빔프로젝터", self.window.lists["subjects"].item(0).text())
        for row in (0, 1):
            self.window.lists["rooms"].setCurrentRow(row)
            with patch.object(QInputDialog, "getMultiLineText", return_value=("빔프로젝터", True)):
                self.window.edit("rooms", "facilities")
        page = self.window.room_assignment_page
        self.window.nav.button(self.window.pages.indexOf(page)).click()
        self.assertIn("미배정 1개", page.summary.text())
        page.table.selectRow(0)
        self.assertEqual(page.room.count(), 2)
        self.assertIn("필수 시설 빔프로젝터", page.hint.text())
        page.room.setCurrentIndex(page.room.findData(room))
        page.save_button.click()
        self.assertIn("미배정 0개", page.summary.text())
        self.window.nav.button(6).click()
        for period in (0, 1):
            self.assertIn("101호", self.window.schedule_page.grid.item(period, 0).text())
        self.window.term.setCurrentIndex(1)
        self.assertEqual(page.table.rowCount(), 0)


if __name__ == "__main__":
    unittest.main()
