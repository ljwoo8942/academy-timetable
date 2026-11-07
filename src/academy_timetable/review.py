"""저장된 시간표 초안의 지원 가능한 항목만 검토한다."""
from .db import DAYS, validate_periods
from .schedule import Schedule, missing_facilities, room_fits

def review_draft(db, term_id):
    db.conn.execute("BEGIN")
    try:
        db.assert_current()
        if not db.conn.execute("SELECT 1 FROM terms WHERE id=?", (term_id,)).fetchone():
            raise ValueError("학기를 먼저 선택하세요.")
        issues = []
        periods = db.periods(term_id)
        if len(periods) != 11:
            issues.append(("오류", "교시표", "11개 교시가 필요합니다."))
        else:
            try:
                validate_periods(periods)
            except ValueError as exc:
                issues.append(("오류", "교시표", str(exc)))
        cohorts = db.list("cohorts", term_id)
        common = sum(db.cohort_scope(row_id)[0] == "COMMON" for row_id, _ in cohorts)
        if (common or not cohorts) and not 3 <= common <= 10:
            issues.append(("확인 필요", "반 수", f"현재 공통 반 {common}개입니다. 공통 반 운영 기준은 3~10개 반입니다."))
        schedule = Schedule(db)
        cohort_sizes = db.capacity_values("cohorts")
        room_capacities = db.capacity_values("rooms")
        subject_facilities = db.facility_values("subjects")
        room_facilities = db.facility_values("rooms")
        occupancy = {}
        teacher_times = {}
        eligible_teachers = {}
        for cohort_id, cohort in cohorts:
            quotas = schedule.quotas(cohort_id)
            if not quotas:
                issues.append(("확인 필요", "시수 미설정", f"{cohort}: 과목별 주간 시수를 설정하세요."))
            allowed = db.allowed_subject_ids(cohort_id)
            for subject_id, subject, weekly, _, assigned, active in quotas:
                if allowed is not None and subject_id not in allowed:
                    issues.append(("오류", "반 기준 불일치", f"{cohort} · {subject}: 반 기준에 맞지 않는 과목입니다."))
                if assigned != weekly:
                    severity = "오류" if assigned > weekly else "확인 필요"
                    issues.append((severity, "시수 초과" if assigned > weekly else "미배정 시수",
                                   f"{cohort} · {subject}: 목표 {weekly}교시, 배정 {assigned}교시"))
                if not active:
                    issues.append(("확인 필요", "비활성 과목", f"{cohort} · {subject}: 비활성 과목에 시수가 설정되어 있습니다."))
            for lesson in schedule.lessons(cohort_id):
                lesson_id, day, start, length, subject, teacher, room, _, subject_id, teacher_id, room_id = lesson
                label = f"{cohort} · {subject} · {teacher} · {DAYS[day]}요일 {start}~{start + length - 1}교시"
                if subject_id not in eligible_teachers:
                    eligible_teachers[subject_id] = db.eligible_teachers(subject_id)
                eligible = eligible_teachers[subject_id]
                if eligible and teacher_id not in eligible:
                    issues.append(("오류", "담당 강사 불일치", label))
                if start + length - 1 > 11 or (length == 2 and start in (4, 8)):
                    issues.append(("오류", "연강 범위", f"{label}: 교시 범위 또는 점심·저녁 경계를 확인하세요."))
                if room_id is None:
                    issues.append(("확인 필요", "강의실 미배정", label))
                else:
                    student_count = cohort_sizes[cohort_id]
                    capacity = room_capacities.get(room_id)
                    if student_count is None or capacity is None:
                        issues.append(("확인 필요", "인원·정원 미설정", f"{label} · {room}: 반 인원과 강의실 정원을 확인하세요."))
                    elif not room_fits(student_count, capacity):
                        issues.append(("오류", "강의실 정원 부족", f"{label} · {room}: 반 인원 {student_count}명, 정원 {capacity}명"))
                    missing = missing_facilities(subject_facilities.get(subject_id, ""), room_facilities.get(room_id, ""))
                    if missing:
                        issues.append(("오류", "강의실 필수 시설 부족", f"{label} · {room}: {', '.join(missing)}"))
                if teacher_id not in teacher_times:
                    teacher_times[teacher_id] = {(weekday, period): status for weekday, period, status in schedule.availability(term_id, teacher_id)}
                availability = teacher_times[teacher_id]
                unset, unavailable = [], []
                for period in range(start, min(start + length, 12)):
                    status = availability.get((day, period), "UNSET")
                    if status == "UNSET":
                        unset.append(str(period))
                    elif status == "UNAVAILABLE":
                        unavailable.append(str(period))
                    for kind, value, name in (("반", cohort_id, cohort), ("강사", teacher_id, teacher), ("강의실", room_id, room)):
                        if value is None:
                            continue
                        key = (kind, value, day, period)
                        if key in occupancy and occupancy[key][0] != lesson_id:
                            issues.append(("오류", f"{kind} 중복", f"{name} · {DAYS[day]}요일 {period}교시: {occupancy[key][1]} / {label}"))
                        else:
                            occupancy[key] = (lesson_id, label)
                if unavailable:
                    issues.append(("오류", "강사 불가", f"{label}: {', '.join(unavailable)}교시 불가"))
                if unset:
                    issues.append(("확인 필요", "강사 가능 시간 미설정", f"{label}: {', '.join(unset)}교시 미설정"))
        return issues
    finally:
        db.conn.rollback()
