import logging
from logging.handlers import RotatingFileHandler
from importlib.metadata import PackageNotFoundError, version
import platform
import sys

from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QMessageBox


try:
    APP_VERSION = version("academy-timetable")
except PackageNotFoundError:
    APP_VERSION = "개발 버전"


def configure_logging(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "academy-timetable.log"
    logger = logging.getLogger("academy_timetable")
    for previous in logger.handlers[:]:
        previous.close()
        logger.removeHandler(previous)
    handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("앱 시작 version=%s Python=%s Qt=%s OS=%s arch=%s", APP_VERSION,
                platform.python_version(), qVersion(), platform.platform(), platform.machine())
    return path


def install_exception_hook(log_path):
    previous = sys.excepthook

    def report(error_type, error, traceback):
        logging.getLogger("academy_timetable").critical("처리하지 못한 프로그램 오류", exc_info=(error_type, error, traceback))
        QMessageBox.critical(None, "프로그램 오류", f"작업 중 오류가 발생했습니다.\n{error}\n오류 로그: {log_path}")

    sys.excepthook = report
    return previous
