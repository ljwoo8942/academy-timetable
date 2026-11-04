"""수동 시간표와 반별 주간 시수 관리."""


class Schedule:
    def __init__(self, db):
        self.db = db
        self.conn = db.conn

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
        with self.conn:
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
        with self.conn:
            if self.conn.execute("SELECT 1 FROM lessons WHERE cohort_id=? AND subject_id=?", (cohort_id, subject_id)).fetchone():
                raise ValueError("배정된 수업을 먼저 삭제하세요.")
            self.conn.execute("DELETE FROM quotas WHERE cohort_id=? AND subject_id=?", (cohort_id, subject_id))

    def teacher_loads(self, term_id):
        return self.conn.execute("""SELECT l.teacher_id, l.subject_id, SUM(l.length) FROM lessons l
            JOIN cohorts c ON c.id=l.cohort_id WHERE c.term_id=? GROUP BY l.teacher_id,l.subject_id""", (term_id,)).fetchall()

    def lessons(self, cohort_id):
        return self.conn.execute("""SELECT l.id, l.weekday, l.start_period, l.length, s.name, t.name,
            COALESCE(r.name,''), l.locked, l.subject_id, l.teacher_id, l.room_id
            FROM lessons l JOIN subjects s ON s.id=l.subject_id JOIN teachers t ON t.id=l.teacher_id
            LEFT JOIN rooms r ON r.id=l.room_id WHERE l.cohort_id=? ORDER BY l.weekday,l.start_period""", (cohort_id,)).fetchall()

    def assign(self, cohort_id, subject_id, teacher_id, room_id, weekday, start, lesson_id=None):
        if weekday not in range(5) or start not in range(1, 12):
            raise ValueError("월~금과 1~11교시를 선택하세요.")
        with self.conn:
            quota = self.conn.execute("""SELECT q.weekly_periods,q.session_length,c.term_id,s.active
                FROM quotas q JOIN cohorts c ON c.id=q.cohort_id JOIN subjects s ON s.id=q.subject_id
                WHERE q.cohort_id=? AND q.subject_id=?""", (cohort_id, subject_id)).fetchone()
            if not quota or not quota[3]:
                raise ValueError("선택한 반에 활성 과목의 주간 시수를 먼저 설정하세요.")
            weekly, length, term_id, _ = quota
            if not self.conn.execute("SELECT 1 FROM teachers WHERE id=?", (teacher_id,)).fetchone():
                raise ValueError("강사를 선택하세요.")
            if room_id is not None and not self.conn.execute("SELECT 1 FROM rooms WHERE id=?", (room_id,)).fetchone():
                raise ValueError("강의실을 확인하세요.")
            if start + length - 1 > 11 or (length == 2 and start in (4, 8)):
                raise ValueError("연강은 11교시를 넘거나 점심·저녁 경계를 가로지를 수 없습니다.")
            if lesson_id is not None:
                old = self.conn.execute("SELECT cohort_id,subject_id,locked FROM lessons WHERE id=?", (lesson_id,)).fetchone()
                if not old or old[0] != cohort_id or old[1] != subject_id:
                    raise ValueError("수업을 찾을 수 없거나 수업 대상이 변경되었습니다.")
                if old[2]:
                    raise ValueError("잠긴 수업은 먼저 잠금을 해제하세요.")
            assigned = self.conn.execute("SELECT COALESCE(SUM(length),0) FROM lessons WHERE cohort_id=? AND subject_id=? AND id != ?", (cohort_id, subject_id, lesson_id or 0)).fetchone()[0]
            if assigned + length > weekly:
                raise ValueError("주간 설정 시수를 초과합니다.")
            conflicts = self.conn.execute("""SELECT c.name,t.name,COALESCE(r.name,''),l.cohort_id,l.teacher_id,l.room_id
                FROM lessons l JOIN cohorts c ON c.id=l.cohort_id JOIN teachers t ON t.id=l.teacher_id
                LEFT JOIN rooms r ON r.id=l.room_id WHERE c.term_id=? AND l.weekday=? AND l.id != ?
                AND l.start_period < ? AND l.start_period+l.length > ?
                AND (l.cohort_id=? OR l.teacher_id=? OR (l.room_id IS NOT NULL AND l.room_id=?))""",
                (term_id, weekday, lesson_id or 0, start + length, start, cohort_id, teacher_id, room_id)).fetchall()
            if conflicts:
                c, t, r, cid, tid, rid = conflicts[0]
                reason = "반" if cid == cohort_id else "강사" if tid == teacher_id else "강의실"
                raise ValueError(f"{reason} 중복: {c} / {t}" + (f" / {r}" if r else ""))
            if lesson_id is None:
                self.conn.execute("INSERT INTO lessons(cohort_id,subject_id,teacher_id,room_id,weekday,start_period,length) VALUES (?,?,?,?,?,?,?)",
                                  (cohort_id, subject_id, teacher_id, room_id, weekday, start, length))
            else:
                self.conn.execute("UPDATE lessons SET teacher_id=?, room_id=?, weekday=?, start_period=?, length=? WHERE id=?",
                                  (teacher_id, room_id, weekday, start, length, lesson_id))

    def lock(self, lesson_id, locked):
        with self.conn:
            self.conn.execute("UPDATE lessons SET locked=? WHERE id=?", (int(bool(locked)), lesson_id))

    def delete(self, lesson_id):
        with self.conn:
            row = self.conn.execute("SELECT locked FROM lessons WHERE id=?", (lesson_id,)).fetchone()
            if not row:
                raise ValueError("수업을 찾을 수 없습니다.")
            if row[0]:
                raise ValueError("잠긴 수업은 먼저 잠금을 해제하세요.")
            self.conn.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
