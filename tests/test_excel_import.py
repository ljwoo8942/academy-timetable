import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from academy_timetable.db import Database
from academy_timetable.excel_export import export_timetable
from academy_timetable.excel_import import apply_import, preview, read_sheet, sheet_names
from academy_timetable.__main__ import MainWindow
from academy_timetable.import_ui import ImportDialog, TimetableImportDialog
from academy_timetable.schedule import Schedule
from academy_timetable.timetable_import import apply_timetable, preview_timetable, read_timetable


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

    def test_oversized_sheet_is_rejected_before_loading_rows(self):
        for row, column in ((5002, 1), (2, 257), (1001, 51)):
            with self.subTest(row=row, column=column):
                workbook = Workbook()
                sheet = workbook.active
                sheet.append(["반명"])
                sheet.cell(row, column, "범위 끝")
                workbook.save(self.path)
                workbook.close()
                with self.assertRaisesRegex(ValueError, "범위"):
                    read_sheet(self.path, sheet.title)
                self.assertEqual(self.db.list("cohorts", self.term), [])

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

    def test_timetable_dialog_imports_only_the_selected_sheet(self):
        workbook = Workbook()
        for sheet, cohort in ((workbook.active, "다른 반"), (workbook.create_sheet("선택할 시트"), "A반")):
            sheet.append(["반", "과목", "강사", "요일", "시작 교시", "종료 교시"])
            sheet.append([cohort, "수학", "김강사", "월요일", "1교시", 2])
        workbook.save(self.path)
        workbook.close()
        window = MainWindow(self.db)
        dialog = TimetableImportDialog(window, self.db, self.term)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.path), "")):
            dialog.choose_file()
        self.assertFalse(dialog.preview_button.isEnabled())
        dialog.sheet.setCurrentIndex(0)
        dialog.make_preview()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(self.db.list("cohorts", self.term), [])
        dialog.sheet.setCurrentText("선택할 시트")
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.table.rowCount(), 0)
        dialog.make_preview()
        self.assertEqual(dialog.table.item(0, 2).text(), "A반")
        with patch.object(QMessageBox, "information"):
            dialog.apply()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual([row[1] for row in self.db.list("cohorts", self.term)], ["A반"])
        self.assertEqual(Schedule(self.db).room_lessons(self.term)[0].length, 2)
        window.close()

    def test_timetable_round_trip_preserves_locks_and_skips_existing_lessons(self):
        for table, name in (("cohorts", "A반"), ("subjects", "수학"), ("teachers", "김강사"), ("rooms", "101호")):
            self.db.add(table, name, self.term)
        cohort = self.db.list("cohorts", self.term)[0][0]
        subject, teacher, room = (self.db.list(table)[0][0] for table in ("subjects", "teachers", "rooms"))
        schedule = Schedule(self.db)
        schedule.save_quota(cohort, subject, 4, 2)
        schedule.assign(cohort, subject, teacher, room, 0, 1)
        schedule.lock(schedule.lessons(cohort)[0][0], True)
        schedule.assign(cohort, subject, teacher, None, 1, 2)
        export_timetable(self.db, self.term, self.path)
        self.db.add("terms", "가져오기 학기")
        target = next(row[0] for row in self.db.list("terms") if row[1] == "가져오기 학기")
        rows = read_timetable(self.path, "전체_배정목록")
        self.assertEqual([row.number for row in rows], [4, 5])
        approved = preview_timetable(self.db, target, rows)
        self.assertEqual(self.db.list("cohorts", target), [])
        self.assertEqual(apply_timetable(self.db, target, rows, approved), 2)
        copied = sorted(schedule.room_lessons(target), key=lambda row: row.weekday)
        self.assertEqual([(row.start, row.length, row.room_id, row.locked) for row in copied],
                         [(1, 2, room, 1), (2, 2, None, 0)])
        repeat = preview_timetable(self.db, target, rows)
        self.assertEqual([action for action, _ in repeat[1]], ["건너뜀", "건너뜀"])

    def test_timetable_conflict_after_preview_rolls_back_new_names_and_lessons(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["반", "과목", "강사", "요일", "교시"])
        sheet.append(["새 반", "영어", "새 강사", "화", 1])
        sheet.append(["다른 반", "수학", "김강사", "월", 1])
        workbook.save(self.path)
        workbook.close()
        rows = read_timetable(self.path, sheet.title)
        approved = preview_timetable(self.db, self.term, rows)
        self.db.add("cohorts", "기존 반", self.term)
        self.db.add("teachers", "김강사")
        self.db.add("subjects", "수학")
        schedule = Schedule(self.db)
        cohort = self.db.list("cohorts", self.term)[0][0]
        subject, teacher = (self.db.list(table)[0][0] for table in ("subjects", "teachers"))
        schedule.save_quota(cohort, subject, 1, 1)
        schedule.assign(cohort, subject, teacher, None, 0, 1)
        with self.assertRaisesRegex(ValueError, "변경되었습니다"):
            apply_timetable(self.db, self.term, rows, approved)
        self.assertEqual([row[1] for row in self.db.list("cohorts", self.term)], ["기존 반"])
        self.assertEqual([row[1] for row in self.db.list("teachers")], ["김강사"])
        changed = preview_timetable(self.db, self.term, rows)
        self.assertIn("강사 중복", changed[1][1][1])
        self.assertEqual(len(schedule.room_lessons(self.term)), 1)

    def test_grid_timetable_imports_saturday_and_excludes_every_508_column(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.cell(3, 2, "요일")
        sheet.cell(5, 2, "반")
        for column, day, cohort in ((3, "월", 601), (4, None, 508), (5, "토", 601), (6, None, 508)):
            if day:
                sheet.cell(3, column, day)
            sheet.cell(5, column, cohort)
            sheet.cell(7, column, "국한\n단과" if column == 5 else "수학1\nA1")
            if column != 5:
                sheet.cell(8, column, "수고")
        sheet.cell(7, 2, 1)
        workbook.save(self.path)
        workbook.close()
        rows = read_timetable(self.path, sheet.title, ["508반"])
        self.assertEqual([row.number for row in rows], ["C7", "E7"])
        self.assertEqual(rows[1].lesson.teacher, "국한")
        approved = preview_timetable(self.db, self.term, rows)
        self.assertEqual(apply_timetable(self.db, self.term, rows, approved), 2)
        schedule = Schedule(self.db)
        self.assertEqual([row[1] for row in self.db.list("cohorts", self.term)], ["601"])
        self.assertEqual({row.weekday for row in schedule.room_lessons(self.term)}, {0, 5})
        export_timetable(self.db, self.term, self.path)
        exported = read_timetable(self.path, "전체_배정목록")
        self.assertEqual({row.lesson.weekday for row in exported}, {0, 5})


if __name__ == "__main__":
    unittest.main()
