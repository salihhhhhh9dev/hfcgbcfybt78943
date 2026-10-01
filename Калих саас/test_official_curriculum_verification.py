"""
Comprehensive Verification Script for Official Kyrgyz Republic Ministry Curriculum
Profession: «Разработчик web и мультимедийных приложений» (2513 Разработчик web-сайта, 3121 Web дизайнер).
Group: «ВЕБ-25» (1 курс, 2 года обучения, 1440 академических часов, 36 часов в неделю).
Tech Stack: Python, unittest, Flask, SQLAlchemy, openpyxl
"""

import unittest
from datetime import date, time
from io import BytesIO
import openpyxl

from app import app
from models import (
    db, Lyceum, Subscription, LyceumSettings, AcademicHoliday,
    User, Teacher, Room, StudentGroup, SubjectCurriculum, ScheduleAssignment, SlotType
)


class TestOfficialCurriculumVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            from seed_db import seed_database
            seed_database()

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def login(self, email="admin@lyceum14.edu", password="password123"):
        return self.client.post("/login", data={
            "email": email,
            "password": password
        }, follow_redirects=True)

    def test_01_lyceum_and_admin_setup(self):
        """Verify Lyceum tenant and admin account."""
        lyceum = Lyceum.query.first()
        self.assertIsNotNone(lyceum, "Lyceum tenant must exist")
        self.assertIn("Лицей №14", lyceum.name)

        admin = User.query.filter_by(email="admin@lyceum14.edu").first()
        self.assertIsNotNone(admin, "Admin user must exist")
        self.assertEqual(admin.role, "LYCEUM_ADMIN")

    def test_02_calendar_settings(self):
        """Verify calendar settings match Ministry Plan: Sept 1 2026 - June 30 2027, 6 working days, 3 pairs (36h/week)."""
        lyceum = Lyceum.query.first()
        settings = lyceum.settings
        self.assertIsNotNone(settings, "Lyceum settings must exist")
        self.assertEqual(settings.academic_year_start, date(2026, 9, 1))
        self.assertEqual(settings.academic_year_end, date(2027, 6, 30))
        self.assertEqual(settings.working_days_mask, [0, 1, 2, 3, 4, 5])
        self.assertEqual(settings.pairs_per_day, 3)
        self.assertEqual(settings.single_lessons_per_day, 1)

        # Holidays check
        holiday_dates = {h.date for h in lyceum.holidays}
        self.assertIn(date(2026, 11, 7), holiday_dates)
        self.assertIn(date(2027, 1, 1), holiday_dates)
        self.assertIn(date(2027, 3, 8), holiday_dates)
        self.assertIn(date(2027, 3, 21), holiday_dates)
        self.assertIn(date(2027, 5, 9), holiday_dates)
        # Sept 1 must NOT be an excluded holiday
        self.assertNotIn(date(2026, 9, 1), holiday_dates)

    def test_03_pedagogical_staffing_and_classrooms(self):
        """Verify realistic pedagogical staffing and classrooms."""
        lyceum = Lyceum.query.first()

        teachers = Teacher.query.filter_by(lyceum_id=lyceum.id).all()
        t_names = {t.full_name for t in teachers}
        self.assertGreaterEqual(len(teachers), 7)
        self.assertIn("Асанова Айгуль Бакытовна", t_names)  # Учитель кыргызского языка
        self.assertIn("Смирнова Елена Васильевна", t_names)  # Учитель русского языка
        self.assertIn("Исаков Данияр Алымкулович", t_names)  # Математик
        self.assertIn("Жумабеков Канат Темирович", t_names)  # Историк
        self.assertIn("Токтосунова Жылдыз Муратовна", t_names)  # Физик/химик
        self.assertIn("Калиев Самат Бектурович", t_names)  # IT/программирование
        self.assertIn("Бакиров Руслан Эркинович", t_names)  # Мастер ПО

        rooms = Room.query.filter_by(lyceum_id=lyceum.id).all()
        r_nums = {r.room_number for r in rooms}
        self.assertIn("Каб. 201", r_nums)
        self.assertIn("Каб. 202", r_nums)
        self.assertIn("Каб. 203", r_nums)
        self.assertIn("Компьютерная лаборатория №1", r_nums)
        self.assertIn("IT-мастерская (веб-разработка)", r_nums)
        self.assertIn("Спортзал", r_nums)

    def test_04_official_curriculum_breakdown_1440h(self):
        """Verify 1st year group «ВЕБ-25» has exactly 1440 hours matching official curriculum breakdown."""
        group = StudentGroup.query.filter_by(name="ВЕБ-25").first()
        self.assertIsNotNone(group, "Group ВЕБ-25 must exist")
        self.assertEqual(group.course_year, 1)
        self.assertEqual(group.years_of_study, 2)
        self.assertEqual(group.student_count, 25)

        subjs = SubjectCurriculum.query.filter_by(group_id=group.id).all()
        self.assertEqual(len(subjs), 23, "Must have exactly 23 subjects")

        subj_map = {s.subject_name: s.total_hours for s in subjs}

        # I. Общеобразовательный компонент (952 часа)
        gen_ed_expected = {
            "Кыргызский язык": 102,
            "Кыргызская литература": 34,
            "Русский язык": 68,
            "Русская литература": 102,
            "Иностранный язык (Английский)": 68,
            "История": 68,
            "Человек и общество": 34,
            "Алгебра": 102,
            "Геометрия": 34,
            "Биология": 34,
            "География": 34,
            "Физика / Астрономия": 102,
            "Химия": 68,
            "Допризывная подготовка": 68,
            "Физическое воспитание": 34,
        }
        for name, h in gen_ed_expected.items():
            self.assertIn(name, subj_map, f"Missing general subject: {name}")
            self.assertEqual(subj_map[name], h, f"Mismatch in hours for {name}")
        self.assertEqual(sum(gen_ed_expected.values()), 952)

        # II. Профессиональный компонент (488 часов)
        prof_expected = {
            "Охрана труда и производственная экология": 24,
            "Правовые основы профессиональной деятельности": 24,
            "Безопасный здоровый образ жизни": 24,
            "Основы компьютерных вычислений": 42,
            "Библиотека языков программирования": 30,
            "Основы программирования": 60,
            "Технология программирования": 40,
            "Производственное обучение (Практикум в лаборатории)": 244,
        }
        for name, h in prof_expected.items():
            self.assertIn(name, subj_map, f"Missing professional subject: {name}")
            self.assertEqual(subj_map[name], h, f"Mismatch in hours for {name}")
        self.assertEqual(sum(prof_expected.values()), 488)

        total_hours = sum(s.total_hours for s in subjs)
        self.assertEqual(total_hours, 1440, "Total curriculum must be exactly 1440 academic hours")

    def test_05_schedule_generation_100_percent_coverage(self):
        """Verify 100% of 1440 hours are allocated in ScheduleAssignment with zero conflicts, distinct pairs, and 4 slots/day."""
        group = StudentGroup.query.filter_by(name="ВЕБ-25").first()
        subjs = SubjectCurriculum.query.filter_by(group_id=group.id).all()

        total_planned = sum(s.total_hours for s in subjs)
        total_allocated = sum(s.allocated_hours for s in subjs)
        total_remaining = sum(s.remaining_hours for s in subjs)

        self.assertEqual(total_planned, 1440)
        self.assertEqual(total_allocated, 1440, "All 1440 hours must be allocated")
        self.assertEqual(total_remaining, 0, "No remaining unallocated hours allowed")

        assignments = ScheduleAssignment.query.filter_by(group_id=group.id).all()
        # Sum of hours: pairs = 2h, single lessons = 1h
        total_assignment_hours = sum(2 if a.slot_type == SlotType.PAIR else 1 for a in assignments)
        self.assertEqual(total_assignment_hours, 1440, "Total assignment hours must equal 1440")

        from collections import defaultdict
        day_slots = defaultdict(dict)
        teacher_slots = set()
        room_slots = set()

        for a in assignments:
            # Must be on a working day Monday (0) through Saturday (5)
            self.assertIn(a.date.weekday(), [0, 1, 2, 3, 4, 5])
            day_slots[a.date][a.slot_number] = a

            if a.slot_number in (1, 2, 3):
                self.assertEqual(a.slot_type, SlotType.PAIR)
            elif a.slot_number == 4:
                self.assertEqual(a.slot_type, SlotType.SINGLE_LESSON)

            t_key = (a.date, a.slot_number, a.teacher_id)
            self.assertNotIn(t_key, teacher_slots, f"Teacher conflict detected: {t_key}")
            teacher_slots.add(t_key)

            if a.room_id:
                r_key = (a.date, a.slot_number, a.room_id)
                self.assertNotIn(r_key, room_slots, f"Room conflict detected: {r_key}")
                room_slots.add(r_key)

        # a) Every populated day has 3 pairs and 1 single lesson (slot_numbers 1, 2, 3, 4)
        for d, sdict in day_slots.items():
            # b) In any given day, slot 1, slot 2, and slot 3 have three mutually distinct subject_ids
            pair_subjs = [sdict[s].subject_id for s in [1, 2, 3] if s in sdict]
            self.assertEqual(len(pair_subjs), len(set(pair_subjs)), f"Duplicate pair subject on {d}")
            # Ensure max 3 hours per subject per day
            day_subject_hours = defaultdict(int)
            for s_num, a in sdict.items():
                hrs = 2 if a.slot_type == SlotType.PAIR else 1
                day_subject_hours[a.subject_id] += hrs
            for subj_id, h in day_subject_hours.items():
                self.assertLessEqual(h, 3, f"Subject {subj_id} exceeded max 3 hours on {d}: {h}h")

    def test_06_web_schedule_view(self):
        """Verify /schedule route renders group «ВЕБ-25» timetable across weeks."""
        self.login()
        resp = self.client.get("/schedule")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("ВЕБ-25", html)
        self.assertIn("Понедельник", html)
        self.assertIn("Суббота", html)
        self.assertIn("1 пара", html)
        self.assertIn("4 урок", html)
        self.assertIn("100", html)  # 100% KPI completion

    def test_07_excel_export_matches_group(self):
        """Verify /export/excel produces workbook with 4 time slots on Sheet 1 and populated lessons."""
        self.login()
        resp = self.client.get("/export/excel")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers.get("Content-Type"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        wb = openpyxl.load_workbook(BytesIO(resp.data))
        self.assertIn("Группа ВЕБ-25", wb.sheetnames)
        ws = wb["Группа ВЕБ-25"]

        self.assertIn("РАСПИСАНИЕ ЗАНЯТИЙ", str(ws["A1"].value))
        self.assertIn("ВЕБ-25", str(ws["A1"].value))

        # Check Sheet 1 has 4 time slot rows (Row 5: 1-я пара, Row 6: 2-я пара, Row 7: 3-я пара, Row 8: 4-й урок)
        self.assertIn("1-я пара", str(ws["A5"].value))
        self.assertIn("08:30 - 10:00", str(ws["A5"].value))
        self.assertIn("2-я пара", str(ws["A6"].value))
        self.assertIn("10:10 - 11:40", str(ws["A6"].value))
        self.assertIn("3-я пара", str(ws["A7"].value))
        self.assertIn("12:00 - 13:30", str(ws["A7"].value))
        self.assertIn("4-й урок", str(ws["A8"].value))
        self.assertIn("13:40 - 14:25", str(ws["A8"].value))

        # Check all 6 days (Mon-Sat, columns B to G) for row 5 (1-я пара) and row 8 (4-й урок)
        for col_letter in ["B", "C", "D", "E", "F", "G"]:
            cell_val_5 = str(ws[f"{col_letter}5"].value)
            self.assertNotEqual(cell_val_5, "—", f"Cell {col_letter}5 should be populated")
            self.assertIn("\n", cell_val_5, f"Cell {col_letter}5 should contain multiline info")

            cell_val_8 = str(ws[f"{col_letter}8"].value)
            self.assertNotEqual(cell_val_8, "—", f"Cell {col_letter}8 (4-й урок) should be populated")
            self.assertIn("\n", cell_val_8, f"Cell {col_letter}8 should contain multiline info")

        # Check Sheet 2 (annual register) includes both pairs and single lessons
        sheet2_title = "Журнал ВЕБ-25 (Год)"
        self.assertIn(sheet2_title, wb.sheetnames)
        ws2 = wb[sheet2_title]
        assignments = ScheduleAssignment.query.all()
        types_in_register = set()
        for r in range(5, 5 + len(assignments)):
            types_in_register.add(str(ws2[f"D{r}"].value))
        self.assertTrue(any("урок" in t for t in types_in_register), "Sheet 2 must include single lessons")
        self.assertTrue(any("пара" in t for t in types_in_register), "Sheet 2 must include pairs")


if __name__ == "__main__":
    unittest.main()
