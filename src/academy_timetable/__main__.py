import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                               QFileDialog, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QStackedWidget, QTableWidget, QLineEdit, QFormLayout,
                               QTableWidgetItem, QVBoxLayout, QWidget)
from .backup_ui import BackupPage
from .db import CAPACITY_COLUMNS, FACILITY_COLUMNS, MAX_CAPACITY, Database, facility_tags
from .diagnostics import APP_VERSION, configure_logging, install_exception_hook
from .excel_export import export_timetable
from .help_ui import HelpDialog
from .import_ui import ImportDialog, TimetableImportDialog
from .review_ui import ReviewPage
from .schedule_ui import RoomAssignmentPage, SchedulePage, TeacherAvailabilityPage, TeacherLoadPage
from .update_ui import UpdateDialog


STYLE = """
QMainWindow, QWidget#content { background: #f3f6fa; color: #19283d; }
QFrame#sidebar, QWidget#sideContent, QScrollArea#sideScroll { background: #29384e; }
QScrollArea#sideScroll { border: none; }
QLabel#brand { color: white; font-size: 18px; font-weight: bold; }
QLabel#sideSection { color: #a7b6ca; font-size: 12px; font-weight: bold; padding: 12px 12px 3px; }
QPushButton#sideButton { background: transparent; border: none; border-radius: 7px; color: #e5edf7;
    text-align: left; padding: 10px 14px; font-size: 14px; }
QPushButton#sideButton:hover { background: #3b4c65; }
QPushButton#sideButton:checked { background: #2878e7; color: white; font-weight: bold; }
QLabel#eyebrow { color: #738399; font-size: 12px; font-weight: bold; }
QLabel#heading { color: #17263c; font-size: 25px; font-weight: bold; }
QLabel#description, QLabel#muted { color: #718198; font-size: 13px; }
QLabel#cardTitle { color: #1b2c44; font-size: 16px; font-weight: bold; }
QLabel#metricValue { color: #182c49; font-size: 23px; font-weight: bold; }
QFrame#card { background: white; border: 1px solid #dce4ef; border-radius: 10px; }
QPushButton { background: #ffffff; border: 1px solid #cad5e4; border-radius: 6px;
    color: #263a56; padding: 8px 15px; font-size: 13px; }
QPushButton:hover { background: #f0f6ff; border-color: #96b8ed; }
QPushButton#primary { background: #216de0; border-color: #216de0; color: white; font-weight: bold; }
QPushButton#primary:hover { background: #155ecb; }
QComboBox { background: white; border: 1px solid #cad5e4; border-radius: 6px;
    padding: 7px 26px 7px 10px; min-width: 130px; color: #263a56; }
QListWidget, QTableWidget { background: white; border: 1px solid #dce4ef; border-radius: 6px;
    color: #20324b; font-size: 14px; alternate-background-color: #f8faff;
    selection-background-color: #e4efff; selection-color: #173d79; }
QListWidget::item { padding: 11px 12px; border-bottom: 1px solid #edf1f6; }
QHeaderView::section { background: #e5effc; color: #283e5e; border: none;
    border-right: 1px solid #d4e0ee; border-bottom: 1px solid #d4e0ee; padding: 8px; font-weight: bold; }
QTableWidget { gridline-color: #e3eaf2; }
QStatusBar { background: #f3f6fa; color: #718198; }
"""


class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.period_dirty = False
        self.previous_term = None
        self.setWindowTitle(f"학원 시간표 관리 v{APP_VERSION}")
        self.resize(1180, 760)
        self.setMinimumSize(800, 560)
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(206)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.side_scroll = QScrollArea(objectName="sideScroll")
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_content = QWidget(objectName="sideContent")
        side = QVBoxLayout(side_content)
        side.setContentsMargins(10, 20, 10, 16)
        brand = QLabel("▦  학원 시간표", objectName="brand")
        side.addWidget(brand)
        side.addSpacing(22)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.pages = QStackedWidget()
        self.page_info = [
            ("terms", "학기 관리", "학기별 운영 정보를 등록하고 관리합니다."),
            ("cohorts", "과목별 반 설정", "교과 단위 또는 등록 과목 단위를 선택하여 국어 A, 수학 A 등의 반을 관리합니다."),
            ("teachers", "강사 관리", "등록된 강사를 확인하고 관리합니다."),
            ("subjects", "과목 관리", "과목을 등록하고 활성 상태를 관리합니다."),
            ("rooms", "강의실 관리", "수업에 사용할 강의실을 관리합니다."),
            ("periods", "교시·시간 설정", "선택한 학기의 월~토 공통 교시 시간을 설정합니다."),
            ("schedule", "시간표 편집", "과목 시수를 설정하고 반별 수업을 수동으로 배정합니다."),
            ("teacher_load", "강사 시수 관리", "강사별 과목 배정 시수를 확인합니다."),
            ("availability", "강사 가능 시간", "학기별 강사 가능 시간을 설정합니다."),
            ("review", "초안 검토", "저장된 시간표의 시수와 기본 충돌을 확인합니다."),
            ("room_assignment", "강의실 배정", "강의실을 직접 지정하거나 미배정 수업의 자동 제안을 확인합니다."),
            ("backup", "백업·복원", "저장된 데이터를 백업하거나 복원합니다."),
        ]
        self.lists = {}
        for index, (table, title, description) in enumerate(self.page_info):
            if index in (0, 5, 6):
                side.addWidget(QLabel({0: "기초정보 관리", 5: "운영 설정", 6: "시간표 편성"}[index], objectName="sideSection"))
            button = QPushButton(title, objectName="sideButton")
            button.setMinimumHeight(38)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            self.nav.addButton(button, index)
            side.addWidget(button)
            if table == "periods":
                self.pages.addWidget(self.make_period_page())
            elif table == "schedule":
                self.schedule_page = SchedulePage(db)
                self.pages.addWidget(self.schedule_page)
            elif table == "teacher_load":
                self.teacher_load_page = TeacherLoadPage(db)
                self.pages.addWidget(self.teacher_load_page)
            elif table == "availability":
                self.availability_page = TeacherAvailabilityPage(db)
                self.pages.addWidget(self.availability_page)
            elif table == "review":
                self.review_page = ReviewPage(db)
                self.pages.addWidget(self.review_page)
            elif table == "room_assignment":
                self.room_assignment_page = RoomAssignmentPage(db)
                self.pages.addWidget(self.room_assignment_page)
            elif table == "backup":
                self.pages.addWidget(BackupPage(db, self))
            else:
                self.pages.addWidget(self.make_list_page(table, title))
        side.addStretch()
        side.addWidget(QLabel("로컬 데이터 · 개발 초기 버전", objectName="sideSection"))
        self.side_scroll.setWidget(side_content)
        sidebar_layout.addWidget(self.side_scroll)
        layout.addWidget(sidebar)

        content = QWidget(objectName="content")
        layout.addWidget(content, 1)
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 22, 24, 18)
        body.setSpacing(14)
        top = QHBoxLayout()
        top.addWidget(QLabel("시간표 관리", objectName="eyebrow"))
        top.addStretch()
        import_button = QPushButton("엑셀 가져오기")
        import_menu = QMenu(import_button)
        import_menu.addAction("기본 정보 가져오기").triggered.connect(self.import_excel)
        import_menu.addAction("시간표 불러오기").triggered.connect(self.import_timetable)
        import_button.setMenu(import_menu)
        top.addWidget(import_button)
        export_button = QPushButton("엑셀 내보내기")
        export_button.clicked.connect(self.export_excel)
        top.addWidget(export_button)
        top.addWidget(QLabel("학기", objectName="muted"))
        self.term = QComboBox()
        self.term.setAccessibleName("선택 학기")
        self.term.currentIndexChanged.connect(self.change_term)
        top.addWidget(self.term)
        body.addLayout(top)

        heading = QHBoxLayout()
        heading_text = QVBoxLayout()
        self.heading = QLabel(objectName="heading")
        self.description = QLabel(objectName="description")
        self.description.setWordWrap(True)
        heading_text.addWidget(self.heading)
        heading_text.addWidget(self.description)
        heading.addLayout(heading_text, 1)
        self.help_dialog = HelpDialog(self)
        update_button = QPushButton("업데이트")
        update_button.setAccessibleName("프로그램 업데이트")
        update_button.clicked.connect(self.show_update)
        heading.addWidget(update_button, alignment=Qt.AlignmentFlag.AlignTop)
        help_button = QPushButton("사용 방법")
        help_button.clicked.connect(self.show_help)
        heading.addWidget(help_button, alignment=Qt.AlignmentFlag.AlignTop)
        body.addLayout(heading)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.metrics = {}
        for key, label in (("terms", "전체 학기"), ("cohorts", "선택 학기 반"),
                           ("teachers", "전체 강사"), ("subjects", "활성 과목")):
            card = QFrame(objectName="card")
            card_box = QVBoxLayout(card)
            card_box.setContentsMargins(16, 12, 16, 12)
            card_box.addWidget(QLabel(label, objectName="muted"))
            value = QLabel("0", objectName="metricValue")
            self.metrics[key] = value
            card_box.addWidget(value)
            cards.addWidget(card, 1)
        body.addLayout(cards)
        body.addWidget(self.pages, 1)
        self.statusBar().showMessage("수동 시간표 편집 · 강의실 자동 제안 · 초안 검토")
        self.refresh_all()
        self.show_page(2)

    def show_update(self):
        if self.period_dirty:
            QMessageBox.information(self, "교시표 저장", "교시표 변경을 먼저 저장한 뒤 업데이트하세요.")
            return
        dialog = UpdateDialog(self, self.db)
        self.update_dialog = dialog
        try:
            dialog.exec()
        finally:
            self.update_dialog = None
        if dialog.install_started and self.close():
            QApplication.instance().quit()

    def show_help(self):
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def export_excel(self):
        if self.term.currentData() is None:
            QMessageBox.information(self, "학기 선택", "먼저 학기를 선택하세요.")
            return
        if self.period_dirty and QMessageBox.question(
            self, "저장되지 않은 교시표", "교시표에 저장되지 않은 변경이 있습니다. 마지막으로 저장한 시간으로 내보내시겠습니까?"
        ) != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(self, "시간표 초안 엑셀 저장", "시간표_초안.xlsx",
                                               "Excel 파일 (*.xlsx)", options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        if not Path(path).suffix:
            path += ".xlsx"
        if Path(path).suffix.lower() != ".xlsx":
            QMessageBox.warning(self, "저장 실패", "파일 확장자는 .xlsx여야 합니다.")
            return
        if os.path.lexists(path) and QMessageBox.question(self, "파일 덮어쓰기", "같은 이름의 파일이 있습니다. 덮어쓰시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        try:
            export_timetable(self.db, self.term.currentData(), path)
            QMessageBox.information(self, "저장 완료", "시간표 초안을 엑셀 파일로 저장했습니다.")
        except Exception as exc:
            QMessageBox.warning(self, "저장 실패", f"엑셀 파일을 저장하지 못했습니다.\n{exc}")

    def import_excel(self):
        dialog = ImportDialog(self, self.db, self.term.currentData())
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.refresh_all()

    def import_timetable(self):
        term_id = self.term.currentData()
        if term_id is None:
            QMessageBox.information(self, "학기 선택", "시간표를 추가할 학기를 먼저 선택하세요.")
            return
        dialog = TimetableImportDialog(self, self.db, term_id)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.refresh_all()
            self.show_page(self.pages.indexOf(self.schedule_page))

    def make_list_page(self, table, title):
        card = QFrame(objectName="card")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 18)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(title + " 목록", objectName="cardTitle"))
        toolbar.addStretch()
        actions = [("+ 추가", "add"), ("이름 수정", "rename")]
        if table == "cohorts":
            actions.append(("반 기준 설정", "scope"))
        if table in CAPACITY_COLUMNS:
            actions.append(("인원 설정" if table == "cohorts" else "정원 설정", "capacity"))
        if table in FACILITY_COLUMNS:
            actions.append(("시설 설정", "facilities"))
        actions.append(("활성/비활성" if table == "subjects" else "삭제", "remove"))
        for label, action in actions:
            button = QPushButton(label)
            if action == "add":
                button.setObjectName("primary")
            button.clicked.connect(lambda checked=False, t=table, a=action: self.edit(t, a))
            toolbar.addWidget(button)
        box.addLayout(toolbar)
        options = QHBoxLayout()
        options.addWidget(QLabel("항목을 선택하여 수정하거나 관리할 수 있습니다.", objectName="muted"), 1)
        if table == "subjects":
            area_button = QPushButton("교과 설정")
            area_button.clicked.connect(lambda: self.edit("subjects", "area"))
            options.addWidget(area_button)
            button = QPushButton("담당 강사 설정")
            button.clicked.connect(lambda: self.edit("subjects", "eligible_teachers"))
            options.addWidget(button)
        box.addLayout(options)
        listing = QListWidget()
        listing.setAccessibleName(title + " 목록")
        listing.setAlternatingRowColors(True)
        self.lists[table] = listing
        box.addWidget(listing, 1)
        return card

    def make_period_page(self):
        card = QFrame(objectName="card")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 18)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("교시 시간표", objectName="cardTitle"))
        toolbar.addStretch()
        save = QPushButton("교시표 저장", objectName="primary")
        save.clicked.connect(self.save_periods)
        toolbar.addWidget(save)
        box.addLayout(toolbar)
        box.addWidget(QLabel("시작과 종료 시각을 HH:MM 형식으로 입력하세요.", objectName="muted"))
        self.period_table = QTableWidget(11, 2)
        self.period_table.setAccessibleName("교시별 시작 및 종료 시간")
        self.period_table.itemChanged.connect(self.mark_period_dirty)
        self.period_table.setHorizontalHeaderLabels(["시작", "종료"])
        self.period_table.setVerticalHeaderLabels([f"{i}교시" for i in range(1, 12)])
        self.period_table.horizontalHeader().setStretchLastSection(True)
        self.period_table.horizontalHeader().setSectionResizeMode(0, self.period_table.horizontalHeader().ResizeMode.Stretch)
        self.period_table.setAlternatingRowColors(True)
        box.addWidget(self.period_table, 1)
        return card

    def show_page(self, index):
        try:
            self.db.assert_current()
        except ValueError as exc:
            self.nav.button(self.pages.currentIndex()).setChecked(True)
            QMessageBox.warning(self, "데이터 변경", str(exc))
            return
        if self.page_info[index][0] == "teacher_load":
            self.teacher_load_page.refresh(self.term.currentData())
        elif self.page_info[index][0] == "availability":
            self.availability_page.set_term(self.term.currentData())
        elif self.page_info[index][0] == "review":
            self.review_page.set_term(self.term.currentData())
        elif self.page_info[index][0] == "room_assignment":
            self.room_assignment_page.set_term(self.term.currentData())
        elif self.page_info[index][0] == "schedule":
            self.schedule_page.refresh()
        self.pages.setCurrentIndex(index)
        self.nav.button(index).setChecked(True)
        self.side_scroll.ensureWidgetVisible(self.nav.button(index))
        self.heading.setText(self.page_info[index][1])
        self.description.setText(self.page_info[index][2])

    def refresh_metrics(self):
        for table, value in self.metrics.items():
            rows = self.db.list(table, self.term.currentData())
            count = sum(row[2] for row in rows) if table == "subjects" else len(rows)
            value.setText(f"{count}개" if table != "teachers" else f"{count}명")

    def refresh_all(self, selected=None):
        current = selected if selected is not None else self.term.currentData()
        self.term.blockSignals(True)
        self.term.clear()
        for row_id, name in self.db.list("terms"):
            self.term.addItem(name, row_id)
        index = self.term.findData(current)
        if index >= 0:
            self.term.setCurrentIndex(index)
        self.term.blockSignals(False)
        for table in self.lists:
            self.refresh_list(table)
        self.refresh_term()

    def refresh_list(self, table):
        listing = self.lists[table]
        listing.clear()
        capacities = self.db.capacity_values(table) if table in CAPACITY_COLUMNS else {}
        facilities = self.db.facility_values(table) if table in FACILITY_COLUMNS else {}
        for row in self.db.list(table, self.term.currentData()):
            text = row[1] + (" (비활성)" if table == "subjects" and not row[2] else "")
            if table == "cohorts":
                kind, target = self.db.cohort_scope(row[0])
                text += " · " + ({"AREA": "교과 단위", "SUBJECT": "등록 과목 단위", "COMMON": "공통 반"}[kind])
                if target:
                    text += f" ({target})"
            if table in CAPACITY_COLUMNS:
                field = "인원" if table == "cohorts" else "정원"
                value = capacities.get(row[0])
                display = f"{value}명" if value is not None else "미설정"
                text += f" · {field} {display}"
            if table in FACILITY_COLUMNS:
                field = "필수 시설" if table == "subjects" else "보유 시설"
                display = ", ".join(facility_tags(facilities.get(row[0], ""))) or "등록 없음"
                text += f" · {field} {display}"
            if table == "subjects":
                text += f" · 교과 {self.db.subject_area(row[0]) or '미설정'}"
                count = len(self.db.eligible_teachers(row[0]))
                display = f"{count}명" if count else "미설정"
                text += f" · 담당 강사 {display}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, row[0])
            listing.addItem(item)

    def mark_period_dirty(self):
        self.period_dirty = True

    def discard_period_changes(self):
        return not self.period_dirty or QMessageBox.question(
            self, "저장되지 않은 교시표", "교시표 변경을 저장하지 않고 버리시겠습니까?"
        ) == QMessageBox.StandardButton.Yes

    def change_term(self):
        try:
            self.db.assert_current()
        except ValueError as exc:
            self.term.blockSignals(True)
            self.term.setCurrentIndex(self.term.findData(self.previous_term))
            self.term.blockSignals(False)
            QMessageBox.warning(self, "데이터 변경", str(exc))
            return
        if not self.discard_period_changes():
            self.term.blockSignals(True)
            self.term.setCurrentIndex(self.term.findData(self.previous_term))
            self.term.blockSignals(False)
            return
        self.refresh_term()

    def closeEvent(self, event):
        update = getattr(self, "update_dialog", None)
        if update is not None and update.worker is not None:
            update.reject()
            event.ignore()
            return
        if self.discard_period_changes():
            event.accept()
        else:
            event.ignore()

    def refresh_term(self):
        self.previous_term = self.term.currentData()
        self.period_table.blockSignals(True)
        self.refresh_list("cohorts")
        rows = self.db.periods(self.term.currentData())
        self.period_table.clearContents()
        for i, (start, end) in enumerate(rows):
            self.period_table.setItem(i, 0, QTableWidgetItem(start))
            self.period_table.setItem(i, 1, QTableWidgetItem(end))
        self.period_table.setEnabled(bool(rows))
        self.period_table.blockSignals(False)
        self.period_dirty = False
        self.refresh_metrics()
        self.schedule_page.set_term(self.term.currentData())
        self.teacher_load_page.refresh(self.term.currentData())
        self.availability_page.set_term(self.term.currentData())
        self.review_page.set_term(self.term.currentData())
        self.room_assignment_page.set_term(self.term.currentData())

    def edit_eligible_teachers(self, subject_id):
        teachers = self.db.list("teachers")
        if not teachers:
            QMessageBox.information(self, "강사 필요", "강사 관리에서 강사를 먼저 등록하세요.")
            return False
        current = self.db.eligible_teachers(subject_id)
        dialog = QDialog(self)
        dialog.setWindowTitle("과목별 담당 강사 설정")
        dialog.resize(420, 360)
        layout = QVBoxLayout(dialog)
        hint = QLabel("선택한 강사만 해당 과목에 배정할 수 있습니다. 모두 해제하면 등록된 강사 중에서 수동 배정할 수 있습니다. 모든 학기에 적용됩니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        listing = QListWidget()
        listing.setAccessibleName("과목별 담당 강사 선택")
        for teacher_id, name in teachers:
            item = QListWidgetItem(name, listing)
            item.setData(Qt.ItemDataRole.UserRole, teacher_id)
            item.setCheckState(Qt.CheckState.Checked if teacher_id in current else Qt.CheckState.Unchecked)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        selected = {listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(listing.count())
                    if listing.item(i).checkState() == Qt.CheckState.Checked}
        self.db.set_eligible_teachers(subject_id, selected, expected=current)
        return True

    def edit_cohort(self, cohort_id=None):
        term_id = self.term.currentData()
        if term_id is None:
            raise ValueError("학기를 먼저 등록하고 선택하세요.")
        name = next((name for row_id, name in self.db.list("cohorts", term_id) if row_id == cohort_id), "")
        kind, target = self.db.cohort_scope(cohort_id)
        expected = (name, kind, target) if cohort_id is not None else None
        dialog = QDialog(self)
        dialog.setWindowTitle("과목별 반 설정")
        layout = QVBoxLayout(dialog)
        hint = QLabel("반 이름은 학기 안에서 중복할 수 없습니다. 교과 단위는 해당 교과의 과목을, 등록 과목 단위는 선택한 한 과목만 배정합니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        name_input = QLineEdit(name)
        name_input.setAccessibleName("반 이름")
        name_input.setPlaceholderText("국어 A, 수학 A, 문학 A")
        scope = QComboBox()
        scope.setAccessibleName("반 구분")
        for label, value in (("교과 단위", "AREA"), ("등록 과목 단위", "SUBJECT"), ("공통 반", "COMMON")):
            scope.addItem(label, value)
        scope.setCurrentIndex(scope.findData(kind if cohort_id is not None else "AREA"))
        basis = QComboBox()
        basis.setAccessibleName("반 기준")

        def update_basis():
            basis.clear()
            selected = scope.currentData()
            basis.setEditable(selected == "AREA")
            basis.setEnabled(selected != "COMMON")
            table = "subject_areas" if selected == "AREA" else "subjects"
            if selected != "COMMON":
                basis.addItems([row[1] for row in self.db.list(table)])
            if selected == kind and target:
                basis.setCurrentText(target)

        scope.currentIndexChanged.connect(update_basis)
        update_basis()
        form.addRow("반 이름", name_input)
        form.addRow("반 구분", scope)
        form.addRow("교과 / 등록 과목", basis)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.db.save_cohort(term_id, name_input.text(), scope.currentData(), basis.currentText(),
                            cohort_id=cohort_id, expected=expected)
        return True

    def edit(self, table, action):
        if not self.discard_period_changes():
            return
        item = self.lists[table].currentItem()
        if action != "add" and item is None:
            QMessageBox.information(self, "항목 선택", "먼저 항목을 선택하세요.")
            return
        row_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        try:
            if table == "cohorts" and action in ("add", "scope"):
                if not self.edit_cohort(None if action == "add" else row_id):
                    return
            elif action == "area":
                current = self.db.subject_area(row_id) or ""
                names = [row[1] for row in self.db.list("subject_areas")]
                choices = [""] + names
                value, ok = QInputDialog.getItem(self, "교과 설정", "교과 이름 (예: 국어, 수학 / 빈칸은 미설정). 모든 학기에 적용됩니다.",
                                                choices, choices.index(current), True)
                if not ok:
                    return
                self.db.set_subject_area(row_id, value.strip() or None)
            elif action in ("add", "rename"):
                default = "" if action == "add" else next(row[1] for row in self.db.list(table, self.term.currentData()) if row[0] == row_id)
                name, ok = QInputDialog.getText(self, "이름 입력", "이름:", text=default)
                if not ok:
                    return
                if action == "add":
                    self.db.add(table, name, self.term.currentData())
                else:
                    self.db.rename(table, row_id, name)
            elif action == "capacity":
                field = "반 인원" if table == "cohorts" else "강의실 정원"
                current = self.db.capacity_values(table).get(row_id)
                value, ok = QInputDialog.getInt(self, f"{field} 설정", f"{field} (0은 미설정)", current or 0, 0, MAX_CAPACITY)
                if not ok:
                    return
                self.db.set_capacity(table, row_id, value or None)
            elif action == "facilities":
                field = "필수 시설" if table == "subjects" else "보유 시설"
                current = self.db.facility_values(table).get(row_id, "")
                value, ok = QInputDialog.getMultiLineText(self, f"{field} 설정", "시설 이름을 줄바꿈이나 쉼표로 구분하세요.", current)
                if not ok:
                    return
                self.db.set_facilities(table, row_id, value)
            elif action == "eligible_teachers":
                if not self.edit_eligible_teachers(row_id):
                    return
            else:
                message = "선택한 항목을 삭제하시겠습니까?"
                if table == "terms":
                    message = "학기를 삭제하면 해당 학기의 반, 교시표, 강사 가능 시간도 삭제됩니다. 시수나 수업이 있으면 삭제할 수 없습니다. 계속하시겠습니까?"
                elif table == "subjects":
                    message = "선택한 과목의 활성 상태를 변경하시겠습니까?"
                elif table == "teachers":
                    message = "강사를 삭제하면 가능 시간과 과목의 담당 강사 설정에서도 삭제됩니다. 수업에 배정된 강사는 삭제할 수 없습니다. 계속하시겠습니까?"
                if QMessageBox.question(self, "확인", message) != QMessageBox.StandardButton.Yes:
                    return
                self.db.remove(table, row_id)
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "저장 실패", f"이름 중복이나 입력값을 확인하세요. 시수나 수업에 사용 중인 항목은 먼저 연결을 해제해야 합니다.\n{exc}")

    def save_periods(self):
        try:
            periods = [(self.period_table.item(i, 0).text() if self.period_table.item(i, 0) else "",
                        self.period_table.item(i, 1).text() if self.period_table.item(i, 1) else "") for i in range(11)]
            self.db.save_periods(self.term.currentData(), periods)
            self.availability_page.set_term(self.term.currentData())
            self.period_dirty = False
            self.statusBar().showMessage("교시표를 저장했습니다.", 5000)
        except Exception as exc:
            QMessageBox.warning(self, "저장 실패", str(exc))


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("AcademyTimetable")
    app.setApplicationName("AcademyTimetable")
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    log_path = None
    try:
        log_path = configure_logging(data_dir)
        db = Database(data_dir / "academy-timetable.sqlite3")
    except Exception as exc:
        logging.getLogger(__name__).exception("앱을 시작하지 못했습니다.")
        detail = f"\n오류 로그: {log_path}" if log_path else "\n로그 파일을 만들지 못했습니다."
        QMessageBox.critical(None, "시작 오류", str(exc) + detail)
        return 1
    previous_hook = install_exception_hook(log_path)
    try:
        window = MainWindow(db)
        window.show()
        return app.exec()
    except Exception:
        sys.excepthook(*sys.exc_info())
        return 1
    finally:
        sys.excepthook = previous_hook
        db.conn.close()


if __name__ == "__main__":
    sys.exit(main())
