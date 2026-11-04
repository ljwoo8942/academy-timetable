import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from academy_timetable.db import Database
from academy_timetable.excel_export import export_timetable
from academy_timetable.schedule import Schedule
from academy_timetable.__main__ import MainWindow


class ExcelExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "시간표.xlsx"
        self.db = Database(":memory:")
        self.db.add("terms", "2026 1학기")
        self.term = self.db.list("terms")[0][0]
        self.db.add("cohorts", "A반/특별", self.term)
        self.db.add("subjects", "=수학")
        self.db.add("teachers", "=김강사")
        self.db.add("rooms", "101호")
        self.cohort = self.db.list("cohorts", self.term)[0][0]
        self.subject = self.db.list("subjects")[0][0]
        self.teacher = self.db.list("teachers")[0][0]
        self.room = self.db.list("rooms")[0][0]
        self.schedule = Schedule(self.db)
        self.schedule.save_quota(self.cohort, self.subject, 4, 2)
        self.schedule.assign(self.cohort, self.subject, self.teacher, self.room, 0, 1)
        self.schedule.assign(self.cohort, self.subject, self.teacher, None, 1, 5)

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_export_views_totals_and_literal_text(self):
        before = self.schedule.lessons(self.cohort)
        export_timetable(self.db, self.term, self.path)
        book = load_workbook(self.path)
        self.assertEqual(book.sheetnames, ["반_001", "강사_001", "강의실_001", "전체_배정목록", "과목_시수요약", "강사_배정시수"])
        cohort = book["반_001"]
        self.assertIn("초안", cohort["A1"].value)
        self.assertIn("A반/특별", cohort["A1"].value)
        self.assertEqual(cohort["B4"].value, "08:30~09:20")
        self.assertEqual(cohort["C4"].value, cohort["C5"].value)
        self.assertIn("강의실 미배정", cohort["D8"].value)
        self.assertEqual(book["전체_배정목록"]["B4"].value, "=수학")
        self.assertEqual(book["전체_배정목록"]["B4"].data_type, "s")
        self.assertEqual(book["강사_배정시수"]["B4"].value, 4)
        self.assertEqual(book["강사_배정시수"]["C5"].value, 4)
        self.assertEqual(book["과목_시수요약"]["F4"].value, 0)
        self.assertEqual(cohort.freeze_panes, "C4")
        self.assertEqual(cohort.page_setup.orientation, "landscape")
        cohort["C4"] = "엑셀에서 수정"
        book.save(self.path)
        book.close()
        self.assertEqual(self.schedule.lessons(self.cohort), before)

    def test_existing_file_survives_save_failure(self):
        self.path.write_bytes(b"original")
        with patch("openpyxl.workbook.workbook.Workbook.save", side_effect=OSError("저장 실패")):
            with self.assertRaises(OSError):
                export_timetable(self.db, self.term, self.path)
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertEqual(os.listdir(self.tmp.name), ["시간표.xlsx"])

    def test_gui_cancel_overwrite_and_preserve_unsaved_periods(self):
        self.path.write_bytes(b"original")
        window = MainWindow(self.db)
        window.period_table.item(0, 0).setText("08:20")
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(self.path), "")), \
             patch.object(QMessageBox, "question", side_effect=[QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No]):
            window.export_excel()
        self.assertEqual(self.path.read_bytes(), b"original")
        self.assertTrue(window.period_dirty)
        window.period_dirty = False
        window.close()


if __name__ == "__main__":
    unittest.main()
