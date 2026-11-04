import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from academy_timetable.db import Database
from academy_timetable.excel_import import apply_import, preview, read_sheet, sheet_names
from academy_timetable.__main__ import MainWindow
from academy_timetable.import_ui import ImportDialog


class ExcelImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "source.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "입력"
        sheet.append(["반명", "강사", "과목", "수업시간", "수강기호"])
        sheet.append(["A반", "김강사", "수학", 2, "수김"])
        sheet.append(["A반", "김강사", "영어", 1, "영김"])
        workbook.create_sheet("빈 시트")
        workbook.save(self.path)
        workbook.close()
        self.db = Database(":memory:")
        self.db.add("terms", "학기")
        self.term = self.db.list("terms")[0][0]

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_preview_and_idempotent_import(self):
        self.assertEqual(sheet_names(self.path), ["입력", "빈 시트"])
        labels, raw = read_sheet(self.path, "입력")
        rows = preview(self.db, self.term, labels, raw, {"cohorts": 0, "teachers": 1, "subjects": 2})
        self.assertEqual(rows[0][1][3:], (2, "수김"))
        self.assertFalse(any(row[3] for row in rows))
        self.assertEqual(apply_import(self.db, self.term, rows), {"cohorts": 1, "teachers": 1, "subjects": 2, "rooms": 0})
        self.assertEqual(apply_import(self.db, self.term, rows), {"cohorts": 0, "teachers": 0, "subjects": 0, "rooms": 0})
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM quotas").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            preview(self.db, self.term, labels, raw, {"teachers": 0, "subjects": 0})

    def test_bad_rows_and_changed_database_cancel_everything(self):
        labels, raw = read_sheet(self.path, "입력")
        invalid = preview(self.db, self.term, labels, raw, {"teachers": 3})
        self.assertTrue(invalid[0][3])
        with self.assertRaises(ValueError):
            apply_import(self.db, self.term, invalid)
        self.assertEqual(self.db.list("teachers"), [])
        rows = preview(self.db, self.term, labels, raw, {"teachers": 1, "subjects": 2})
        self.db.add("subjects", "수학")
        self.db.remove("subjects", self.db.list("subjects")[0][0])
        with self.assertRaisesRegex(ValueError, "비활성"):
            apply_import(self.db, self.term, rows)
        self.assertEqual(self.db.list("teachers"), [])
        self.assertEqual(len(self.db.list("subjects")), 1)

    def test_formula_and_missing_values_are_errors(self):
        labels = ["과목", "기타"]
        rows = preview(self.db, self.term, labels, [(2, ("=A1", "x")), (3, (None, "내용"))], {"subjects": 0})
        self.assertTrue(all(row[3] for row in rows))

    def test_gui_mapping_preview_and_import(self):
        window = MainWindow(self.db)
        dialog = ImportDialog(window, self.db, self.term)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.path), "")):
            dialog.choose_file()
        dialog.mapping["cohorts"].setCurrentIndex(1)
        dialog.mapping["teachers"].setCurrentIndex(2)
        dialog.make_preview()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.table.item(0, 5).text(), "2")
        dialog.mapping["subjects"].setCurrentIndex(3)
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.make_preview()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "information"):
            dialog.apply()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(self.db.list("cohorts", self.term)[0][1], "A반")
        window.close()


if __name__ == "__main__":
    unittest.main()
