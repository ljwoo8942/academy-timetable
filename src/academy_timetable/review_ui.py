from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from .review import review_draft


class ReviewPage(QFrame):
    def __init__(self, db):
        super().__init__(objectName="card")
        self.db = db
        self.term_id = None
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 18)
        top = QHBoxLayout()
        top.addWidget(QLabel("초안 검토 결과", objectName="cardTitle"))
        top.addStretch()
        button = QPushButton("다시 검토")
        button.clicked.connect(self.refresh)
        top.addWidget(button)
        box.addLayout(top)
        notice = QLabel("저장된 초안을 기준으로 시수·기본 중복·강사 가능 시간·강의실을 확인합니다. 확인되지 않은 규칙은 결과가 없어도 통과한 것이 아닙니다.", objectName="muted")
        notice.setWordWrap(True)
        box.addWidget(notice)
        self.summary = QLabel()
        box.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setAccessibleName("시간표 초안 검토 결과")
        self.table.setHorizontalHeaderLabels(["상태", "항목", "상세"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 160)
        box.addWidget(self.table, 1)
        limitation = QLabel("미검토: 학생별 선택수업, 과목별 시간대·일일 교과 혼합, 동시 편성 그룹, 강의실 정원·시설 등. 최종 확정 기능은 아직 없습니다.", objectName="muted")
        limitation.setWordWrap(True)
        box.addWidget(limitation)

    def set_term(self, term_id):
        self.term_id = term_id
        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        if self.term_id is None:
            self.summary.setText("학기를 먼저 선택하세요.")
            return
        try:
            issues = review_draft(self.db, self.term_id)
        except Exception as exc:
            self.summary.setText("검토 결과를 불러오지 못했습니다.")
            QMessageBox.warning(self, "검토 실패", str(exc))
            return
        errors = sum(status == "오류" for status, _, _ in issues)
        self.summary.setText(f"검토한 항목: 오류 {errors}건 · 확인 필요 {len(issues) - errors}건")
        self.table.setRowCount(len(issues))
        for row, values in enumerate(issues):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0 and value == "오류":
                    item.setForeground(QColor("#b42318"))
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()
