import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit

from academy_timetable.backup import backup_to, restore_from
from academy_timetable.db import Database, SCHEMA_VERSION
from academy_timetable.excel_export import export_timetable
from academy_timetable.schedule import Schedule
from academy_timetable.review import review_draft
from academy_timetable.timetable_import import ImportedLesson, SheetRow, apply_timetable, preview_timetable, read_timetable
from legacy_db import make_legacy_fixture


class SubjectClassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.db = Database(self.root / "current.sqlite3")
        self.db.add("terms", "학기")
        self.term = self.db.list("terms")[0][0]
        for name in ("문학", "독서", "대수"):
            self.db.add("subjects", name)
        self.subjects = {name: row_id for row_id, name, _ in self.db.list("subjects")}
        for name in ("김강사", "이강사"):
            self.db.add("teachers", name)
        self.teachers = [row_id for row_id, _ in self.db.list("teachers")]

    def tearDown(self):
        self.db.conn.close()
        self.folder.cleanup()

    def configure_areas(self):
        for name in ("문학", "독서"):
            self.db.set_subject_area(self.subjects[name], "국어")
        self.db.set_subject_area(self.subjects["대수"], "수학")

    def test_area_and_registered_subject_classes_have_independent_curricula(self):
        self.configure_areas()
        ids = []
        for area in ("국어", "수학"):
            for label in ("A", "B", "C"):
                ids.append(self.db.save_cohort(self.term, f"{area} {label}", "AREA", area))
        literature = self.db.save_cohort(self.term, "문학 A", "SUBJECT", "문학")
        schedule = Schedule(self.db)
        for name in ("문학", "독서"):
            schedule.save_quota(ids[0], self.subjects[name], 1, 1)
        schedule.save_quota(literature, self.subjects["문학"], 1, 1)
        for cohort, name in ((ids[0], "대수"), (ids[3], "문학"), (literature, "독서")):
            with self.assertRaisesRegex(ValueError, "반 기준"):
                schedule.save_quota(cohort, self.subjects[name], 1, 1)
        self.assertEqual(len(set(ids)), 6)
        self.assertEqual(self.db.cohort_scope(ids[0]), ("AREA", "국어"))
        self.assertEqual(self.db.cohort_scope(literature), ("SUBJECT", "문학"))
        for label in ("D", "E", "F", "G"):
            self.db.save_cohort(self.term, f"국어 {label}", "AREA", "국어")
        self.assertFalse(any(label == "반 수" for _, label, _ in review_draft(self.db, self.term)))
        schedule.assign(ids[0], self.subjects["문학"], self.teachers[0], None, 0, 1)
        schedule.assign(literature, self.subjects["문학"], self.teachers[1], None, 0, 1)
        with self.assertRaisesRegex(ValueError, "강사 중복"):
            schedule.assign(literature, self.subjects["문학"], self.teachers[0], None, 0, 1,
                            schedule.lessons(literature)[0][0])

    def test_incompatible_scope_or_area_changes_preserve_existing_settings(self):
        self.configure_areas()
        cohort = self.db.save_cohort(self.term, "국어 A", "AREA", "국어")
        schedule = Schedule(self.db)
        schedule.save_quota(cohort, self.subjects["독서"], 1, 1)
        with self.assertRaisesRegex(ValueError, "기존 시수"):
            self.db.save_cohort(self.term, "바뀐 반", "SUBJECT", "문학", cohort_id=cohort)
        self.assertEqual(self.db.list("cohorts", self.term), [(cohort, "국어 A")])
        self.assertEqual(self.db.cohort_scope(cohort), ("AREA", "국어"))
        with self.assertRaisesRegex(ValueError, "교과 반"):
            self.db.set_subject_area(self.subjects["독서"], "수학")
        self.assertEqual(self.db.subject_area(self.subjects["독서"]), "국어")
        row = SheetRow(2, (), ImportedLesson("국어 A", "대수", "김강사", None, 0, 1, 1, False))
        before = list(self.db.conn.iterdump())
        approved = preview_timetable(self.db, self.term, [row])
        self.assertEqual(approved[1][0][0], "오류")
        self.assertIn("반 기준", approved[1][0][1])
        self.assertEqual(list(self.db.conn.iterdump()), before)
        with self.assertRaisesRegex(ValueError, "오류"):
            apply_timetable(self.db, self.term, [row], approved)
        self.db.rename("cohorts", cohort, "국어 B")
        with self.assertRaisesRegex(ValueError, "변경"):
            self.db.save_cohort(self.term, "국어 A", "AREA", "국어", cohort_id=cohort,
                                expected=("국어 A", "AREA", "국어"))

    def test_version_seven_upgrade_and_backup_restore_preserve_common_classes(self):
        self.db.add("cohorts", "기존 반", self.term)
        cohort = self.db.list("cohorts", self.term)[0][0]
        schedule = Schedule(self.db)
        schedule.save_quota(cohort, self.subjects["문학"], 1, 1)
        schedule.assign(cohort, self.subjects["문학"], self.teachers[0], None, 5, 1)
        old_backup = self.root / "version-seven.sqlite3"
        backup_to(self.db, old_backup)
        legacy = Database(old_backup)
        make_legacy_fixture(legacy.conn, 7)
        legacy.conn.close()
        self.configure_areas()
        self.db.save_cohort(self.term, "국어 A", "AREA", "국어")
        restore_from(self.db, old_backup)
        self.assertEqual(self.db.list("cohorts", self.term), [(cohort, "기존 반")])
        self.assertEqual(self.db.cohort_scope(cohort), ("COMMON", None))
        self.assertEqual(schedule.lessons(cohort)[0][1], 5)
        self.assertEqual(self.db.list("subject_areas"), [])
        old = Database(self.root / "upgrade.sqlite3")
        old.add("terms", "기존 학기")
        make_legacy_fixture(old.conn, 7)
        updated = Database(self.root / "upgrade.sqlite3")
        try:
            self.assertEqual(updated.list("terms"), [(1, "기존 학기")])
            self.assertEqual(updated.conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            with self.assertRaisesRegex(ValueError, "갱신"):
                old.add("teachers", "오래된 창")
        finally:
            updated.conn.close()
            old.conn.close()

    def test_excel_and_backup_round_trip_preserve_both_scope_types(self):
        self.configure_areas()
        schedule = Schedule(self.db)
        for index, (name, kind, target) in enumerate((("국어 A", "AREA", "국어"), ("문학 A", "SUBJECT", "문학"))):
            cohort = self.db.save_cohort(self.term, name, kind, target)
            schedule.save_quota(cohort, self.subjects["문학"], 1, 1)
            schedule.assign(cohort, self.subjects["문학"], self.teachers[index], None, 0, 1)
        backup = self.root / "scoped.sqlite3"
        backup_to(self.db, backup)
        self.db.save_cohort(self.term, "공통으로 변경", "COMMON", None, cohort_id=cohort)
        restore_from(self.db, backup)
        self.assertEqual(self.db.cohort_scope(cohort), ("SUBJECT", "문학"))
        path = self.root / "scoped.xlsx"
        export_timetable(self.db, self.term, path)
        target_db = Database(self.root / "import.sqlite3")
        try:
            target_db.add("terms", "가져온 학기")
            term = target_db.list("terms")[0][0]
            rows = read_timetable(path, "전체_배정목록")
            approved = preview_timetable(target_db, term, rows)
            self.assertFalse(any(action == "오류" for action, _ in approved[1]), approved)
            self.assertEqual(apply_timetable(target_db, term, rows, approved), 2)
            scopes = {name: target_db.cohort_scope(row_id) for row_id, name in target_db.list("cohorts", term)}
            self.assertEqual(scopes, {"국어 A": ("AREA", "국어"), "문학 A": ("SUBJECT", "문학")})
            self.assertTrue(all(action == "건너뜀" for action, _ in preview_timetable(target_db, term, rows)[1]))
        finally:
            target_db.conn.close()

    def test_gui_configures_each_scope_and_filters_quota_subjects(self):
        from academy_timetable.__main__ import MainWindow
        self.configure_areas()
        window = MainWindow(self.db)
        try:
            window.show_page(1)
            self.assertEqual(window.heading.text(), "과목별 반 설정")
            for name, kind, target in (("국어 A", "AREA", "국어"), ("문학 A", "SUBJECT", "문학")):
                def save_dialog(dialog):
                    boxes = {box.accessibleName(): box for box in dialog.findChildren(QComboBox)}
                    dialog.findChild(QLineEdit).setText(name)
                    boxes["반 구분"].setCurrentIndex(boxes["반 구분"].findData(kind))
                    boxes["반 기준"].setCurrentText(target)
                    return QDialog.DialogCode.Accepted

                with patch.object(QDialog, "exec", new=save_dialog):
                    window.edit("cohorts", "add")
                cohort = next(row_id for row_id, label in self.db.list("cohorts", self.term) if label == name)
                self.assertEqual(self.db.cohort_scope(cohort), (kind, target))
                page = window.schedule_page
                page.cohort.setCurrentIndex(page.cohort.findData(cohort))
                seen = []

                def inspect_quota(dialog):
                    subjects = dialog.findChildren(QComboBox)[0]
                    seen.extend(subjects.itemText(i) for i in range(subjects.count()))
                    return QDialog.DialogCode.Rejected

                with patch.object(QDialog, "exec", new=inspect_quota):
                    page.edit_quota()
                self.assertEqual(set(seen), {"문학", "독서"} if kind == "AREA" else {"문학"})
            text = " ".join(window.lists["cohorts"].item(i).text() for i in range(2))
            self.assertIn("교과 단위 (국어)", text)
            self.assertIn("등록 과목 단위 (문학)", text)
            index = next(i for i in range(window.lists["subjects"].count())
                         if window.lists["subjects"].item(i).data(256) == self.subjects["문학"])
            window.lists["subjects"].setCurrentRow(index)
            with patch("academy_timetable.__main__.QInputDialog.getItem", return_value=("언어", True)):
                window.edit("subjects", "area")
            self.assertEqual(self.db.subject_area(self.subjects["문학"]), "언어")
        finally:
            window.close()
