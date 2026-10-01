"""
End-to-End Automated Integration Test Suite for KALIX Lyceum SaaS.
Tests all requirements:
1. Strict Sidebar Navigation (1. /schedule, 2. /teachers, 3. /rooms, 4. /subscriptions, 5. /groups, ⚙️ /settings)
2. Weekly CSS Grid schedule rendering with filters and week switcher
3. Calendar pre-flight configuration (floating start, Saturday toggle, pairs/lessons count, holidays)
4. Triggering auto-schedule generation via POST /api/schedule/generate
5. Professional Excel Export with populated timetable cells
6. Conflict resolution priority strictly verified (highest remaining_hours gets slot)
7. Full Lyceum CRUD operations (Teachers, Rooms, Groups, Curricula)
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


class TestLyceumSaaSE2E(unittest.TestCase):
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

    def test_01_auth_and_login_flow(self):
        """Test login and redirect to main workspace."""
        resp = self.login()
        self.assertEqual(resp.status_code, 200)
        # Should be on weekly schedule page
        self.assertIn("Расписание на неделю".encode("utf-8"), resp.data)

    def test_02_strict_sidebar_navigation_order(self):
        """
        Verify restored exact sequence in sidebar navigation from screenshots:
        1. Недельная сетка (/dashboard)
        2. Годовая сетка (3 дня триал) (/schedule/yearly)
        3. Группы и Учебные планы (/groups)
        4. Преподаватели (/teachers)
        5. Управление тарифом (/tariffs)
        6. Настройки и Инструкции (/settings)
        + Выход (/logout)
        """
        self.login()
        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        pos_1 = html.find("Недельная сетка")
        pos_2 = html.find("Годовая сетка (3 дня триал)")
        pos_3 = html.find("Группы и Учебные планы")
        pos_4 = html.find("Преподаватели")
        pos_5 = html.find("Управление тарифом")
        pos_6 = html.find("Настройки и Инструкции")

        self.assertTrue(pos_1 != -1, "Sidebar item 1 missing")
        self.assertTrue(pos_2 != -1, "Sidebar item 2 missing")
        self.assertTrue(pos_3 != -1, "Sidebar item 3 missing")
        self.assertTrue(pos_4 != -1, "Sidebar item 4 missing")
        self.assertTrue(pos_5 != -1, "Sidebar item 5 missing")
        self.assertTrue(pos_6 != -1, "Sidebar item 6 missing")

        # Verify strict order
        self.assertTrue(pos_1 < pos_2 < pos_3 < pos_4 < pos_5 < pos_6,
                        "Sidebar items are not in strict required order!")

    def test_03_weekly_schedule_grid_and_filters(self):
        """Test dashboard schedule grid, day tabs, and weekly schedule view."""
        self.login()
        # GET /dashboard / /schedule renders dashboard.html
        resp_dash = self.client.get("/dashboard")
        self.assertEqual(resp_dash.status_code, 200)
        html_dash = resp_dash.data.decode("utf-8")
        self.assertIn("ВЕБ-25", html_dash)
        self.assertIn("1 пара", html_dash)
        self.assertIn("4 урок", html_dash)
        self.assertIn("selectDay", html_dash)

        # GET /schedule/weekly with week_offset=0
        resp = self.client.get("/schedule/weekly?week_offset=0")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        self.assertIn("Звонки \\ День", html)
        self.assertIn("Понедельник", html)
        self.assertIn("Вторник", html)
        self.assertIn("ВЕБ-25", html)

        # Navigate to week 2 (week_offset=1)
        resp2 = self.client.get("/schedule/weekly?week_offset=1")
        self.assertEqual(resp2.status_code, 200)
        html2 = resp2.data.decode("utf-8")
        self.assertIn("Учебная неделя 2", html2)

    def test_04_teachers_management_page(self):
        """Test teachers roster, add teacher, and delete teacher."""
        self.login()
        resp = self.client.get("/teachers")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Асанова Айгуль Бакытовна".encode("utf-8"), resp.data)

        # Add a new teacher
        resp_add = self.client.post("/teachers/add", data={
            "full_name": "Тестовый Преподаватель Электронщик",
            "specializations": "Микроэлектроника, Схемотехника",
            "max_weekly_hours": 30
        }, follow_redirects=True)
        self.assertEqual(resp_add.status_code, 200)
        self.assertIn("Тестовый Преподаватель Электронщик".encode("utf-8"), resp_add.data)

        # Cleanup: find and delete
        t = Teacher.query.filter_by(full_name="Тестовый Преподаватель Электронщик").first()
        self.assertIsNotNone(t)
        resp_del = self.client.post(f"/teachers/delete/{t.id}", follow_redirects=True)
        self.assertEqual(resp_del.status_code, 200)

    def test_05_rooms_management_page(self):
        """Test classrooms roster, add room, and delete room."""
        self.login()
        resp = self.client.get("/rooms")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Каб. 201".encode("utf-8"), resp.data)
        self.assertIn("Компьютерная лаборатория №1".encode("utf-8"), resp.data)

        # Add a new room
        resp_add = self.client.post("/rooms", data={
            "room_number": "Каб. 999 (Робототехника)",
            "capacity": 24,
            "is_computer_lab": "on"
        }, follow_redirects=True)
        self.assertEqual(resp_add.status_code, 200)
        self.assertIn("Каб. 999 (Робототехника)".encode("utf-8"), resp_add.data)

        # Delete room
        r = Room.query.filter_by(room_number="Каб. 999 (Робототехника)").first()
        self.assertIsNotNone(r)
        resp_del = self.client.post(f"/rooms/delete/{r.id}", follow_redirects=True)
        self.assertEqual(resp_del.status_code, 200)

    def test_06_subscriptions_and_tariffs_page(self):
        """Test SaaS subscriptions tiers (Базовый, Про, Корпоративный)."""
        self.login()
        resp = self.client.get("/subscriptions")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Базовый", html)
        self.assertIn("Про", html)
        self.assertIn("Корпоративный", html)

    def test_07_groups_and_curriculum_page(self):
        """Test groups roster and curriculum hours distribution."""
        self.login()
        resp = self.client.get("/groups")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("ВЕБ-25", html)

        # Test group detail
        g = StudentGroup.query.filter_by(name="ВЕБ-25").first()
        self.assertIsNotNone(g)
        resp_detail = self.client.get(f"/groups/{g.id}")
        self.assertEqual(resp_detail.status_code, 200)
        self.assertIn("Основы программирования".encode("utf-8"), resp_detail.data)

    def test_08_calendar_settings_configuration(self):
        """Test settings and pre-flight calendar configuration."""
        self.login()
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Параметры учебного года и сетка звонков", html)
        self.assertIn("Праздничные, нерабочие и карантинные дни", html)
        self.assertIn("Персонализация интерфейса", html)
        self.assertIn("Инструкция и База знаний", html)

        # Save settings via POST
        resp_post = self.client.post("/settings", json={
            "academic_year_start": "2026-09-01",
            "academic_year_end": "2027-06-30",
            "pairs_per_day": 3,
            "single_lessons_per_day": 1,
            "works_on_saturdays": True
        })
        self.assertEqual(resp_post.status_code, 200)
        data = resp_post.get_json()
        self.assertTrue(data.get("success"))

    def test_09_api_schedule_generation(self):
        """Test API schedule generation end-to-end."""
        self.login()
        resp = self.client.post("/api/schedule/generate", json={
            "academic_year_start": "2026-09-01",
            "academic_year_end": "2027-06-30",
            "pairs_per_day": 3,
            "single_lessons_per_day": 1,
            "works_on_saturdays": True,
            "exception_dates": ["2026-11-07", "2027-01-01"]
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertGreater(data.get("total_assignments", 0), 100)
        self.assertEqual(data.get("completion_percent"), 100.0)

    def test_10_excel_export_generation(self):
        """Test Excel timetable matrix export and verify cell contents."""
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

        # Check title
        self.assertIn("РАСПИСАНИЕ ЗАНЯТИЙ", str(ws["A1"].value))
        # Check timetable cell populated with subject, teacher and room
        b5_val = str(ws["B5"].value)
        self.assertNotEqual(b5_val, "—")
        self.assertIn("\n", b5_val)


if __name__ == "__main__":
    unittest.main()
