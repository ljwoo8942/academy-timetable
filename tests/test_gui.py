import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from academy_timetable.__main__ import MainWindow
from academy_timetable.db import Database


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


if __name__ == "__main__":
    unittest.main()
