import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from academy_timetable.__main__ import MainWindow
from academy_timetable.db import Database
from academy_timetable.update_ui import UpdateDialog


class UpdateGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.db = Database(self.root / 'data.sqlite3')
        self.db.add('terms', '보존할 학기')
        self.window = MainWindow(self.db)

    def tearDown(self):
        self.window.period_dirty = False
        self.window.close()
        self.db.conn.close()
        self.folder.cleanup()

    def wait_job(self, dialog):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app.processEvents()
            if dialog.worker is None:
                return
            time.sleep(0.005)
        self.fail('Update worker did not finish')

    def test_update_button_opens_dialog_and_unsaved_periods_prevent_shutdown(self):
        button = next(button for button in self.window.findChildren(QPushButton)
                      if button.accessibleName() == '프로그램 업데이트')
        with patch.object(UpdateDialog, 'exec') as show:
            button.click()
            show.assert_called_once()
            self.window.period_dirty = True
            with patch.object(QMessageBox, 'information'):
                button.click()
            show.assert_called_once()

    def test_successful_download_is_backed_up_before_the_helper_starts(self):
        release = {'version': '0.4.0'}
        with patch('academy_timetable.update_ui.install_target', return_value=('windows-portable', self.root / 'App.exe', 'AcademyTimetable.exe')), \
             patch('academy_timetable.update_ui.check_update', return_value=release), \
             patch('academy_timetable.update_ui.download_update', side_effect=lambda release, folder, **kw: folder / 'new.exe'), \
             patch('academy_timetable.update_ui.launch_update', return_value=self.root / 'update.log') as launch:
            dialog = UpdateDialog(self.window, self.db)
            dialog.show()
            self.app.processEvents()
            self.wait_job(dialog)
            self.assertTrue(dialog.install.isEnabled())
            dialog.install.click()
            self.wait_job(dialog)
            self.assertTrue(dialog.install_started)
            launch.assert_called_once()
            backups = list(self.root.glob('before_update_*.sqlite3'))
            self.assertEqual(len(backups), 1)
            backup = Database(backups[0])
            try:
                self.assertEqual(backup.list('terms'), self.db.list('terms'))
            finally:
                backup.conn.close()
            config = launch.call_args.args[0]
            from academy_timetable.updater import cleanup_update
            cleanup_update(config)

    def test_backup_failure_and_cancelled_finished_job_never_launch_installer(self):
        dialog = UpdateDialog(self.window, self.db)
        stage = self.root / 'download'
        stage.mkdir()
        with patch('academy_timetable.update_ui.backup_to', side_effect=OSError('disk full')), \
             patch('academy_timetable.update_ui.launch_update') as launch, \
             patch.object(QMessageBox, 'warning'):
            dialog.job = 'download'
            dialog.worker = Mock(result={'stage': str(stage)}, error=None)
            dialog.finish_job()
            self.assertFalse(dialog.install_started)
            launch.assert_not_called()
        stage.mkdir()
        with patch('academy_timetable.update_ui.launch_update') as launch:
            dialog.worker = Mock(result={'stage': str(stage)}, error=None)
            dialog.worker.isRunning.return_value = False
            dialog.reject()
            self.assertTrue(dialog.cancelled)
            dialog.finish_job()
            launch.assert_not_called()
            self.assertFalse(stage.exists())
