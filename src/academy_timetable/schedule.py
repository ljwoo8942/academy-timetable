"""수동 시간표와 반별 주간 시수 관리."""

from typing import NamedTuple, Optional

from .db import DAYS, facility_tags


class RoomLesson(NamedTuple):
    id: int
    weekday: int
    start: int
    length: int
    cohort: str
    subject: str
    teacher: str
    room_id: Optional[int]
    room: str
    locked: int
    student_count: Optional[int]
    required_facilities: str


class RoomSuggestion(NamedTuple):
    lesson: RoomLesson
    room_id: Optional[int]
    result: str


def room_fits(student_count, capacity):
    return student_count is None or capacity is None or student_count <= capacity


def missing_facilities(required, available):
    registered = {tag.casefold() for tag in facility_tags(available)}
    return [tag for tag in facility_tags(required) if tag.casefold() not in registered]


class Schedule:
    def __init__(self, db):
        self.db = db
        self.conn = db.conn

    def transaction(self):
        return self.db.transaction()

    def quotas(self, cohort_id):
        return self.conn.execute("""
            SELECT q.subject_id, s.name, q.weekly_periods, q.session_length,
                   COALESCE((SELECT SUM(l.length) FROM lessons l
                             WHERE l.cohort_id=q.cohort_id AND l.subject_id=q.subject_id), 0), s.active
            FROM quotas q JOIN subjects s ON s.id=q.subject_id
            WHERE q.cohort_id=? ORDER BY s.name
        """, (cohort_id,)).fetchall()

    def save_quota(self, cohort_id, subject_id, weekly, length):
        if not isinstance(weekly, int) or not 1 <= weekly <= 55 or length not in (1, 2):
            raise ValueError("주간 시수와 수업 길이를 확인하세요.")
        if weekly % length:
            raise ValueError("주간 시수는 수업 길이로 나누어떨어져야 합니다.")
        with self.transaction():
            if not self.conn.execute("SELECT 1 FROM cohorts WHERE id=?", (cohort_id,)).fetchone():
                raise ValueError("반을 선택하세요.")
            subject = self.conn.execute("SELECT active FROM subjects WHERE id=?", (subject_id,)).fetchone()
            if not subject or not subject[0]:
                raise ValueError("활성 과목을 선택하세요.")
            assigned = self.conn.execute("SELECT COALESCE(SUM(length),0), MIN(length), MAX(length) FROM lessons WHERE cohort_id=? AND subject_id=?", (cohort_id, subject_id)).fetchone()
            if weekly < assigned[0] or (assigned[0] and (assigned[1] != length or assigned[2] != length)):
                raise ValueError("이미 배정된 시수보다 줄이거나 기존 수업과 다른 길이로 변경할 수 없습니다.")
            self.conn.execute("""INSERT INTO quotas VALUES (?,?,?,?)
                ON CONFLICT(cohort_id,subject_id) DO UPDATE SET weekly_periods=excluded.weekly_periods, session_length=excluded.session_length""",
                (cohort_id, subject_id, weekly, length))

    def delete_quota(self, cohort_id, subject_id):
        with self.transaction():
            if self.conn.execute("SELECT 1 FROM lessons WHERE cohort_id=? AND subject_id=?", (cohort_id, subject_id)).fetchone():
                raise ValueError("배정된 수업을 먼저 삭제하세요.")
            self.conn.execute("DELETE FROM quotas WHERE cohort_id=? AND subject_id=?", (cohort_id, subject_id))

    def availability(self, term_id, teacher_id):
        return self.conn.execute("""SELECT weekday, period, status FROM teacher_availability
            WHERE term_id=? AND teacher_id=? ORDER BY weekday, period""", (term_id, teacher_id)).fetchall()

    def set_availability(self, term_id, teacher_id, cells, status):
        cells = set(cells)
        if status not in ("AVAILABLE", "UNAVAILABLE", "UNSET") or not cells or any(
            day not in range(len(DAYS)) or period not in range(1, 12) for day, period in cells
        ):
            raise ValueError("요일, 교시 및 가능 상태를 확인하세요.")
        with self.transaction():
            if not self.conn.execute("SELECT 1 FROM terms WHERE id=?", (term_id,)).fetchone() or not self.conn.execute(
                "SELECT 1 FROM teachers WHERE id=?", (teacher_id,)
            ).fetchone():
                raise ValueError("학기와 강사를 선택하세요.")
            if status == "UNAVAILABLE":
                for day, period in cells:
                    lesson = self.conn.execute("""SELECT c.name, l.start_period, l.length FROM lessons l
                        JOIN cohorts c ON c.id=l.cohort_id WHERE c.term_id=? AND l.teacher_id=?
                        AND l.weekday=? AND l.start_period<=? AND l.start_period+l.length>? LIMIT 1""",
                        (term_id, teacher_id, day, period, period)).fetchone()
                    if lesson:
                        raise ValueError(f"{DAYS[day]}요일 {period}교시에 {lesson[0]}의 수업이 이미 배정되어 있습니다. 먼저 수업을 이동하거나 삭제하세요.")
            for day, period in cells:
                if status == "UNSET":
                    self.conn.execute("DELETE FROM teacher_availability WHERE term_id=? AND teacher_id=? AND weekday=? AND period=?",
                                      (term_id, teacher_id, day, period))
                else:
                    self.conn.execute("""INSERT INTO teacher_availability VALUES (?,?,?,?,?)
                        ON CONFLICT(term_id,teacher_id,weekday,period) DO UPDATE SET status=excluded.status""",
                        (term_id, teacher_id, day, period, status))

    def teacher_loads(self, term_id):
        return self.conn.execute("""SELECT l.teacher_id, l.subject_id, SUM(l.length) FROM lessons l
            JOIN cohorts c ON c.id=l.cohort_id WHERE c.term_id=? GROUP BY l.teacher_id,l.subject_id""", (term_id,)).fetchall()

    def lessons(self, cohort_id):
        return self.conn.execute("""SELECT l.id, l.weekday, l.start_period, l.length, s.name, t.name,
            COALESCE(r.name,''), l.locked, l.subject_id, l.teacher_id, l.room_id
            FROM lessons l JOIN subjects s ON s.id=l.subject_id JOIN teachers t ON t.id=l.teacher_id
            LEFT JOIN rooms r ON r.id=l.room_id WHERE l.cohort_id=? ORDER BY l.weekday,l.start_period""", (cohort_id,)).fetchall()

    def room_lessons(self, term_id, lesson_id=None):
        return [RoomLesson(*row) for row in self.conn.execute("""
            SELECT l.id, l.weekday, l.start_period, l.length, c.name, s.name, t.name,
                   l.room_id, COALESCE(r.name,''), l.locked, c.student_count, s.required_facilities
            FROM lessons l JOIN cohorts c ON c.id=l.cohort_id
            JOIN subjects s ON s.id=l.subject_id JOIN teachers t ON t.id=l.teacher_id
            LEFT JOIN rooms r ON r.id=l.room_id
            WHERE c.term_id=? AND (? IS NULL OR l.id=?)
            ORDER BY l.room_id IS NOT NULL, l.weekday, l.start_period, c.name, l.id
        """, (term_id, lesson_id, lesson_id))]

    def _overlapping_lessons(self, term_id, weekday, start, length, lesson_id):
        return self.conn.execute("""
            SELECT c.name,t.name,COALESCE(r.name,''),l.cohort_id,l.teacher_id,l.room_id
            FROM lessons l JOIN cohorts c ON c.id=l.cohort_id JOIN teachers t ON t.id=l.teacher_id
            LEFT JOIN rooms r ON r.id=l.room_id WHERE c.term_id=? AND l.weekday=? AND l.id != ?
            AND l.start_period < ? AND l.start_period+l.length > ?
        """, (term_id, weekday, lesson_id or 0, start + length, start))

    def available_rooms(self, term_id, lesson):
        busy = {row[5] for row in self._overlapping_lessons(term_id, lesson.weekday, lesson.start, lesson.length, lesson.id)}
        return [
            (room_id, name) for room_id, name, capacity, facilities in self.conn.execute(
                "SELECT id, name, capacity, facilities FROM rooms ORDER BY name"
            )
            if room_id not in busy and room_fits(lesson.student_count, capacity)
            and not missing_facilities(lesson.required_facilities, facilities)
        ]

    def suggest_rooms(self, term_id):
        self.conn.execute("BEGIN")
        try:
            self.db.assert_current()
            return self._room_suggestions(term_id)
        finally:
            self.conn.rollback()

    def _room_suggestions(self, term_id):
        lessons = [lesson for lesson in self.room_lessons(term_id) if lesson.room_id is None]
        capacities = self.db.capacity_values("rooms")
        candidates = {}
        suggestions = {}
        for lesson in lessons:
            if lesson.locked:
                reason = "수업 잠김"
            elif lesson.student_count is None:
                reason = "반 인원 미설정"
            else:
                available = self.available_rooms(term_id, lesson)
                confirmed = [(room_id, name) for room_id, name in available if capacities[room_id] is not None]
                if confirmed:
                    candidates[lesson] = sorted(confirmed, key=lambda room: capacities[room[0]])
                    reason = "조건을 충족하는 강의실을 다른 수업에 제안함"
                else:
                    reason = "후보 강의실 정원 미설정" if available else "시간·정원·시설 조건을 충족하는 빈 강의실 없음"
            suggestions[lesson.id] = RoomSuggestion(lesson, None, reason)

        reserved = set()
        # shortcut: first-fit can leave lessons unassigned, use a solver if maximum coverage is needed.
        for lesson in sorted(candidates, key=lambda item: (len(candidates[item]), -item.length)):
            for room_id, name in candidates[lesson]:
                cells = {(room_id, lesson.weekday, period) for period in range(lesson.start, lesson.start + lesson.length)}
                if cells.isdisjoint(reserved):
                    reserved.update(cells)
                    suggestions[lesson.id] = RoomSuggestion(lesson, room_id, name)
                    break
        return list(suggestions.values())

    def apply_room_suggestions(self, term_id, suggestions):
        with self.transaction():
            if self._room_suggestions(term_id) != suggestions:
                raise ValueError("미리보기 이후 제안 결과가 변경되었습니다. 제안을 다시 확인하세요.")
            self.conn.executemany("UPDATE lessons SET room_id=? WHERE id=?", (
                (room_id, lesson.id) for lesson, room_id, _ in suggestions if room_id is not None
            ))

    def _validate_room(self, room_id, student_count, required_facilities):
        room = self.conn.execute("SELECT capacity, facilities FROM rooms WHERE id=?", (room_id,)).fetchone()
        if room is None:
            raise ValueError("강의실을 확인하세요.")
        if not room_fits(student_count, room[0]):
            raise ValueError(f"강의실 정원이 부족합니다. 반 인원 {student_count}명 · 정원 {room[0]}명")
        missing = missing_facilities(required_facilities, room[1])
        if missing:
            raise ValueError(f"필수 시설이 등록되지 않았습니다. {', '.join(missing)}")

    def assign_room(self, term_id, lesson, room_id):
        with self.transaction():
            current = self.room_lessons(term_id, lesson.id)
            if not current or current[0] != lesson:
                raise ValueError("수업 정보가 변경되었습니다. 목록을 새로고침한 뒤 다시 선택하세요.")
            if lesson.locked:
                raise ValueError("잠긴 수업은 시간표 편집에서 먼저 잠금을 해제하세요.")
            if room_id is not None:
                self._validate_room(room_id, lesson.student_count, lesson.required_facilities)
                if any(row[5] == room_id for row in self._overlapping_lessons(
                    term_id, lesson.weekday, lesson.start, lesson.length, lesson.id
                )):
                    raise ValueError("강의실이 해당 교시에 이미 배정되어 있습니다.")
            self.conn.execute("UPDATE lessons SET room_id=? WHERE id=?", (room_id, lesson.id))

    def assign(self, cohort_id, subject_id, teacher_id, room_id, weekday, start, lesson_id=None):
        with self.transaction():
            self._assign(cohort_id, subject_id, teacher_id, room_id, weekday, start, lesson_id)

    def _assign(self, cohort_id, subject_id, teacher_id, room_id, weekday, start, lesson_id=None):
        """호출자가 연 쓰기 트랜잭션 안에서 수업을 저장한다."""
        if weekday not in range(len(DAYS)) or start not in range(1, 12):
            raise ValueError("월~토와 1~11교시를 선택하세요.")
        quota = self.conn.execute("""SELECT q.weekly_periods,q.session_length,c.term_id,s.active,c.student_count,s.required_facilities
            FROM quotas q JOIN cohorts c ON c.id=q.cohort_id JOIN subjects s ON s.id=q.subject_id
            WHERE q.cohort_id=? AND q.subject_id=?""", (cohort_id, subject_id)).fetchone()
        if not quota or not quota[3]:
            raise ValueError("선택한 반에 활성 과목의 주간 시수를 먼저 설정하세요.")
        weekly, length, term_id, _, student_count, required_facilities = quota
        if not self.conn.execute("SELECT 1 FROM teachers WHERE id=?", (teacher_id,)).fetchone():
            raise ValueError("강사를 선택하세요.")
        eligible = self.db.eligible_teachers(subject_id)
        if eligible and teacher_id not in eligible:
            raise ValueError("선택한 강사는 이 과목의 담당 강사로 등록되지 않았습니다.")
        if room_id is not None:
            self._validate_room(room_id, student_count, required_facilities)
        if start + length - 1 > 11 or (length == 2 and start in (4, 8)):
            raise ValueError("연강은 11교시를 넘거나 점심·저녁 경계를 가로지를 수 없습니다.")
        unavailable = self.conn.execute("""SELECT period FROM teacher_availability
            WHERE term_id=? AND teacher_id=? AND weekday=? AND status='UNAVAILABLE'
            AND period>=? AND period<? ORDER BY period LIMIT 1""",
            (term_id, teacher_id, weekday, start, start + length)).fetchone()
        if unavailable:
            raise ValueError(f"강사가 {unavailable[0]}교시에 불가능으로 설정되어 있습니다.")
        if lesson_id is not None:
            old = self.conn.execute("SELECT cohort_id,subject_id,locked FROM lessons WHERE id=?", (lesson_id,)).fetchone()
            if not old or old[0] != cohort_id or old[1] != subject_id:
                raise ValueError("수업을 찾을 수 없거나 수업 대상이 변경되었습니다.")
            if old[2]:
                raise ValueError("잠긴 수업은 먼저 잠금을 해제하세요.")
        assigned = self.conn.execute("SELECT COALESCE(SUM(length),0) FROM lessons WHERE cohort_id=? AND subject_id=? AND id != ?", (cohort_id, subject_id, lesson_id or 0)).fetchone()[0]
        if assigned + length > weekly:
            raise ValueError("주간 설정 시수를 초과합니다.")
        for c, t, r, cid, tid, rid in self._overlapping_lessons(term_id, weekday, start, length, lesson_id):
            if cid != cohort_id and tid != teacher_id and (room_id is None or rid != room_id):
                continue
            reason = "반" if cid == cohort_id else "강사" if tid == teacher_id else "강의실"
            raise ValueError(f"{reason} 중복: {c} / {t}" + (f" / {r}" if r else ""))
        if lesson_id is None:
            return self.conn.execute("INSERT INTO lessons(cohort_id,subject_id,teacher_id,room_id,weekday,start_period,length) VALUES (?,?,?,?,?,?,?)",
                                     (cohort_id, subject_id, teacher_id, room_id, weekday, start, length)).lastrowid
        self.conn.execute("UPDATE lessons SET teacher_id=?, room_id=?, weekday=?, start_period=?, length=? WHERE id=?",
                          (teacher_id, room_id, weekday, start, length, lesson_id))

    def lock(self, lesson_id, locked):
        with self.transaction():
            self.conn.execute("UPDATE lessons SET locked=? WHERE id=?", (int(bool(locked)), lesson_id))

    def delete(self, lesson_id):
        with self.transaction():
            row = self.conn.execute("SELECT locked FROM lessons WHERE id=?", (lesson_id,)).fetchone()
            if not row:
                raise ValueError("수업을 찾을 수 없습니다.")
            if row[0]:
                raise ValueError("잠긴 수업은 먼저 잠금을 해제하세요.")
            self.conn.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
