"""현재 학기의 시간표 초안을 편집 가능한 엑셀 파일로 저장한다."""
import os
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .schedule import Schedule

DAYS = ("월", "화", "수", "목", "금")


def snapshot(db, term_id):
    db.conn.execute("BEGIN")
    try:
        db.assert_current()
        term = db.conn.execute("SELECT name FROM terms WHERE id=?", (term_id,)).fetchone()
        if term is None:
            raise ValueError("학기를 먼저 선택하세요.")
        periods = db.periods(term_id)
        if len(periods) != 11:
            raise ValueError("선택한 학기의 11교시 시간표를 찾을 수 없습니다.")
        cohorts = db.list("cohorts", term_id)
        teachers = db.list("teachers")
        rooms = db.list("rooms")
        subjects = db.list("subjects")
        schedule = Schedule(db)
        quotas = [(cohort_name, subject, weekly, length, assigned)
                  for cohort_id, cohort_name in cohorts
                  for _, subject, weekly, length, assigned, _ in schedule.quotas(cohort_id)]
        lessons = db.conn.execute("""SELECT l.cohort_id,c.name,l.subject_id,s.name,l.teacher_id,t.name,
            l.room_id,COALESCE(r.name,''),l.weekday,l.start_period,l.length,l.locked
            FROM lessons l JOIN cohorts c ON c.id=l.cohort_id
            JOIN subjects s ON s.id=l.subject_id JOIN teachers t ON t.id=l.teacher_id
            LEFT JOIN rooms r ON r.id=l.room_id WHERE c.term_id=?
            ORDER BY l.weekday,l.start_period,c.name,l.id""", (term_id,)).fetchall()
        return term[0], periods, cohorts, teachers, rooms, subjects, quotas, lessons
    finally:
        db.conn.rollback()


def export_timetable(db, term_id, destination):
    path = Path(destination)
    if path.suffix.lower() != ".xlsx":
        raise ValueError("저장할 파일의 확장자는 .xlsx여야 합니다.")
    term, periods, cohorts, teachers, rooms, subjects, quotas, lessons = snapshot(db, term_id)
    workbook = Workbook()
    workbook.remove(workbook.active)
    blue = PatternFill("solid", fgColor="DEEAFB")
    border = Border(*(Side(style="thin", color="D6DFEA") for _ in range(4)))

    def style_sheet(sheet, header_row):
        sheet.freeze_panes = f"C{header_row + 1}"
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.print_options.horizontalCentered = True
        sheet.print_title_rows = f"1:{header_row}"
        for cell in sheet[header_row]:
            cell.fill = blue
            cell.font = Font(bold=True, color="1D3554")
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                if cell.row >= header_row:
                    cell.border = border
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.print_area = f"A1:{get_column_letter(sheet.max_column)}{sheet.max_row}"

    def timetable(title, items, kind):
        for number, (target_id, name) in enumerate(items, 1):
            sheet = workbook.create_sheet(f"{title}_{number:03d}")
            sheet.append([f"{term} · {title} {name} · 시간표 초안"])
            sheet.append(["확정 전 자료 · 강의실 미배정 수업 포함"])
            sheet.append(["교시", "시간"] + [day + "요일" for day in DAYS])
            for index, (start, end) in enumerate(periods, 1):
                sheet.append([f"{index}교시", f"{start}~{end}"] + [None] * 5)
            for cid, cohort, sid, subject, tid, teacher, rid, room, day, start, length, locked in lessons:
                if {"반": cid, "강사": tid, "강의실": rid}[kind] != target_id:
                    continue
                name_line = f"{subject}\n{teacher}\n{room or '강의실 미배정'}" if kind == "반" else f"{cohort}\n{subject}\n{room or '강의실 미배정'}" if kind == "강사" else f"{cohort}\n{subject}\n{teacher}"
                for period in range(start, start + length):
                    cell = sheet.cell(row=3 + period, column=3 + day)
                    cell.value = f"{cell.value}\n---\n{name_line}" if cell.value else name_line
            sheet.column_dimensions["A"].width = 10
            sheet.column_dimensions["B"].width = 17
            for column in "CDEFG":
                sheet.column_dimensions[column].width = 24
            for row in range(4, 15):
                sheet.row_dimensions[row].height = 52
            style_sheet(sheet, 3)

    timetable("반", cohorts, "반")
    timetable("강사", teachers, "강사")
    timetable("강의실", rooms, "강의실")

    sheet = workbook.create_sheet("전체_배정목록")
    sheet.append([f"{term} · 전체 배정 목록 · 시간표 초안"])
    sheet.append(["강의실 미배정 수업을 포함합니다."])
    sheet.append(["반", "과목", "강사", "강의실", "요일", "시작 교시", "종료 교시", "시수", "잠금"])
    for _, cohort, _, subject, _, teacher, _, room, day, start, length, locked in lessons:
        sheet.append([cohort, subject, teacher, room or "미배정", DAYS[day], start, start + length - 1, length, "잠금" if locked else "해제"])
    for index in range(1, 10):
        sheet.column_dimensions[get_column_letter(index)].width = 19
    style_sheet(sheet, 3)

    sheet = workbook.create_sheet("과목_시수요약")
    sheet.append([f"{term} · 반별 과목 시수 · 시간표 초안"])
    sheet.append(["잔여 시수는 목표에서 배정된 교시를 뺀 값입니다."])
    sheet.append(["반", "과목", "목표 시수", "수업 길이", "배정 시수", "잔여 시수"])
    for cohort, subject, weekly, length, assigned in quotas:
        sheet.append([cohort, subject, weekly, length, assigned, weekly - assigned])
    for index in range(1, 7):
        sheet.column_dimensions[get_column_letter(index)].width = 19
    style_sheet(sheet, 3)

    sheet = workbook.create_sheet("강사_배정시수")
    sheet.append([f"{term} · 강사별 과목 배정 시수 · 시간표 초안"])
    sheet.append(["2교시 연강은 2시수로 집계합니다."])
    sheet.append(["강사"] + [name + (" (비활성)" if not active else "") for _, name, active in subjects] + ["합계"])
    totals = {subject_id: 0 for subject_id, _, _ in subjects}
    for teacher_id, teacher_name in teachers:
        counts = {subject_id: 0 for subject_id in totals}
        for _, _, subject_id, _, tid, _, _, _, _, _, length, _ in lessons:
            if tid == teacher_id:
                counts[subject_id] += length
                totals[subject_id] += length
        sheet.append([teacher_name] + [counts[subject_id] for subject_id, _, _ in subjects] + [sum(counts.values())])
    sheet.append(["합계"] + [totals[subject_id] for subject_id, _, _ in subjects] + [sum(totals.values())])
    for index in range(1, len(subjects) + 3):
        sheet.column_dimensions[get_column_letter(index)].width = 19
    style_sheet(sheet, 3)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".academy-", suffix=".xlsx", dir=path.parent, delete=False) as handle:
            temporary = handle.name
        workbook.save(temporary)
        os.replace(temporary, path)
        temporary = None
    finally:
        workbook.close()
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
