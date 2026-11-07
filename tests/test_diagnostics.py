import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from academy_timetable import __main__
from academy_timetable.diagnostics import APP_VERSION, configure_logging, install_exception_hook


class DiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.previous_hook = sys.excepthook

    def tearDown(self):
        sys.excepthook = self.previous_hook
        logger = logging.getLogger("academy_timetable")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        logger.propagate = True
        logger.setLevel(logging.NOTSET)
        self.folder.cleanup()

    def test_uncaught_error_is_logged_and_shows_the_log_location(self):
        path = configure_logging(self.root)
        install_exception_hook(path)
        with patch.object(QMessageBox, "critical") as message:
            try:
                raise RuntimeError("진단 테스트 오류")
            except RuntimeError:
                sys.excepthook(*sys.exc_info())
        text = path.read_text(encoding="utf-8")
        self.assertIn(f"version={APP_VERSION}", text)
        self.assertIn("RuntimeError: 진단 테스트 오류", text)
        self.assertIn("Traceback", text)
        self.assertIn(str(path), message.call_args.args[2])

    def test_database_startup_failure_leaves_a_readable_log(self):
        with patch.object(__main__, "QApplication", return_value=self.app), \
             patch.object(__main__.QStandardPaths, "writableLocation", return_value=str(self.root)), \
             patch.object(__main__, "Database", side_effect=OSError("데이터 파일 열기 실패")), \
             patch.object(QMessageBox, "critical") as message:
            self.assertEqual(__main__.main(), 1)
        path = self.root / "academy-timetable.log"
        self.assertIn("데이터 파일 열기 실패", path.read_text(encoding="utf-8"))
        self.assertIn(str(path), message.call_args.args[2])
        self.assertIs(sys.excepthook, self.previous_hook)
