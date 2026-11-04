"""엑셀 기본 정보 미리보기와 원자적 반영."""
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from .schedule import Schedule

FIELDS = {"cohorts": "반 이름", "teachers": "강사 이름", "subjects": "과목 이름", "rooms": "강의실 이름"}


def sheet_names(path):
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        return workbook.sheetnames
    finally:
        workbook.close()


def read_sheet(path, sheet):
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if sheet not in workbook.sheetnames:
            raise ValueError("시트를 찾을 수 없습니다.")
        rows = workbook[sheet].iter_rows(values_only=True)
        header = next(rows, ())
        if not header or not any(value is not None for value in header):
            raise ValueError("첫 행에 열 제목이 필요합니다.")
        labels = [f"{get_column_letter(i)}: {str(value).strip() if value is not None else '(제목 없음)'}"
                  for i, value in enumerate(header, 1)]
        return labels, [(i, tuple(values)) for i, values in enumerate(rows, 2)
                        if any(value is not None and str(value).strip() for value in values)]
    finally:
        workbook.close()


def preview(db, term_id, labels, source_rows, mapping):
    if not mapping or any(key not in FIELDS for key in mapping):
        raise ValueError("가져올 열을 하나 이상 선택하세요.")
    if len(set(mapping.values())) != len(mapping) or any(not isinstance(index, int) or index < 0 or index >= len(labels) for index in mapping.values()):
        raise ValueError("각 항목에 서로 다른 유효한 열을 선택하세요.")
    if "cohorts" in mapping and not db.conn.execute("SELECT 1 FROM terms WHERE id=?", (term_id,)).fetchone():
        raise ValueError("반을 가져오려면 학기를 먼저 선택하세요.")
    inactive = {name for _, name, active in db.list("subjects") if not active}
    results = []
    for number, values in source_rows:
        mapped, errors = {}, []
        for table, index in mapping.items():
            value = values[index] if index < len(values) else None
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if not isinstance(value, str) or value.lstrip().startswith("="):
                errors.append(f"{FIELDS[table]}: 텍스트 이름만 가능")
                continue
            name = value.strip()
            if table == "subjects" and name in inactive:
                errors.append(f"과목 '{name}': 기존 비활성 과목")
            mapped[table] = name
        if not mapped and not errors:
            errors.append("선택된 열에 값 없음")
        results.append((number, values, mapped, errors))
    if not results:
        raise ValueError("가져올 데이터 행이 없습니다.")
    return results


def apply_import(db, term_id, rows):
    if not rows or any(errors or not values for _, _, values, errors in rows):
        raise ValueError("오류가 없는 미리보기만 반영할 수 있습니다.")
    counts = {table: 0 for table in FIELDS}
    with Schedule(db).transaction():
        if any("cohorts" in values for _, _, values, _ in rows) and not db.conn.execute("SELECT 1 FROM terms WHERE id=?", (term_id,)).fetchone():
            raise ValueError("선택한 학기가 더 이상 존재하지 않습니다.")
        for _, _, values, _ in rows:
            for table, name in values.items():
                if table not in FIELDS or not isinstance(name, str) or not name.strip() or name != name.strip():
                    raise ValueError("가져올 이름이 올바르지 않습니다.")
                if table == "subjects":
                    subject = db.conn.execute("SELECT active FROM subjects WHERE name=?", (name,)).fetchone()
                    if subject and not subject[0]:
                        raise ValueError(f"과목 '{name}'은 비활성 상태입니다. 미리보기를 다시 확인하세요.")
                if table == "cohorts":
                    result = db.conn.execute("INSERT OR IGNORE INTO cohorts(term_id,name) VALUES (?,?)", (term_id, name))
                else:
                    result = db.conn.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES (?)", (name,))
                counts[table] += result.rowcount
    return counts
