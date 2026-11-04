from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .schedule import Schedule


DAYS = ("월", "화", "수", "목", "금")


class SchedulePage(QFrame):
    def __init__(self, db):
        super().__init__(objectName="card")
        self.db = db
        self.schedule = Schedule(db)
        self.term_id = None
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 18)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("반별 수동 시간표", objectName="cardTitle"))
        bar.addStretch()
        bar.addWidget(QLabel("반"))
        self.cohort = QComboBox()
        self.cohort.setAccessibleName("시간표 편집 반")
        self.cohort.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.cohort)
        box.addLayout(bar)
        box.addWidget(QLabel("먼저 과목별 주간 시수를 설정한 뒤 교시를 선택해 수업을 배정하세요.", objectName="muted"))
        splitter = QSplitter(Qt.Orientation.Vertical)
        box.addWidget(splitter, 1)

        quota_card = QFrame()
        quota_box = QVBoxLayout(quota_card)
        quota_box.setContentsMargins(0, 0, 0, 0)
        quota_bar = QHBoxLayout()
        quota_bar.addWidget(QLabel("과목별 주간 시수", objectName="cardTitle"))
        quota_bar.addStretch()
        for title, handler in (("시수 설정", self.edit_quota), ("시수 삭제", self.delete_quota)):
            button = QPushButton(title)
            button.clicked.connect(handler)
            quota_bar.addWidget(button)
        quota_box.addLayout(quota_bar)
        self.quota_table = QTableWidget(0, 4)
        self.quota_table.setHorizontalHeaderLabels(["과목", "목표 시수", "배정 / 잔여", "수업 길이"])
        self.quota_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.quota_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.quota_table.horizontalHeader().setStretchLastSection(True)
        self.quota_table.verticalHeader().setVisible(False)
        quota_box.addWidget(self.quota_table)
        splitter.addWidget(quota_card)

        grid_card = QFrame()
        grid_box = QVBoxLayout(grid_card)
        grid_box.setContentsMargins(0, 4, 0, 0)
        grid_bar = QHBoxLayout()
        grid_bar.addWidget(QLabel("주간 시간표", objectName="cardTitle"))
        grid_bar.addStretch()
        for title, handler in (("배정 / 수정", self.edit_lesson), ("잠금 / 해제", self.toggle_lock), ("수업 삭제", self.delete_lesson)):
            button = QPushButton(title)
            if title == "배정 / 수정":
                button.setObjectName("primary")
            button.clicked.connect(handler)
            grid_bar.addWidget(button)
        grid_box.addLayout(grid_bar)
        self.grid = QTableWidget(11, 5)
        self.grid.setAccessibleName("반별 주간 시간표")
        self.grid.setHorizontalHeaderLabels([day + "요일" for day in DAYS])
        self.grid.setVerticalHeaderLabels([f"{i}교시" for i in range(1, 12)])
        self.grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.grid.horizontalHeader().setSectionResizeMode(self.grid.horizontalHeader().ResizeMode.Stretch)
        self.grid.verticalHeader().setDefaultSectionSize(46)
        self.grid.cellDoubleClicked.connect(lambda row, column: self.edit_lesson())
        grid_box.addWidget(self.grid)
        splitter.addWidget(grid_card)
        splitter.setSizes([180, 360])

    def set_term(self, term_id):
        self.term_id = term_id
        current = self.cohort.currentData()
        self.cohort.blockSignals(True)
        self.cohort.clear()
        for row_id, name in self.db.list("cohorts", term_id):
            self.cohort.addItem(name, row_id)
        index = self.cohort.findData(current)
        if index >= 0:
            self.cohort.setCurrentIndex(index)
        self.cohort.blockSignals(False)
        self.refresh()

    def refresh(self):
        cohort_id = self.cohort.currentData()
        grid_row, grid_column = self.grid.currentRow(), self.grid.currentColumn()
        selected_subject = self.selected_quota()
        self.quota_table.setRowCount(0)
        for row, (subject_id, name, weekly, length, assigned, active) in enumerate(self.schedule.quotas(cohort_id)):
            self.quota_table.insertRow(row)
            for col, value in enumerate((name + (" (비활성)" if not active else ""), str(weekly), f"{assigned} / {weekly - assigned}", f"{length}교시")):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, subject_id)
                self.quota_table.setItem(row, col, item)
            if subject_id == selected_subject:
                self.quota_table.setCurrentCell(row, 0)
        self.grid.clearContents()
        for lesson in self.schedule.lessons(cohort_id):
            row_id, day, start, length, subject, teacher, room, locked, *_ = lesson
            text = f"{'🔒 ' if locked else ''}{subject}\n{teacher}" + (f" · {room}" if room else "")
            for period in range(start, start + length):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, row_id)
                item.setToolTip(f"{subject} · {teacher} · {room or '강의실 미배정'}\n{start}~{start + length - 1}교시" + (" · 잠김" if locked else ""))
                self.grid.setItem(period - 1, day, item)
        self.grid.setEnabled(cohort_id is not None)
        if grid_row >= 0 and grid_column >= 0:
            self.grid.setCurrentCell(grid_row, grid_column)

    def selected_quota(self):
        item = self.quota_table.item(self.quota_table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected_lesson(self):
        item = self.grid.currentItem()
        lesson_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((row for row in self.schedule.lessons(self.cohort.currentData()) if row[0] == lesson_id), None)

    def dialog(self, title):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog, form

    def edit_quota(self):
        if self.cohort.currentData() is None:
            QMessageBox.information(self, "반 선택", "학기와 반을 먼저 등록하고 선택하세요.")
            return
        dialog, form = self.dialog("주간 시수 설정")
        subjects = QComboBox()
        for subject_id, name, active in self.db.list("subjects"):
            if active:
                subjects.addItem(name, subject_id)
        if not subjects.count():
            QMessageBox.information(self, "과목 필요", "활성 과목을 먼저 등록하세요.")
            return
        chosen = self.selected_quota()
        index = subjects.findData(chosen)
        if index >= 0:
            subjects.setCurrentIndex(index)
        weekly = QSpinBox()
        weekly.setRange(1, 55)
        length = QComboBox()
        length.addItem("2교시 연강", 2)
        length.addItem("1교시", 1)
        def load_quota():
            row = next((q for q in self.schedule.quotas(self.cohort.currentData()) if q[0] == subjects.currentData()), None)
            default_length = 1 if subjects.currentText() == "영어" else 2
            value = row[3] if row else default_length
            length.setCurrentIndex(length.findData(value))
            weekly.setValue(row[2] if row else value)
        subjects.currentIndexChanged.connect(load_quota)
        load_quota()
        form.addRow("과목", subjects)
        form.addRow("주간 목표 교시", weekly)
        form.addRow("1회 수업 길이", length)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.schedule.save_quota(self.cohort.currentData(), subjects.currentData(), weekly.value(), length.currentData())
                self.refresh()
            except Exception as exc:
                QMessageBox.warning(self, "시수 저장 실패", str(exc))

    def delete_quota(self):
        subject_id = self.selected_quota()
        if subject_id is None:
            QMessageBox.information(self, "과목 선택", "시수 목록에서 과목을 선택하세요.")
            return
        if QMessageBox.question(self, "시수 삭제", "선택한 과목의 주간 시수를 삭제하시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.schedule.delete_quota(self.cohort.currentData(), subject_id)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "삭제 실패", str(exc))

    def edit_lesson(self):
        if self.cohort.currentData() is None or self.grid.currentRow() < 0:
            QMessageBox.information(self, "교시 선택", "반과 시간표의 교시를 먼저 선택하세요.")
            return
        lesson = self.selected_lesson()
        if lesson and lesson[7]:
            QMessageBox.information(self, "잠긴 수업", "수정하려면 먼저 잠금을 해제하세요.")
            return
        if lesson and not any(row[0] == lesson[8] and row[2] for row in self.db.list("subjects")):
            QMessageBox.information(self, "비활성 과목", "수업을 수정하려면 먼저 과목을 다시 활성화하세요.")
            return
        dialog, form = self.dialog("수업 배정 / 이동")
        subjects = QComboBox()
        for subject_id, name, weekly, length, assigned, active in self.schedule.quotas(self.cohort.currentData()):
            if active:
                subjects.addItem(f"{name} ({length}교시, 잔여 {weekly - assigned})", subject_id)
        teachers = QComboBox()
        for row_id, name in self.db.list("teachers"):
            teachers.addItem(name, row_id)
        rooms = QComboBox()
        rooms.addItem("미배정", None)
        for row_id, name in self.db.list("rooms"):
            rooms.addItem(name, row_id)
        if not subjects.count() or not teachers.count():
            QMessageBox.information(self, "기본 정보 필요", "활성 과목의 주간 시수와 강사를 먼저 등록하세요.")
            return
        days = QComboBox()
        for day in DAYS:
            days.addItem(day + "요일")
        start = QSpinBox()
        start.setRange(1, 11)
        if lesson:
            subjects.setCurrentIndex(subjects.findData(lesson[8]))
            subjects.setEnabled(False)
            teachers.setCurrentIndex(teachers.findData(lesson[9]))
            rooms.setCurrentIndex(rooms.findData(lesson[10]))
            days.setCurrentIndex(lesson[1])
            start.setValue(lesson[2])
        else:
            days.setCurrentIndex(self.grid.currentColumn())
            start.setValue(self.grid.currentRow() + 1)
        form.addRow("과목", subjects)
        form.addRow("강사", teachers)
        form.addRow("강의실", rooms)
        form.addRow("요일", days)
        form.addRow("시작 교시", start)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.schedule.assign(self.cohort.currentData(), subjects.currentData(), teachers.currentData(), rooms.currentData(), days.currentIndex(), start.value(), lesson[0] if lesson else None)
                self.refresh()
            except Exception as exc:
                QMessageBox.warning(self, "수업 저장 실패", str(exc))

    def toggle_lock(self):
        lesson = self.selected_lesson()
        if not lesson:
            QMessageBox.information(self, "수업 선택", "시간표에서 수업을 선택하세요.")
            return
        self.schedule.lock(lesson[0], not lesson[7])
        self.refresh()

    def delete_lesson(self):
        lesson = self.selected_lesson()
        if not lesson:
            QMessageBox.information(self, "수업 선택", "시간표에서 수업을 선택하세요.")
            return
        if QMessageBox.question(self, "수업 삭제", "선택한 수업 묶음 전체를 삭제하시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.schedule.delete(lesson[0])
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "삭제 실패", str(exc))


class TeacherLoadPage(QFrame):
    def __init__(self, db):
        super().__init__(objectName="card")
        self.db = db
        self.schedule = Schedule(db)
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 18)
        box.addWidget(QLabel("과목별 배정 시수표", objectName="cardTitle"))
        box.addWidget(QLabel("선택한 학기의 수동 배정 교시를 집계합니다. 연강 1회는 2시수로 계산합니다.", objectName="muted"))
        self.table = QTableWidget()
        self.table.setAccessibleName("강사별 과목 배정 시수")
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.table, 1)
        self.summary = QLabel(objectName="muted")
        box.addWidget(self.summary)

    def refresh(self, term_id):
        subjects = self.db.list("subjects")
        teachers = self.db.list("teachers")
        loads = {(teacher_id, subject_id): count for teacher_id, subject_id, count in self.schedule.teacher_loads(term_id)}
        self.table.clear()
        self.table.setColumnCount(len(subjects) + 2)
        self.table.setHorizontalHeaderLabels(["강사명"] + [name + (" (비활성)" if not active else "") for _, name, active in subjects] + ["합계"])
        self.table.setRowCount(len(teachers) + 1)
        for row, (teacher_id, name) in enumerate(teachers):
            values = [name] + [str(loads.get((teacher_id, subject_id), 0)) for subject_id, _, _ in subjects]
            values.append(str(sum(loads.get((teacher_id, subject_id), 0) for subject_id, _, _ in subjects)))
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        totals = ["합계"] + [str(sum(loads.get((teacher_id, subject_id), 0) for teacher_id, _ in teachers)) for subject_id, _, _ in subjects] + [str(sum(loads.values()))]
        for column, value in enumerate(totals):
            self.table.setItem(len(teachers), column, QTableWidgetItem(value))
        self.summary.setText(f"전체 강사 {len(teachers)}명 · 선택 학기 배정 {sum(loads.values())}시수")
