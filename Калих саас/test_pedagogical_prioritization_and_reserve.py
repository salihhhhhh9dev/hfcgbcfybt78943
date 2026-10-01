"""
test_pedagogical_prioritization_and_reserve.py — Тесты педагогической приоритизации и резервных дней.

Проверяет:
1. LyceumSettings.reserve_days_count = 3 по умолчанию.
2. generate_academic_calendar_slots удерживает ровно reserve_days_count последних рабочих дней учебного года.
3. В расписании группы «ВЕБ-25» последние 3 рабочих дня учебного года содержат ровно 0 занятий.
4. Все 15 общеобразовательных предметов (952ч) завершаются на 100% до середины мая (до 15 мая).
5. Завершающие недели расписания (апрель-май) отведены под профессиональный компонент (практика и программирование).
6. 0 сдваиваний пар на протяжении всех 206 учебных дней.
7. Сетка звонков: 205 полных дней по 4 слота (7ч) + 1 финальный день (5ч) = 1440ч.
8. API /settings и /api/schedule/generate корректно принимают и сохраняют reserve_days_count.
"""

import unittest
from datetime import date, timedelta
from collections import defaultdict
import openpyxl

from app import app
from models import (
    db, Lyceum, LyceumSettings, StudentGroup, SubjectCurriculum,
    ScheduleAssignment, SlotType, AcademicHoliday
)
from academic_calendar import generate_academic_calendar_slots
from seed_db import seed_database
from excel_exporter import generate_excel_matrix


class TestPedagogicalPrioritizationAndReserve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            seed_database()

    def setUp(self):
        self.app_context = app.app_context()
        self.app_context.push()
        self.client = app.test_client()

    def tearDown(self):
        self.app_context.pop()

    def test_01_lyceum_settings_reserve_days_default(self):
        """1. LyceumSettings содержит reserve_days_count со значением 3 по умолчанию."""
        lyceum = Lyceum.query.first()
        self.assertIsNotNone(lyceum)
        self.assertIsNotNone(lyceum.settings)
        self.assertEqual(lyceum.settings.reserve_days_count, 3)

    def test_02_calendar_slot_generator_withholds_reserve_days(self):
        """2. generate_academic_calendar_slots отсекает последние reserve_days_count рабочих дней учебного года."""
        start = date(2026, 9, 1)
        end = date(2027, 6, 30)
        holidays = {date(2026, 11, 7), date(2027, 1, 1), date(2027, 5, 9)}
        weekdays = [0, 1, 2, 3, 4, 5]

        # Без резерва (reserve_days_count = 0)
        slots_no_reserve = generate_academic_calendar_slots(
            start_date=start, end_date=end,
            working_weekdays=weekdays, holiday_dates=holidays,
            reserve_days_count=0
        )
        days_no_reserve = sorted(list(set(s['date'] for s in slots_no_reserve)))

        # С резервом (reserve_days_count = 3)
        slots_with_reserve = generate_academic_calendar_slots(
            start_date=start, end_date=end,
            working_weekdays=weekdays, holiday_dates=holidays,
            reserve_days_count=3
        )
        days_with_reserve = sorted(list(set(s['date'] for s in slots_with_reserve)))

        self.assertEqual(len(days_with_reserve), len(days_no_reserve) - 3)
        # Последние 3 рабочих дня должны отсутствовать в слотах с резервом
        last_3_days = days_no_reserve[-3:]
        for d in last_3_days:
            self.assertNotIn(d, days_with_reserve, f"Резервный день {d} не должен присутствовать в учебных слотах")

    def test_03_end_of_year_reserve_days_empty_of_lessons(self):
        """3. Последние 3 рабочих дня учебного года содержат ровно 0 назначенных занятий."""
        lyceum = Lyceum.query.first()
        settings = lyceum.settings
        holiday_dates = {h.date for h in lyceum.holidays}

        # Все рабочие дни учебного года до end_date
        all_working_days = []
        cur = settings.academic_year_start
        while cur <= settings.academic_year_end:
            if cur.weekday() in settings.working_days_mask and cur not in holiday_dates:
                all_working_days.append(cur)
            cur += timedelta(days=1)

        last_reserve_days = all_working_days[-settings.reserve_days_count:]
        self.assertEqual(len(last_reserve_days), 3)

        # Проверяем, что в ScheduleAssignment на эти даты нет ни одного занятия
        reserve_assignments = ScheduleAssignment.query.filter(
            ScheduleAssignment.lyceum_id == lyceum.id,
            ScheduleAssignment.date.in_(last_reserve_days)
        ).all()
        self.assertEqual(
            len(reserve_assignments), 0,
            f"В резервные дни обнаружены занятия: {[(a.date, a.subject.subject_name) for a in reserve_assignments]}"
        )

    def test_04_general_education_completed_ahead_of_time(self):
        """4. Все общеобразовательные дисциплины (15 предметов, 952ч) завершаются на 100% до середины мая."""
        group = StudentGroup.query.filter_by(name="ВЕБ-25").first()
        self.assertIsNotNone(group)

        gen_subjects = SubjectCurriculum.query.filter_by(
            group_id=group.id,
            is_general_education=True
        ).all()
        self.assertEqual(len(gen_subjects), 15, "Должно быть ровно 15 общеобразовательных предметов")
        self.assertEqual(sum(s.total_hours for s in gen_subjects), 952)

        # Все часы распределены
        for s in gen_subjects:
            self.assertEqual(s.allocated_hours, s.total_hours, f"{s.subject_name} должен быть покрыт на 100%")
            self.assertEqual(s.remaining_hours, 0)

        # Проверяем дату последнего занятия для каждого общеобразовательного предмета
        mid_may = date(2027, 5, 15)
        for s in gen_subjects:
            last_assignment = ScheduleAssignment.query.filter_by(
                subject_id=s.id
            ).order_by(ScheduleAssignment.date.desc()).first()
            self.assertIsNotNone(last_assignment, f"Предмет {s.subject_name} должен иметь занятия")
            self.assertLess(
                last_assignment.date, mid_may,
                f"Предмет {s.subject_name} завершился {last_assignment.date}, что позже середины мая ({mid_may})"
            )

    def test_05_final_weeks_devoted_to_vocational_practice(self):
        """5. Завершающие недели учебного расписания отведены под профессиональное обучение и программирование."""
        group = StudentGroup.query.filter_by(name="ВЕБ-25").first()

        # Дата самого последнего общеобразовательного занятия
        gen_subjs = SubjectCurriculum.query.filter_by(group_id=group.id, is_general_education=True).all()
        gen_ids = [s.id for s in gen_subjs]
        last_gen_assignment = ScheduleAssignment.query.filter(
            ScheduleAssignment.group_id == group.id,
            ScheduleAssignment.subject_id.in_(gen_ids)
        ).order_by(ScheduleAssignment.date.desc()).first()
        self.assertIsNotNone(last_gen_assignment)

        last_gen_date = last_gen_assignment.date

        # Все занятия после этой даты обязаны быть строго профессиональными
        subsequent_assignments = ScheduleAssignment.query.filter(
            ScheduleAssignment.group_id == group.id,
            ScheduleAssignment.date > last_gen_date
        ).order_by(ScheduleAssignment.date).all()

        self.assertGreater(len(subsequent_assignments), 0, "После завершения общеобразовательных предметов должны оставаться занятия")
        
        # Общее число часов после окончания общеобразовательного цикла
        voc_hours_after = sum(2 if a.slot_type == SlotType.PAIR else 1 for a in subsequent_assignments)
        self.assertGreaterEqual(voc_hours_after, 100, f"В финальный период должно оставаться не менее ~100 часов практики, факт: {voc_hours_after}ч")

        for a in subsequent_assignments:
            self.assertFalse(
                a.subject.is_general_education,
                f"В завершающий период обнаружен общеобразовательный предмет: {a.subject.subject_name} на дату {a.date}"
            )

    def test_06_anti_doubling_zero_duplicate_pairs(self):
        """6. 0 сдваиваний пар на протяжении всех учебных дней."""
        assignments = ScheduleAssignment.query.order_by(ScheduleAssignment.date, ScheduleAssignment.slot_number).all()
        day_slots = defaultdict(dict)
        for a in assignments:
            day_slots[a.date][a.slot_number] = a

        for d, sdict in day_slots.items():
            pair_subjs = [sdict[s].subject_id for s in (1, 2, 3) if s in sdict]
            self.assertEqual(
                len(pair_subjs), len(set(pair_subjs)),
                f"Обнаружено сдваивание пар на дату {d}: {[sdict[s].subject.subject_name for s in (1, 2, 3) if s in sdict]}"
            )

    def test_07_grid_structure_and_coverage(self):
        """7. 205 полных дней по 4 слота (7ч) + 1 финальный день (5ч) = 1440ч, 823 занятия."""
        assignments = ScheduleAssignment.query.order_by(ScheduleAssignment.date, ScheduleAssignment.slot_number).all()
        self.assertEqual(len(assignments), 823)

        day_slots = defaultdict(dict)
        for a in assignments:
            day_slots[a.date][a.slot_number] = a

        self.assertEqual(len(day_slots), 206)
        full_days = sum(1 for d, sl in day_slots.items() if len(sl) == 4)
        self.assertEqual(full_days, 205)

        total_hours = sum(2 if a.slot_type == SlotType.PAIR else 1 for a in assignments)
        self.assertEqual(total_hours, 1440)

    def test_08_api_settings_reserve_days_persistence(self):
        """8. API /settings и /api/schedule/generate корректно сохраняют reserve_days_count."""
        # Login admin
        self.client.post("/login", data={"email": "admin@lyceum14.edu", "password": "password123"}, follow_redirects=True)

        # POST /settings with reserve_days_count = 5
        resp = self.client.post("/settings", json={
            "academic_year_start": "2026-09-01",
            "academic_year_end": "2027-06-30",
            "pairs_per_day": 3,
            "single_lessons_per_day": 1,
            "reserve_days_count": 5,
            "works_on_saturdays": True
        })
        self.assertEqual(resp.status_code, 200)

        lyceum = Lyceum.query.first()
        self.assertEqual(lyceum.settings.reserve_days_count, 5)

        # POST /api/schedule/generate with reserve_days_count = 4
        resp_gen = self.client.post("/api/schedule/generate", json={
            "reserve_days_count": 4
        })
        self.assertEqual(resp_gen.status_code, 200)
        self.assertTrue(resp_gen.get_json()["success"])
        self.assertEqual(lyceum.settings.reserve_days_count, 4)

        # Edge case: reserve_days_count = 0 via /settings
        resp_zero = self.client.post("/settings", json={
            "reserve_days_count": 0
        })
        self.assertEqual(resp_zero.status_code, 200)
        self.assertEqual(lyceum.settings.reserve_days_count, 0)

        # Revert back to 3 via /api/schedule/generate
        resp_revert = self.client.post("/api/schedule/generate", json={
            "reserve_days_count": 3
        })
        self.assertEqual(resp_revert.status_code, 200)
        self.assertEqual(lyceum.settings.reserve_days_count, 3)

    def test_09_curriculum_auto_detection_and_edge_reserves(self):
        """9. Автоматическая классификация предметов и граничные значения резервных дней."""
        # Test auto-detection in SubjectCurriculum
        s_alg = SubjectCurriculum(name="Алгебра", total_hours=100)
        self.assertTrue(s_alg.is_general_education)
        self.assertEqual(s_alg.subject_type, "general")

        s_prog = SubjectCurriculum(name="Основы программирования", total_hours=60)
        self.assertFalse(s_prog.is_general_education)
        self.assertEqual(s_prog.subject_type, "vocational")

        s_pract = SubjectCurriculum(name="Производственная практика", total_hours=200)
        self.assertFalse(s_pract.is_general_education)
        self.assertEqual(s_pract.subject_type, "vocational")

        # Test explicit reserve days on custom short period
        slots_short = generate_academic_calendar_slots(
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 15),
            working_weekdays=[0, 1, 2, 3, 4],
            reserve_days_count=2
        )
        unique_dates = sorted(list(set(s['date'] for s in slots_short)))
        # Total working days between Sept 1 and Sept 15: 11 days (Sept 1,2,3,4, 7,8,9,10,11, 14,15). With 2 reserve days: 9 days.
        self.assertEqual(len(unique_dates), 9)


if __name__ == "__main__":
    unittest.main()
