from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from .excel_import import FIELDS, apply_import, preview, read_sheet, sheet_names
from .timetable_import import COLUMNS, apply_timetable, preview_timetable, read_timetable


class ImportDialog(QDialog):
    def __init__(self, parent, db, term_id):
        super().__init__(parent)
        self.db = db
        self.term_id = term_id
        self.path = None
        self.labels = []
        self.source_rows = []
        self.preview_rows = None
        self.setWindowTitle("엑셀 기본 정보 가져오기")
        self.resize(950, 650)
        box = QVBoxLayout(self)
        notice = QLabel("반·강사·과목·강의실 이름만 가져옵니다. 교과, 레벨, 수강기호, 시수와 나머지 열은 저장하지 않습니다.")
        notice.setWordWrap(True)
        box.addWidget(notice)
        term_name = next((name for row_id, name in db.list("terms") if row_id == term_id), "선택 안 됨")
        term_label = QLabel(f"반을 저장할 학기: {term_name} · 반 열은 실제 반 이름일 때만 선택하세요. 첫 행은 열 제목입니다.")
        term_label.setWordWrap(True)
        box.addWidget(term_label)
        file_row = QHBoxLayout()
        select = QPushButton("엑셀 파일 선택")
        select.clicked.connect(self.choose_file)
        file_row.addWidget(select)
        self.file_label = QLabel("선택된 파일 없음")
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(QLabel("시트"))
        self.sheet = QComboBox()
        self.sheet.currentIndexChanged.connect(self.change_sheet)
        file_row.addWidget(self.sheet)
        box.addLayout(file_row)
        form = QFormLayout()
        self.mapping = {}
        for key, label in FIELDS.items():
            combo = QComboBox()
            combo.addItem("가져오지 않음", None)
            combo.currentIndexChanged.connect(self.invalidate)
            self.mapping[key] = combo
            form.addRow(label, combo)
        box.addLayout(form)
        preview_button = QPushButton("미리보기")
        preview_button.clicked.connect(self.make_preview)
        box.addWidget(preview_button)
        self.status = QLabel("파일과 열을 선택한 다음 미리보기를 확인하세요.")
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAccessibleName("엑셀 원본 행과 검증 결과")
        box.addWidget(self.table, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        self.apply_button = QPushButton("가져오기")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply)
        actions.addWidget(self.apply_button)
        cancel = QPushButton("닫기")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        box.addLayout(actions)

    def invalidate(self):
        self.preview_rows = None
        if hasattr(self, "apply_button"):
            self.apply_button.setEnabled(False)
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.status.setText("파일과 열을 선택한 다음 미리보기를 확인하세요.")

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "엑셀 파일 선택", "", "Excel 파일 (*.xlsx)")
        if not path:
            return
        try:
            sheets = sheet_names(path)
            if not sheets:
                raise ValueError("시트가 없습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "파일 열기 실패", str(exc))
            return
        self.path = path
        self.file_label.setText(Path(path).name)
        self.sheet.blockSignals(True)
        self.sheet.clear()
        self.sheet.addItems(sheets)
        self.sheet.blockSignals(False)
        self.change_sheet()

    def change_sheet(self):
        self.invalidate()
        try:
            self.labels, self.source_rows = read_sheet(self.path, self.sheet.currentText())
            for combo in self.mapping.values():
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("가져오지 않음", None)
                for index, label in enumerate(self.labels):
                    combo.addItem(label, index)
                combo.blockSignals(False)
        except Exception as exc:
            self.labels, self.source_rows = [], []
            for combo in self.mapping.values():
                combo.clear()
                combo.addItem("가져오지 않음", None)
            QMessageBox.warning(self, "시트 읽기 실패", str(exc))

    def make_preview(self):
        try:
            mapping = {key: combo.currentData() for key, combo in self.mapping.items() if combo.currentData() is not None}
            rows = preview(self.db, self.term_id, self.labels, self.source_rows, mapping)
            self.preview_rows = rows
            self.table.setColumnCount(len(self.labels) + 2)
            self.table.setHorizontalHeaderLabels(["행", "확인 결과"] + self.labels)
            self.table.setRowCount(len(rows))
            error_count = 0
            for row_index, (number, values, mapped, errors) in enumerate(rows):
                error_count += bool(errors)
                texts = [str(number), "; ".join(errors) if errors else "확인"] + [str(value) if value is not None else "" for value in values]
                for column, text in enumerate(texts[:self.table.columnCount()]):
                    item = QTableWidgetItem(text)
                    if column == 1 and errors:
                        item.setForeground(QColor("#b42318"))
                    self.table.setItem(row_index, column, item)
            self.table.resizeColumnsToContents()
            self.status.setText(f"{len(rows)}개 행 중 오류 {error_count}개. 원본의 모든 열을 표시하며, 선택한 이름만 저장합니다.")
            self.apply_button.setEnabled(error_count == 0)
        except Exception as exc:
            self.invalidate()
            QMessageBox.warning(self, "미리보기 실패", str(exc))

    def apply(self):
        if not self.preview_rows:
            return
        if QMessageBox.question(self, "가져오기 확인", "미리보기의 이름을 가져오시겠습니까? 기존 항목은 유지하고 같은 이름은 다시 만들지 않습니다.") != QMessageBox.StandardButton.Yes:
            return
        if not self.parent().discard_period_changes():
            return
        try:
            counts = apply_import(self.db, self.term_id, self.preview_rows)
        except Exception as exc:
            QMessageBox.warning(self, "가져오기 실패", f"변경 사항을 저장하지 않았습니다.\n{exc}")
            return
        summary = ", ".join(f"{FIELDS[key]} {count}개" for key, count in counts.items())
        QMessageBox.information(self, "가져오기 완료", "새로 추가: " + summary)
        self.accept()


class TimetableImportDialog(QDialog):
    def __init__(self, parent, db, term_id):
        super().__init__(parent)
        self.db = db
        self.term_id = term_id
        self.path = None
        self.rows = []
        self.approved = None
        self.setWindowTitle("엑셀 시간표 불러오기")
        self.resize(1040, 600)
        box = QVBoxLayout(self)
        term_name = next((name for row_id, name in db.list("terms") if row_id == term_id), "")
        notice = QLabel(f"대상 학기 · {term_name}\n"
                        "배정 목록 또는 요일·반별 격자로 작성한 선행반 시간표의 시트를 선택하세요. "
                        "프로그램에서 내보낸 파일은 전체_배정목록 시트를 선택하세요.")
        notice.setTextFormat(Qt.TextFormat.PlainText)
        notice.setWordWrap(True)
        box.addWidget(notice)
        toolbar = QHBoxLayout()
        choose = QPushButton("엑셀 파일 선택")
        choose.clicked.connect(self.choose_file)
        toolbar.addWidget(choose)
        self.sheet = QComboBox()
        self.sheet.setAccessibleName("시간표가 들어 있는 시트")
        self.sheet.setPlaceholderText("시간표 시트 선택")
        toolbar.addWidget(self.sheet, 1)
        self.preview_button = QPushButton("미리보기")
        self.preview_button.clicked.connect(self.make_preview)
        toolbar.addWidget(self.preview_button)
        box.addLayout(toolbar)
        filters = QFormLayout()
        self.excluded_cohorts = QLineEdit()
        self.excluded_cohorts.setPlaceholderText("예: 508, 509")
        filters.addRow("제외할 반", self.excluded_cohorts)
        box.addLayout(filters)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.table = QTableWidget(0, len(COLUMNS) + 2)
        self.table.setAccessibleName("시간표 엑셀 미리보기")
        self.table.setHorizontalHeaderLabels(["엑셀 위치", "확인 결과", *COLUMNS])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        box.addWidget(self.table, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        self.apply_button = QPushButton("시간표에 추가")
        self.apply_button.clicked.connect(self.apply)
        actions.addWidget(self.apply_button)
        cancel = QPushButton("닫기")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        box.addLayout(actions)
        self.sheet.currentIndexChanged.connect(self.invalidate)
        self.excluded_cohorts.textChanged.connect(self.invalidate)
        self.invalidate()

    def invalidate(self):
        self.rows = []
        self.approved = None
        self.table.setRowCount(0)
        self.apply_button.setEnabled(False)
        self.preview_button.setEnabled(self.path is not None and self.sheet.currentIndex() >= 0)
        self.status.setText(f"{Path(self.path).name} · 시간표 시트를 선택한 뒤 미리보기를 누르세요."
                            if self.path else "엑셀 파일을 선택하세요.")

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "엑셀 파일 선택", "", "Excel 파일 (*.xlsx)")
        if not path:
            return
        try:
            sheets = sheet_names(path)
        except Exception as exc:
            QMessageBox.warning(self, "파일 열기 실패", str(exc))
            return
        self.path = path
        self.sheet.clear()
        self.sheet.addItems(sheets)
        self.sheet.setCurrentIndex(-1)
        self.invalidate()

    def make_preview(self):
        if not self.preview_button.isEnabled():
            return
        self.invalidate()
        try:
            excluded = [name.strip() for name in self.excluded_cohorts.text().split(",") if name.strip()]
            rows = read_timetable(self.path, self.sheet.currentText(), excluded)
            self.approved = preview_timetable(self.db, self.term_id, rows)
        except Exception as exc:
            self.status.setText(f"시트를 읽을 수 없습니다. {exc}")
            return
        self.rows = rows
        results = self.approved[1]
        self.table.setRowCount(len(rows))
        for i, (row, (action, detail)) in enumerate(zip(rows, results)):
            texts = [row.number, f"{action} · {detail}" if detail else action, *row.values]
            for column, value in enumerate(texts):
                item = QTableWidgetItem(str(value) if value is not None else "")
                item.setToolTip(item.text())
                if column == 1 and action == "오류":
                    item.setForeground(QColor("#b42318"))
                self.table.setItem(i, column, item)
        self.table.resizeColumnsToContents()
        added = sum(action == "추가" for action, _ in results)
        skipped = sum(action == "건너뜀" for action, _ in results)
        errors = len(results) - added - skipped
        self.status.setText(f"{self.approved[0]} · {self.sheet.currentText()} · 추가 {added}건 · 건너뜀 {skipped}건 · 오류 {errors}건")
        self.apply_button.setEnabled(added > 0 and errors == 0)

    def apply(self):
        if not self.apply_button.isEnabled() or not self.parent().discard_period_changes():
            return
        try:
            count = apply_timetable(self.db, self.term_id, self.rows, self.approved)
        except Exception as exc:
            self.invalidate()
            QMessageBox.warning(self, "시간표 저장 실패", str(exc))
            return
        QMessageBox.information(self, "시간표 불러오기 완료", f"{count}개 수업을 선택한 학기에 추가했습니다.")
        self.accept()
