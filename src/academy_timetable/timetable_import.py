"""엑셀 배정 목록을 검토하고 학기 시간표에 추가한다."""
from collections import defaultdict
from itertools import chain, islice
from typing import NamedTuple, Optional, Union

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from .db import DAYS
from .excel_import import FIELDS
from .schedule import Schedule


COLUMNS = ("반", "과목", "강사", "강의실", "요일", "시작 교시", "종료 교시", "시수", "잠금", "반 구분", "반 기준", "교과")
SCOPE_LABELS = {"COMMON": "공통", "AREA": "교과", "SUBJECT": "과목"}
REQUIRED = ("반", "과목", "강사", "요일", "시작 교시")
HEADERS = {name.replace(" ", ""): name for name in COLUMNS}
HEADERS.update({"반이름": "반", "반명": "반", "과목이름": "과목", "과목명": "과목",
                "강사이름": "강사", "강사명": "강사", "강의실이름": "강의실", "교시": "시작 교시"})


class ImportedLesson(NamedTuple):
    cohort: str
    subject: str
    teacher: str
    room: Optional[str]
    weekday: int
    start: int
    length: int
    locked: bool
    scope_kind: str = "COMMON"
    scope_name: Optional[str] = None
    area_name: Optional[str] = None


class SheetRow(NamedTuple):
    number: Union[int, str]
    values: tuple
    lesson: Optional[ImportedLesson]
    error: str = ""


def _name(value, label):
    if not isinstance(value, str) or not value.strip() or value.lstrip().startswith("="):
        raise ValueError(f"{label} 이름을 텍스트로 입력하세요.")
    return value.strip()


def _number(value, label, maximum):
    text = str(value).strip()
    if text.endswith("교시"):
        text = text[:-2].strip()
    if not text.isascii() or not text.isdecimal() or len(text) > 2 or not 1 <= int(text) <= maximum:
        raise ValueError(f"{label}에 1~{maximum} 사이의 교시를 입력하세요.")
    return int(text)


def _parse(values):
    cohort, subject, teacher, room, day, start, end, length, locked, kind, basis, area = (*values, *([None] * (len(COLUMNS) - len(values))))
    kinds = {label: key for key, label in SCOPE_LABELS.items()}
    if kind is None:
        kind = "공통"
    if kind not in kinds:
        raise ValueError("반 구분은 공통, 교과, 과목 중 하나를 입력하세요.")
    if kind == "공통" and basis is not None:
        raise ValueError("공통 반에는 반 기준을 입력하지 마세요.")
    basis = _name(basis, "반 기준") if kind != "공통" else None
    area = _name(area, "교과") if area is not None else None
    day = str(day).strip()
    if day.endswith("요일"):
        day = day[:-2]
    if day not in DAYS:
        raise ValueError("요일은 월~토 중 하나를 입력하세요.")
    start = _number(start, "시작 교시", 11)
    length = _number(length, "시수", 2) if length is not None else None
    if end is not None:
        span = _number(end, "종료 교시", 11) - start + 1
        if span not in (1, 2) or (length is not None and span != length):
            raise ValueError("시작·종료 교시와 시수가 1교시 또는 2교시 연강에 맞아야 합니다.")
        length = span
    lock_text = str(locked).strip() if locked is not None else "해제"
    if lock_text not in ("잠금", "해제"):
        raise ValueError("잠금은 잠금 또는 해제로 입력하세요.")
    if room is None or room == "미배정":
        room = None
    elif type(room) is int and room > 0:
        room = str(room)
    else:
        room = _name(room, "강의실")
    return ImportedLesson(_name(cohort, "반"), _name(subject, "과목"), _name(teacher, "강사"), room,
                          DAYS.index(day), start, length or 1, lock_text == "잠금", kinds[kind], basis, area)


def _cohort_key(value):
    name = str(value).strip()
    if name.endswith("반") and name[:-1].strip().isdecimal():
        return name[:-1].strip()
    return name


def _grid_rows(worksheet, excluded):
    cells = list(worksheet.iter_rows(min_row=3, max_row=28, max_col=min(worksheet.max_column or 256, 256)))
    columns = []
    day = None
    for index, (day_cell, cohort_cell) in enumerate(zip(cells[0], cells[2])):
        if index < 2:
            continue
        if day_cell.value is not None:
            day = day_cell.value
        if cohort_cell.value is not None and _cohort_key(cohort_cell.value) not in excluded:
            columns.append((index, day, str(cohort_cell.value).strip()))

    results = []
    for offset in range(4, len(cells) - 1, 2):
        subject_cells, teacher_cells = cells[offset:offset + 2]
        period = subject_cells[1].value
        for index, day, cohort in columns:
            cell, teacher_cell = subject_cells[index], teacher_cells[index]
            if cell.value is None:
                continue
            subject = " ".join(str(cell.value).split())
            if not subject:
                continue
            teacher = teacher_cell.value
            if teacher is None and subject.endswith(" 단과") and len(subject.split()) == 2:
                teacher = subject.split()[0]
            values = (cohort, subject, teacher, None, day, period, None, 1, None)
            coordinate = f"{get_column_letter(index + 1)}{offset + 3}"
            try:
                if cell.data_type in ("f", "e") or teacher_cell.data_type in ("f", "e"):
                    raise ValueError("수식과 엑셀 오류는 가져올 수 없습니다.")
                results.append(SheetRow(coordinate, values, _parse(values)))
            except ValueError as exc:
                results.append(SheetRow(coordinate, values, None, str(exc)))
    return results


def read_timetable(path, sheet, excluded_cohorts=()):
    excluded = {_cohort_key(name) for name in excluded_cohorts}
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        worksheet = workbook[sheet]
        cells = worksheet.iter_rows(max_col=min(worksheet.max_column or 256, 256))
        first = list(islice(cells, 5))
        if len(first) == 5 and len(first[2]) >= 2 and first[2][1].value == "요일" and first[4][1].value == "반":
            cells.close()
            result = _grid_rows(worksheet, excluded)
            if not result:
                raise ValueError("제외할 반을 적용한 뒤 가져올 수업이 없습니다.")
            return result

        rows = enumerate(chain(first, cells), 1)
        for number, cells in rows:
            if number > 20:
                raise ValueError("처음 20행 안에 반, 과목, 강사, 요일, 시작 교시 열 제목이 필요합니다.")
            recognized = [(HEADERS.get("".join(str(cell.value).split())), i) for i, cell in enumerate(cells)]
            mapping = {name: index for name, index in recognized if name}
            if all(name in mapping for name in REQUIRED):
                if len(mapping) != sum(name is not None for name, _ in recognized):
                    raise ValueError("같은 의미의 열 제목이 중복되어 있습니다.")
                header_row = number
                break
        else:
            raise ValueError("반, 과목, 강사, 요일, 시작 교시 열 제목을 찾을 수 없습니다.")

        result = []
        for number, cells in rows:
            if number > header_row + 5000:
                raise ValueError("한 번에 불러올 수 있는 범위는 열 제목 다음 5,000행까지입니다.")
            selected = [cells[mapping[name]] if name in mapping else None for name in COLUMNS]
            values = tuple((cell.value.strip() or None if isinstance(cell.value, str) else cell.value)
                           if cell is not None else None for cell in selected)
            if not any(value is not None for value in values) or _cohort_key(values[0]) in excluded:
                continue
            try:
                if any(cell is not None and cell.data_type in ("f", "e") for cell in selected):
                    raise ValueError("수식과 엑셀 오류는 가져올 수 없습니다. 값으로 저장한 뒤 다시 선택하세요.")
                result.append(SheetRow(number, values, _parse(values)))
            except ValueError as exc:
                result.append(SheetRow(number, values, None, str(exc)))
        if not result:
            raise ValueError("가져올 수업 행이 없습니다.")
        return result
    finally:
        workbook.close()


def _import_rows(db, term_id, rows):
    term = db.conn.execute("SELECT name FROM terms WHERE id=?", (term_id,)).fetchone()
    if not term or not rows:
        raise ValueError("대상 학기와 불러올 수업을 확인하세요.")
    schedule = Schedule(db)
    saved = {(row.cohort, row.subject, row.teacher, row.room if row.room_id is not None else None,
                            row.weekday, row.start, row.length, bool(row.locked))
             for row in schedule.room_lessons(term_id)}
    ids = {table: {row[1]: row[0] for row in db.list(table, term_id)} for table in FIELDS}

    def name_id(table, name):
        if name not in ids[table]:
            if table == "cohorts":
                inserted = db.conn.execute("INSERT INTO cohorts(term_id,name) VALUES (?,?)", (term_id, name))
            else:
                inserted = db.conn.execute(f"INSERT INTO {table}(name) VALUES (?)", (name,))
            ids[table][name] = inserted.lastrowid
        return ids[table][name]

    metadata_errors = {}
    pending = defaultdict(dict)
    for index, row in enumerate(rows):
        lesson = row.lesson
        if lesson is None:
            continue
        try:
            cohort_id = name_id("cohorts", lesson.cohort)
            subject_id = name_id("subjects", lesson.subject)
            if lesson.area_name is not None:
                current = db.subject_area(subject_id)
                if current is not None and current != lesson.area_name:
                    raise ValueError("기존 과목의 교과 설정과 다릅니다. 과목 관리에서 먼저 확인하세요.")
                db._set_subject_area(subject_id, lesson.area_name)
            if lesson.scope_kind != "COMMON":
                current = db.cohort_scope(cohort_id)
                if current[0] != "COMMON" and current != (lesson.scope_kind, lesson.scope_name):
                    raise ValueError("기존 반 기준과 다릅니다. 과목별 반 설정에서 먼저 확인하세요.")
                db._set_cohort_scope(cohort_id, lesson.scope_kind, lesson.scope_name)
            if lesson[:8] not in saved:
                pending[lesson.cohort, lesson.subject][lesson[:8]] = lesson
        except ValueError as exc:
            metadata_errors[index] = str(exc)

    lengths, group_errors = {}, {}
    for group, lessons in pending.items():
        cohort_id, subject_id = name_id("cohorts", group[0]), name_id("subjects", group[1])
        try:
            db.validate_cohort_subject(cohort_id, subject_id)
        except ValueError as exc:
            group_errors[group] = str(exc)
            continue
        quota = db.conn.execute("SELECT session_length FROM quotas WHERE cohort_id=? AND subject_id=?",
                                (cohort_id, subject_id)).fetchone()
        if quota:
            lengths[group] = quota[0]
            continue
        sizes = {lesson.length for lesson in lessons.values()}
        total = sum(lesson.length for lesson in lessons.values())
        if len(sizes) != 1 or total > 55:
            group_errors[group] = "같은 반의 같은 과목은 수업 길이가 같아야 하며 주간 시수는 55교시 이하여야 합니다."
            continue
        lengths[group] = sizes.pop()
        db.conn.execute("INSERT INTO quotas VALUES (?,?,?,?)", (cohort_id, subject_id, total, lengths[group]))

    results = []
    for index, row in enumerate(rows):
        lesson = row.lesson
        if lesson is None:
            results.append(("오류", row.error))
            continue
        if index in metadata_errors:
            results.append(("오류", metadata_errors[index]))
            continue
        if lesson[:8] in saved:
            results.append(("건너뜀", "같은 수업이 이미 있습니다."))
            continue
        group = lesson.cohort, lesson.subject
        try:
            if group in group_errors:
                raise ValueError(group_errors[group])
            if lesson.length != lengths[group]:
                raise ValueError("엑셀의 수업 길이가 기존 시수 설정과 다릅니다.")
            teacher_id = name_id("teachers", lesson.teacher)
            room_id = name_id("rooms", lesson.room) if lesson.room is not None else None
            lesson_id = schedule._assign(ids["cohorts"][lesson.cohort], ids["subjects"][lesson.subject],
                                         teacher_id, room_id, lesson.weekday, lesson.start)
            if lesson.locked:
                db.conn.execute("UPDATE lessons SET locked=1 WHERE id=?", (lesson_id,))
        except ValueError as exc:
            results.append(("오류", str(exc)))
        else:
            results.append(("추가", ""))
            saved.add(lesson[:8])
    return term[0], tuple(results)


def preview_timetable(db, term_id, rows):
    with db.transaction():
        db.conn.execute("SAVEPOINT timetable_preview")
        try:
            return _import_rows(db, term_id, rows)
        finally:
            db.conn.execute("ROLLBACK TO timetable_preview")
            db.conn.execute("RELEASE timetable_preview")


def apply_timetable(db, term_id, rows, approved):
    if any(action == "오류" for action, _ in approved[1]):
        raise ValueError("오류가 없는 미리보기만 저장할 수 있습니다.")
    with db.transaction():
        if _import_rows(db, term_id, rows) != approved:
            raise ValueError("학기나 시간표가 변경되었습니다. 미리보기를 다시 확인하세요.")
    return sum(action == "추가" for action, _ in approved[1])
