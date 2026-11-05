import os
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .backup import RestoreAppliedError, backup_to, restore_from


class BackupPage(QFrame):
    def __init__(self, db, window):
        super().__init__(objectName="card")
        self.db = db
        self.window = window
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 18)
        box.addWidget(QLabel("데이터 백업 및 복원", objectName="cardTitle"))
        notice = QLabel("백업은 모든 학기와 시간표를 하나의 SQLite 파일로 저장합니다. 복원은 현재 데이터를 백업 파일의 내용으로 교체합니다.", objectName="muted")
        notice.setWordWrap(True)
        box.addWidget(notice)
        detail = QLabel("복원 전 현재 데이터의 별도 백업을 자동으로 보관합니다. 다른 프로그램 창의 저장되지 않은 변경은 먼저 저장하고 창을 닫아 주세요.", objectName="muted")
        detail.setWordWrap(True)
        box.addWidget(detail)
        save = QPushButton("백업 파일 저장", objectName="primary")
        save.clicked.connect(self.save_backup)
        box.addWidget(save)
        restore = QPushButton("백업 파일에서 복원")
        restore.clicked.connect(self.restore_backup)
        box.addWidget(restore)
        box.addStretch()

    def save_backup(self):
        if self.window.period_dirty and QMessageBox.question(
            self, "저장되지 않은 교시표", "교시표에 저장되지 않은 변경이 있습니다. 저장된 데이터만 백업하시겠습니까?"
        ) != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(self, "백업 파일 저장", "학원_백업.sqlite3", "SQLite 백업 (*.sqlite3)", options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        if not Path(path).suffix:
            path += ".sqlite3"
        if Path(path).suffix.lower() != ".sqlite3":
            QMessageBox.warning(self, "백업 실패", "파일 확장자는 .sqlite3이어야 합니다.")
            return
        if os.path.lexists(path) and QMessageBox.question(self, "파일 덮어쓰기", "같은 이름의 파일이 있습니다. 덮어쓰시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        try:
            backup_to(self.db, path)
            QMessageBox.information(self, "백업 완료", f"백업 파일을 저장했습니다.\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "백업 실패", str(exc))

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "복원할 백업 선택", "", "SQLite 백업 (*.sqlite3)")
        if not path:
            return
        if QMessageBox.question(self, "복원 확인", "현재 모든 학기와 시간표가 백업 파일의 데이터로 교체됩니다. 복원 전 현재 데이터를 별도 백업합니다. 다른 창을 닫았는지 확인하고 계속하시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        if not self.window.discard_period_changes():
            return
        try:
            safety = restore_from(self.db, path)
        except RestoreAppliedError as exc:
            self.window.refresh_all()
            QMessageBox.warning(self, "복원 후 정리 실패", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "복원 실패", str(exc))
            return
        self.window.refresh_all()
        QMessageBox.information(self, "복원 완료", f"백업 파일을 복원했습니다.\n복원 전 데이터 백업: {safety}")
