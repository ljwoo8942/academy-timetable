import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)
from .db import Database
from .schedule_ui import SchedulePage, TeacherAvailabilityPage, TeacherLoadPage


STYLE = """
QMainWindow, QWidget#content { background: #f3f6fa; color: #19283d; }
QFrame#sidebar { background: #29384e; }
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
        self.setWindowTitle("학원 시간표 관리")
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
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 20, 10, 16)
        brand = QLabel("▦  학원 시간표", objectName="brand")
        side.addWidget(brand)
        side.addSpacing(22)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.pages = QStackedWidget()
        self.page_info = [
            ("terms", "학기 관리", "학기별 운영 정보를 등록하고 관리합니다."),
            ("cohorts", "반 관리", "선택한 학기의 반을 등록하고 관리합니다."),
            ("teachers", "강사 관리", "등록된 강사를 확인하고 관리합니다."),
            ("subjects", "과목 관리", "과목을 등록하고 활성 상태를 관리합니다."),
            ("rooms", "강의실 관리", "수업에 사용할 강의실을 관리합니다."),
            ("periods", "교시·시간 설정", "선택한 학기의 월~금 공통 교시 시간을 설정합니다."),
            ("schedule", "시간표 편집", "과목 시수를 설정하고 반별 수업을 수동으로 배정합니다."),
            ("teacher_load", "강사 시수 관리", "강사별 과목 배정 시수를 확인합니다."),
            ("availability", "강사 가능 시간", "학기별 강사 가능 시간을 설정합니다."),
        ]
        self.lists = {}
        for index, (table, title, description) in enumerate(self.page_info):
            if index in (0, 5, 6):
                side.addWidget(QLabel({0: "기초정보 관리", 5: "운영 설정", 6: "시간표 편성"}[index], objectName="sideSection"))
            button = QPushButton(title, objectName="sideButton")
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
            else:
                self.pages.addWidget(self.make_list_page(table, title))
        side.addStretch()
        side.addWidget(QLabel("로컬 데이터 · 개발 초기 버전", objectName="sideSection"))
        layout.addWidget(sidebar)

        content = QWidget(objectName="content")
        layout.addWidget(content, 1)
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 22, 24, 18)
        body.setSpacing(14)
        top = QHBoxLayout()
        top.addWidget(QLabel("ACADEMY  /  시간표 관리", objectName="eyebrow"))
        top.addStretch()
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
        heading_text.addWidget(self.heading)
        heading_text.addWidget(self.description)
        heading.addLayout(heading_text)
        heading.addStretch()
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
        self.statusBar().showMessage("수동 편성: 반·강사·강의실 중복과 강사 불가 시간 검사 · 교과별 규칙·자동 편성·확정은 미지원")
        self.refresh_all()
        self.show_page(2)

    def make_list_page(self, table, title):
        card = QFrame(objectName="card")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 18)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(title + " 목록", objectName="cardTitle"))
        toolbar.addStretch()
        for label, action in (("+ 추가", "add"), ("이름 수정", "rename"),
                              ("활성/비활성" if table == "subjects" else "삭제", "remove")):
            button = QPushButton(label)
            if action == "add":
                button.setObjectName("primary")
            button.clicked.connect(lambda checked=False, t=table, a=action: self.edit(t, a))
            toolbar.addWidget(button)
        box.addLayout(toolbar)
        box.addWidget(QLabel("항목을 선택하여 수정하거나 관리할 수 있습니다.", objectName="muted"))
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
        if self.page_info[index][0] == "teacher_load":
            self.teacher_load_page.refresh(self.term.currentData())
        elif self.page_info[index][0] == "availability":
            self.availability_page.set_term(self.term.currentData())
        self.pages.setCurrentIndex(index)
        self.nav.button(index).setChecked(True)
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
        for row in self.db.list(table, self.term.currentData()):
            item = QListWidgetItem(row[1] + (" (비활성)" if table == "subjects" and not row[2] else ""))
            item.setData(Qt.ItemDataRole.UserRole, row[0])
            listing.addItem(item)

    def mark_period_dirty(self):
        self.period_dirty = True

    def discard_period_changes(self):
        return not self.period_dirty or QMessageBox.question(
            self, "저장되지 않은 교시표", "교시표 변경을 저장하지 않고 버리시겠습니까?"
        ) == QMessageBox.StandardButton.Yes

    def change_term(self):
        if not self.discard_period_changes():
            self.term.blockSignals(True)
            self.term.setCurrentIndex(self.term.findData(self.previous_term))
            self.term.blockSignals(False)
            return
        self.refresh_term()

    def closeEvent(self, event):
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

    def edit(self, table, action):
        if not self.discard_period_changes():
            return
        item = self.lists[table].currentItem()
        if action != "add" and item is None:
            QMessageBox.information(self, "항목 선택", "먼저 항목을 선택하세요.")
            return
        row_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        try:
            if action in ("add", "rename"):
                default = "" if action == "add" else next(row[1] for row in self.db.list(table, self.term.currentData()) if row[0] == row_id)
                name, ok = QInputDialog.getText(self, "이름 입력", "이름:", text=default)
                if not ok:
                    return
                if action == "add":
                    self.db.add(table, name, self.term.currentData())
                else:
                    self.db.rename(table, row_id, name)
            else:
                message = "선택한 항목을 삭제하시겠습니까?"
                if table == "terms":
                    message = "학기를 삭제하면 해당 학기의 반, 교시표, 강사 가능 시간도 삭제됩니다. 시수나 수업이 있으면 삭제할 수 없습니다. 계속하시겠습니까?"
                elif table == "subjects":
                    message = "선택한 과목의 활성 상태를 변경하시겠습니까?"
                elif table == "teachers":
                    message = "강사를 삭제하면 저장된 가능 시간도 삭제됩니다. 수업에 배정된 강사는 삭제할 수 없습니다. 계속하시겠습니까?"
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
    try:
        db = Database(data_dir / "academy-timetable.sqlite3")
    except Exception as exc:
        QMessageBox.critical(None, "데이터베이스 오류", str(exc))
        return 1
    window = MainWindow(db)
    window.show()
    result = app.exec()
    db.conn.close()
    return result


if __name__ == "__main__":
    sys.exit(main())
