from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .db import DAYS, facility_tags
from .schedule import Schedule


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
        self.grid = QTableWidget(11, len(DAYS))
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
        allowed = self.db.allowed_subject_ids(self.cohort.currentData())
        for subject_id, name, active in self.db.list("subjects"):
            if active and (allowed is None or subject_id in allowed):
                subjects.addItem(name, subject_id)
        if not subjects.count():
            QMessageBox.information(self, "과목 필요", "반 기준에 맞는 활성 과목이 없습니다. 과목 관리의 교과 설정과 반 기준을 확인하세요.")
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
        subjects.setAccessibleName("배정 과목")
        for subject_id, name, weekly, length, assigned, active in self.schedule.quotas(self.cohort.currentData()):
            if active:
                subjects.addItem(f"{name} ({length}교시, 잔여 {weekly - assigned})", subject_id)
        teachers = QComboBox()
        teachers.setAccessibleName("배정 강사")
        teachers.setPlaceholderText("담당 강사 선택")
        teacher_rows = self.db.list("teachers")
        rooms = QComboBox()
        rooms.addItem("미배정", None)
        capacities = self.db.capacity_values("rooms")
        for row_id, name in self.db.list("rooms"):
            capacity = capacities.get(row_id)
            display = f"{capacity}명" if capacity is not None else "미설정"
            rooms.addItem(f"{name} · 정원 {display}", row_id)
        if not subjects.count() or not teacher_rows:
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
            rooms.setCurrentIndex(rooms.findData(lesson[10]))
            days.setCurrentIndex(lesson[1])
            start.setValue(lesson[2])
        else:
            days.setCurrentIndex(self.grid.currentColumn())
            start.setValue(self.grid.currentRow() + 1)

        def refresh_teachers():
            current = lesson[9] if lesson else teachers.currentData()
            eligible = self.db.eligible_teachers(subjects.currentData())
            teachers.clear()
            for teacher_id, name in teacher_rows:
                if not eligible or teacher_id in eligible:
                    teachers.addItem(name, teacher_id)
            teachers.setCurrentIndex(0 if current is None else teachers.findData(current))

        subjects.currentIndexChanged.connect(refresh_teachers)
        refresh_teachers()
        form.addRow("과목", subjects)
        form.addRow("강사", teachers)
        form.addRow("강의실", rooms)
        form.addRow("요일", days)
        form.addRow("시작 교시", start)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.schedule.assign(self.cohort.currentData(), subjects.currentData(), teachers.currentData(), rooms.currentData(), days.currentIndex(), start.value(), lesson[0] if lesson else None, expected=lesson)
            except Exception as exc:
                QMessageBox.warning(self, "수업 저장 실패", str(exc))
            self.refresh()

    def toggle_lock(self):
        lesson = self.selected_lesson()
        if not lesson:
            QMessageBox.information(self, "수업 선택", "시간표에서 수업을 선택하세요.")
            return
        try:
            self.schedule.lock(lesson[0], not lesson[7])
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "잠금 변경 실패", str(exc))

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


class RoomAssignmentPage(QFrame):
    COLUMNS = ("요일·교시", "반", "과목", "강사", "강의실")

    def __init__(self, db):
        super().__init__(objectName="card")
        self.db = db
        self.schedule = Schedule(db)
        self.term_id = None
        self.rows = []
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("수업별 강의실 배정", objectName="cardTitle"))
        toolbar.addStretch()
        self.suggest_button = QPushButton("자동 제안")
        self.suggest_button.clicked.connect(self.suggest)
        toolbar.addWidget(self.suggest_button)
        refresh = QPushButton("새로고침")
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setAccessibleName("학기별 강의실 배정 현황")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(self.refresh_choices)
        layout.addWidget(self.table, 1)
        controls = QHBoxLayout()
        label = QLabel("빈 강의실")
        self.room = QComboBox()
        self.room.setAccessibleName("선택한 수업의 강의실")
        label.setBuddy(self.room)
        self.room.currentIndexChanged.connect(self.update_save_button)
        controls.addWidget(label)
        controls.addWidget(self.room, 1)
        self.save_button = QPushButton("강의실 저장", objectName="primary")
        self.save_button.clicked.connect(self.save)
        controls.addWidget(self.save_button)
        layout.addLayout(controls)
        self.hint = QLabel(objectName="muted")
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    def set_term(self, term_id):
        if self.term_id != term_id:
            self.table.setCurrentCell(-1, -1)
        self.term_id = term_id
        self.refresh()

    def selected_lesson(self):
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def refresh(self):
        selected = self.selected_lesson()
        self.rows = self.schedule.room_lessons(self.term_id)
        pending = sum(lesson.room_id is None for lesson in self.rows)
        self.summary.setText("학기를 먼저 선택하세요." if self.term_id is None else
                             f"전체 {len(self.rows)}개 수업 · 강의실 미배정 {pending}개")
        self.suggest_button.setEnabled(pending > 0)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for row, lesson in enumerate(self.rows):
            room = lesson.room if lesson.room_id is not None else "미배정"
            if lesson.locked:
                room += " (잠김)"
            self._fill_row(self.table, row, lesson, room)
            if selected and selected.id == lesson.id:
                self.table.setCurrentCell(row, 0)
        self.table.blockSignals(False)
        self.refresh_choices()

    @staticmethod
    def _fill_row(table, row, lesson, result):
        end = lesson.start + lesson.length - 1
        periods = f"{lesson.start}~{end}" if end > lesson.start else str(lesson.start)
        values = (f"{DAYS[lesson.weekday]} {periods}교시", lesson.cohort, lesson.subject, lesson.teacher, result)
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            table.setItem(row, col, item)

    def suggest(self):
        term_id = self.term_id
        try:
            suggestions = self.schedule.suggest_rooms(term_id)
        except Exception as exc:
            QMessageBox.warning(self, "강의실 제안 실패", str(exc))
            return
        assigned = sum(row.room_id is not None for row in suggestions)
        dialog = QDialog(self)
        dialog.setWindowTitle("강의실 자동 제안")
        dialog.resize(740, 440)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"배정 제안 {assigned}개 · 미배정 {len(suggestions) - assigned}개"))
        layout.addWidget(QLabel("적용하면 제안된 강의실만 저장합니다. 미배정 수업은 개별 조정할 수 있습니다."))
        preview = QTableWidget(len(suggestions), len(self.COLUMNS))
        preview.setAccessibleName("강의실 제안과 미배정 사유")
        preview.setHorizontalHeaderLabels([*self.COLUMNS[:-1], "제안 강의실 / 미배정 사유"])
        preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        preview.setAlternatingRowColors(True)
        preview.verticalHeader().hide()
        preview.horizontalHeader().setStretchLastSection(True)
        for row, (lesson, room_id, result) in enumerate(suggestions):
            self._fill_row(preview, row, lesson, result if room_id is not None else f"미배정 · {result}")
        layout.addWidget(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("닫기" if not assigned else "취소")
        if assigned:
            buttons.addButton("제안 적용", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and assigned:
            try:
                self.schedule.apply_room_suggestions(term_id, suggestions)
            except Exception as exc:
                QMessageBox.warning(self, "강의실 저장 실패", str(exc))
        self.refresh()

    def refresh_choices(self):
        lesson = self.selected_lesson()
        self.room.blockSignals(True)
        self.room.clear()
        self.room.addItem("미배정 (강의실 없음)", None)
        self.room.setEnabled(bool(lesson and not lesson.locked))
        if not lesson:
            self.hint.setText("강의실을 지정할 수업을 선택하세요.")
        elif lesson.locked:
            self.hint.setText("시간표 편집에서 수업 잠금을 해제한 뒤 변경하세요.")
        else:
            rooms = self.schedule.available_rooms(self.term_id, lesson)
            capacities = self.db.capacity_values("rooms")
            for room_id, name in rooms:
                capacity = capacities.get(room_id)
                display = f"{capacity}명" if capacity is not None else "미설정"
                self.room.addItem(f"{name} · 정원 {display}", room_id)
            self.room.setCurrentIndex(self.room.findData(lesson.room_id))
            count = f"{lesson.student_count}명" if lesson.student_count is not None else "미설정"
            required = ", ".join(facility_tags(lesson.required_facilities)) or "없음"
            hint = "해당 교시에 배정할 수 있는 강의실을 표시합니다." if rooms else "시간·정원·시설 조건에 맞는 빈 강의실이 없습니다."
            self.hint.setText(f"반 인원 {count} · 필수 시설 {required}\n{hint}")
        self.room.blockSignals(False)
        self.update_save_button()

    def update_save_button(self):
        lesson = self.selected_lesson()
        self.save_button.setEnabled(bool(lesson and not lesson.locked and self.room.currentIndex() >= 0
                                         and self.room.currentData() != lesson.room_id))

    def save(self):
        lesson = self.selected_lesson()
        if not lesson or not self.save_button.isEnabled():
            return
        try:
            self.schedule.assign_room(self.term_id, lesson, self.room.currentData())
        except Exception as exc:
            QMessageBox.warning(self, "강의실 저장 실패", str(exc))
        self.refresh()


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


class TeacherAvailabilityPage(QFrame):
    def __init__(self, db):
        super().__init__(objectName="card")
        self.db = db
        self.schedule = Schedule(db)
        self.term_id = None
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 18)
        top = QHBoxLayout()
        top.addWidget(QLabel("강사 가능 시간", objectName="cardTitle"))
        top.addStretch()
        top.addWidget(QLabel("강사"))
        self.teacher = QComboBox()
        self.teacher.setAccessibleName("가능 시간 설정 강사")
        self.teacher.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.teacher)
        box.addLayout(top)
        for text in ("교시를 하나 또는 여러 개 선택한 뒤 상태를 지정하세요. 변경 즉시 저장됩니다.",
                     "미설정은 가능 여부를 아직 확인하지 않은 상태입니다. 수동 편성은 허용하지만, 불가 교시는 차단합니다."):
            label = QLabel(text, objectName="muted")
            label.setWordWrap(True)
            box.addWidget(label)
        self.grid = QTableWidget(11, len(DAYS))
        self.grid.setAccessibleName("강사 요일별 가능 시간")
        self.grid.setHorizontalHeaderLabels([day + "요일" for day in DAYS])
        self.grid.setVerticalHeaderLabels([f"{i}교시" for i in range(1, 12)])
        self.grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.grid.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.grid.horizontalHeader().setSectionResizeMode(self.grid.horizontalHeader().ResizeMode.Stretch)
        self.grid.verticalHeader().setDefaultSectionSize(33)
        box.addWidget(self.grid, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        for title, state in (("가능", "AVAILABLE"), ("불가", "UNAVAILABLE"), ("미설정", "UNSET")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, value=state: self.apply(value))
            buttons.addWidget(button)
        box.addLayout(buttons)

    def set_term(self, term_id):
        self.term_id = term_id
        selected = self.teacher.currentData()
        self.teacher.blockSignals(True)
        self.teacher.clear()
        for teacher_id, name in self.db.list("teachers"):
            self.teacher.addItem(name, teacher_id)
        index = self.teacher.findData(selected)
        if index >= 0:
            self.teacher.setCurrentIndex(index)
        self.teacher.blockSignals(False)
        periods = self.db.periods(term_id)
        self.grid.setVerticalHeaderLabels([
            f"{i}교시  {start}~{end}" for i, (start, end) in enumerate(periods, 1)
        ] if len(periods) == 11 else [f"{i}교시" for i in range(1, 12)])
        self.refresh()

    def refresh(self):
        from PySide6.QtGui import QColor
        selected = [(index.row(), index.column()) for index in self.grid.selectedIndexes()]
        states = {(day, period): status for day, period, status in self.schedule.availability(self.term_id, self.teacher.currentData())}
        labels = {"AVAILABLE": ("가능", "#e7f6ed"), "UNAVAILABLE": ("불가", "#fde9e9"), "UNSET": ("미설정", "#f4f6f9")}
        self.grid.clearContents()
        for period in range(1, 12):
            for day in range(len(DAYS)):
                status = states.get((day, period), "UNSET")
                label, color = labels[status]
                item = QTableWidgetItem(label)
                item.setBackground(QColor(color))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.grid.setItem(period - 1, day, item)
        self.grid.setEnabled(self.term_id is not None and self.teacher.currentData() is not None)
        for row, column in selected:
            self.grid.item(row, column).setSelected(True)

    def apply(self, status):
        cells = {(index.column(), index.row() + 1) for index in self.grid.selectedIndexes()}
        if not cells:
            QMessageBox.information(self, "교시 선택", "가능 시간을 설정할 교시를 선택하세요.")
            return
        try:
            self.schedule.set_availability(self.term_id, self.teacher.currentData(), cells, status)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "가능 시간 저장 실패", str(exc))
