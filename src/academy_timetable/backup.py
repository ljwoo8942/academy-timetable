"""SQLite 온라인 백업과 트랜잭션 기반 복원."""
import os
import sqlite3
import tempfile
from pathlib import Path

class RestoreAppliedError(RuntimeError):
    """복원은 완료됐으나 후속 정리에 실패한 상태."""


TABLES = {
    "terms": ("id", "name"),
    "teachers": ("id", "name"),
    "subjects": ("id", "name", "active"),
    "rooms": ("id", "name"),
    "cohorts": ("id", "term_id", "name"),
    "periods": ("term_id", "number", "start", "end"),
    "quotas": ("cohort_id", "subject_id", "weekly_periods", "session_length"),
    "lessons": ("id", "cohort_id", "subject_id", "teacher_id", "room_id", "weekday", "start_period", "length", "locked"),
    "teacher_availability": ("term_id", "teacher_id", "weekday", "period", "status"),
}


def database_path(db):
    path = db.conn.execute("PRAGMA database_list").fetchone()[2]
    if not path:
        raise ValueError("파일에 저장된 데이터베이스가 필요합니다.")
    return Path(path).resolve()


def _same_file(first, second):
    if Path(first).resolve() == Path(second).resolve():
        return True
    return os.path.exists(first) and os.path.exists(second) and os.path.samefile(first, second)


def _copy(source, destination):
    def progress(status, remaining, total):
        if status in (getattr(sqlite3, "SQLITE_BUSY", 5), getattr(sqlite3, "SQLITE_LOCKED", 6)):
            raise sqlite3.OperationalError("데이터베이스가 사용 중입니다. 다른 작업을 마친 뒤 다시 시도하세요.")
    source.backup(destination, pages=128, progress=progress)


def backup_to(db, destination):
    target = Path(destination)
    if target.suffix.lower() != ".sqlite3":
        raise ValueError("백업 파일 확장자는 .sqlite3이어야 합니다.")
    if db.conn.in_transaction:
        raise ValueError("저장 중인 작업을 완료한 뒤 백업하세요.")
    if _same_file(database_path(db), target):
        raise ValueError("현재 사용 중인 데이터베이스에는 백업할 수 없습니다.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".academy-backup-", suffix=".sqlite3", dir=target.parent, delete=False) as handle:
            temporary = handle.name
        output = sqlite3.connect(temporary)
        try:
            db.conn.execute("BEGIN")
            try:
                db.assert_current()
                _copy(db.conn, output)
            finally:
                db.conn.rollback()
            _check_backup(output)
        finally:
            output.close()
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _check_backup(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != 3:
        raise ValueError("이 프로그램의 데이터베이스 버전 3 백업만 복원할 수 있습니다.")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("백업 파일의 무결성 검사에 실패했습니다.")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("백업 파일의 연결 정보가 올바르지 않습니다.")
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*'")}
    if tables != set(TABLES):
        raise ValueError("백업 파일의 테이블 구성이 이 프로그램과 다릅니다.")
    for table, columns in TABLES.items():
        found = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
        if found != columns:
            raise ValueError(f"백업 파일의 {table} 구조가 올바르지 않습니다.")


def restore_from(db, source_path):
    current_path = database_path(db)
    source_path = Path(source_path).resolve()
    if _same_file(current_path, source_path):
        raise ValueError("현재 사용 중인 데이터베이스는 복원 파일로 선택할 수 없습니다.")
    if db.conn.in_transaction:
        raise ValueError("저장 중인 작업을 완료한 뒤 복원하세요.")
    staging = None
    safety = None
    safety_valid = False
    attached = False
    applied = False
    try:
        source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
        try:
            with tempfile.NamedTemporaryFile(prefix=".academy-restore-", suffix=".sqlite3", dir=current_path.parent, delete=False) as handle:
                staging = handle.name
            staged = sqlite3.connect(staging)
            try:
                _copy(source, staged)
                _check_backup(staged)
            finally:
                staged.close()
        finally:
            source.close()
        db.conn.execute("BEGIN IMMEDIATE")
        try:
            db.assert_current()
            with tempfile.NamedTemporaryFile(prefix="before_restore_", suffix=".sqlite3", dir=current_path.parent, delete=False) as handle:
                safety = Path(handle.name)
            reader = sqlite3.connect(current_path.as_uri() + "?mode=ro", uri=True)
            try:
                output = sqlite3.connect(safety)
                try:
                    _copy(reader, output)
                    _check_backup(output)
                    safety_valid = True
                finally:
                    output.close()
            finally:
                reader.close()
            db.conn.execute("ATTACH DATABASE ? AS restore_source", (staging,))
            attached = True
            for table in reversed(TABLES):
                db.conn.execute(f"DELETE FROM main.{table}")
            for table, columns in TABLES.items():
                names = ", ".join(columns)
                db.conn.execute(f"INSERT INTO main.{table} ({names}) SELECT {names} FROM restore_source.{table}")
            if db.conn.execute("PRAGMA main.foreign_key_check").fetchone():
                raise ValueError("복원 데이터의 연결 정보가 올바르지 않습니다.")
            # 다른 창이 복원 전 식별자로 쓰지 못하도록 데이터와 함께 세대를 갱신한다.
            next_generation = (db.restore_generation + 1) % 2147483647
            db.conn.execute(f"PRAGMA application_id = {next_generation}")
            db.conn.commit()
            db.restore_generation = next_generation
            applied = True
        except Exception:
            db.conn.rollback()
            raise
        finally:
            if attached:
                db.conn.execute("DETACH DATABASE restore_source")
        return safety
    except Exception as exc:
        if applied:
            raise RestoreAppliedError(f"복원은 적용되었지만 연결 정리에 실패했습니다. 프로그램을 다시 시작하세요. 복원 전 백업: {safety}\n{exc}") from exc
        if safety_valid:
            raise RuntimeError(f"복원하지 못했습니다. 복원 전 백업: {safety}\n{exc}") from exc
        if safety is not None and safety.exists():
            safety.unlink()
        raise
    finally:
        if staging and os.path.exists(staging):
            os.unlink(staging)
