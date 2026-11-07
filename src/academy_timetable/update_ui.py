import logging
from pathlib import Path
import tempfile

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

from .backup import backup_to, database_path
from .diagnostics import APP_BUILD, APP_VERSION
from .updater import (UpdateCancelled, check_update, cleanup_update, download_update, install_target,
                      launch_update, prepare_install)


class UpdateWorker(QThread):
    progress = Signal(int)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.operation(self)
        except Exception as exc:
            self.error = exc
            if not isinstance(exc, UpdateCancelled):
                logging.getLogger(__name__).exception('업데이트 작업 실패')


class UpdateDialog(QDialog):
    def __init__(self, window, db):
        super().__init__(window)
        self.db = db
        self.worker = None
        self.cancelled = False
        self.release = None
        self.install_started = False
        self.setWindowTitle('프로그램 업데이트')
        self.resize(520, 260)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'현재 버전: {APP_VERSION}'))
        self.status = QLabel('GitHub 공개 배포에서 새 버전을 확인합니다. 로그인은 필요하지 않습니다.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setAccessibleName('업데이트 진행률')
        layout.addWidget(self.progress)
        hint = QLabel('설치 전 모든 학기와 시간표를 자동 백업합니다. 업데이트 중에는 앱이 종료된 뒤 다시 열립니다. 다른 프로그램 창은 먼저 닫아 주세요.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        self.retry = QPushButton('다시 확인')
        self.retry.clicked.connect(self.check)
        self.install = QPushButton('업데이트 설치', objectName='primary')
        self.install.setEnabled(False)
        self.install.clicked.connect(self.download)
        self.cancel = QPushButton('닫기')
        self.cancel.clicked.connect(self.reject)
        for button in (self.retry, self.install, self.cancel):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        QTimer.singleShot(0, self.check)

    def start_job(self, name, operation):
        self.job = name
        self.retry.setEnabled(False)
        self.install.setEnabled(False)
        self.progress.setRange(0, 0)
        self.worker = UpdateWorker(operation, self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.finish_job)
        self.worker.start()

    def check(self):
        if not self.isVisible() or (self.worker and self.worker.isRunning()):
            return
        try:
            self.mode, self.target, self.asset_name = install_target()
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.status.setText('GitHub에서 최신 버전을 확인하는 중입니다…')
        self.release = None
        self.start_job('check', lambda worker: check_update(APP_VERSION, self.asset_name, current_build=APP_BUILD))

    def download(self):
        if not self.release or (self.worker and self.worker.isRunning()):
            return
        try:
            root = database_path(self.db).parent / 'updates'
            root.mkdir(exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix='update-', dir=root))
        except Exception as exc:
            self.status.setText(f'업데이트 폴더를 만들 수 없습니다. {exc}')
            return

        def operation(worker):
            config = {'stage': str(folder)}
            try:
                payload = download_update(self.release, folder, cancelled=worker.isInterruptionRequested,
                                          progress=worker.progress.emit)
                if worker.isInterruptionRequested():
                    raise UpdateCancelled()
                config = prepare_install(payload, self.mode, self.target)
                if worker.isInterruptionRequested():
                    raise UpdateCancelled()
                return config
            except Exception:
                cleanup_update(config)
                raise

        self.status.setText(f'v{self.release["version"]} 다운로드 및 검증 중…')
        self.start_job('download', operation)
        self.progress.setRange(0, 100)

    def finish_job(self):
        worker = self.worker
        self.worker = None
        worker.deleteLater()
        self.retry.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        if self.cancelled:
            if self.job == 'download' and worker.result:
                cleanup_update(worker.result)
            super().reject()
            return
        if worker.error:
            self.status.setText(f'업데이트를 완료하지 못했습니다. 인터넷 연결과 저장 공간을 확인한 뒤 다시 시도하세요.\n{worker.error}')
            return
        if self.job == 'check':
            self.release = worker.result
            if self.release is None:
                self.status.setText('현재 버전이 최신 공개 버전 이상입니다.')
            else:
                self.status.setText(f'새 버전 v{self.release["version"]}이 있습니다. 업데이트 설치를 누르면 다운로드 후 앱이 다시 시작됩니다.')
                self.install.setEnabled(True)
            return
        config = worker.result
        backup_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix='before_update_', suffix='.sqlite3',
                                             dir=database_path(self.db).parent, delete=False) as backup:
                backup_path = Path(backup.name)
            backup_to(self.db, backup_path)
            log_path = launch_update(config)
            logging.getLogger(__name__).info('업데이트 설치 시작 backup=%s log=%s', backup_path, log_path)
        except Exception as exc:
            cleanup_update(config)
            try:
                if backup_path is not None and backup_path.exists() and backup_path.stat().st_size == 0:
                    backup_path.unlink()
            except OSError:
                logging.getLogger(__name__).warning('실패한 백업 파일 정리 오류', exc_info=True)
            self.status.setText(f'백업 또는 설치 준비에 실패해 앱을 종료하지 않았습니다.\n{exc}')
            QMessageBox.warning(self, '업데이트 실패', self.status.text())
            return
        self.install_started = True
        self.accept()

    def reject(self):
        if self.worker is not None:
            self.cancelled = True
            self.worker.requestInterruption()
            self.status.setText('취소 중입니다. 진행 중인 네트워크 요청이 끝나면 닫힙니다.')
            self.cancel.setEnabled(False)
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            event.accept()
