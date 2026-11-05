import unittest

from academy_timetable.db import Database
from academy_timetable.review import review_draft
from academy_timetable.schedule import Schedule


class DraftReviewTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.db.add("terms", "1학기")
        self.term = self.db.list("terms")[0][0]
        self.db.add("cohorts", "A반", self.term)
        self.db.add("subjects", "수학")
        self.db.add("teachers", "김강사")
        self.db.add("rooms", "101호")
        self.cohort = self.db.list("cohorts", self.term)[0][0]
        self.subject = self.db.list("subjects")[0][0]
        self.teacher = self.db.list("teachers")[0][0]
        self.room = self.db.list("rooms")[0][0]
        self.schedule = Schedule(self.db)

    def tearDown(self):
        self.db.conn.close()

    def test_incomplete_draft_is_reported_without_mutation(self):
        self.schedule.save_quota(self.cohort, self.subject, 4, 2)
        self.schedule.assign(self.cohort, self.subject, self.teacher, None, 0, 1)
        before = self.db.conn.total_changes
        rows = review_draft(self.db, self.term)
        categories = {category for _, category, _ in rows}
        self.assertTrue({"반 수", "미배정 시수", "강의실 미배정", "강사 가능 시간 미설정"} <= categories)
        self.assertTrue(all(status == "확인 필요" for status, _, _ in rows))
        self.assertEqual(self.db.conn.total_changes, before)
        self.assertIn("1, 2교시", next(detail for _, category, detail in rows if category == "강사 가능 시간 미설정"))
        self.schedule.set_availability(self.term, self.teacher, {(0, 1), (0, 2)}, "AVAILABLE")
        self.assertNotIn("강사 가능 시간 미설정", {category for _, category, _ in review_draft(self.db, self.term)})

    def test_detects_existing_conflicts_and_unavailability(self):
        self.schedule.save_quota(self.cohort, self.subject, 2, 2)
        self.schedule.assign(self.cohort, self.subject, self.teacher, self.room, 0, 1)
        with self.db.conn:
            self.db.conn.execute("""INSERT INTO lessons(cohort_id,subject_id,teacher_id,room_id,weekday,start_period,length)
                VALUES (?,?,?,?,?,?,?)""", (self.cohort, self.subject, self.teacher, self.room, 0, 1, 2))
            self.db.conn.execute("INSERT INTO teacher_availability VALUES (?,?,?,?,?)", (self.term, self.teacher, 0, 2, "UNAVAILABLE"))
        rows = review_draft(self.db, self.term)
        errors = {category for status, category, _ in rows if status == "오류"}
        self.assertTrue({"반 중복", "강사 중복", "강의실 중복", "시수 초과", "강사 불가"} <= errors)
        self.assertTrue(any("월요일 2교시" in detail for _, category, detail in rows if category == "강사 중복"))

    def test_different_term_is_not_included(self):
        self.db.add("terms", "2학기")
        other = next(row[0] for row in self.db.list("terms") if row[1] == "2학기")
        self.db.add("cohorts", "다른 반", other)
        other_cohort = self.db.list("cohorts", other)[0][0]
        self.schedule.save_quota(other_cohort, self.subject, 2, 2)
        self.schedule.assign(other_cohort, self.subject, self.teacher, None, 0, 1)
        self.assertFalse(any("다른 반" in detail for _, _, detail in review_draft(self.db, self.term)))
        with self.assertRaises(ValueError):
            review_draft(self.db, None)


if __name__ == "__main__":
    unittest.main()
