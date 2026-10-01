"""
Database Seeder Script (`seed_db.py`)
Populates database with official curriculum from the Ministry of Education of the Kyrgyz Republic:
Profession: «Разработчик web и мультимедийных приложений» (2513 Разработчик web-сайта, 3121 Web дизайнер).
Group: «ВЕБ-25» (1 курс, 2 года обучения, 1440 академических часов в год, 36 часов в неделю).
Tech Stack: Python, Flask, SQLAlchemy, Werkzeug
"""

import sys
from datetime import date, time
from werkzeug.security import generate_password_hash

from app import app
from models import (
    db, Lyceum, Subscription, LyceumSettings, AcademicHoliday,
    User, Teacher, Room, StudentGroup, SubjectCurriculum
)
from schedule_service import run_lyceum_schedule_generation


def seed_database():
    """
    Cleans database schema and seeds official B2B lyceum data for 'Профессиональный Лицей №14'
    with 1st year group «ВЕБ-25» (1440 hours).
    """
    print("=" * 60)
    print("[SEED] Starting Database Seeding Process (Official Ministry Curriculum)...")
    print("=" * 60)

    try:
        # 1. Clean slate - Drop and recreate all tables
        print("[1/7] Recreating database tables (clean slate)...")
        db.drop_all()
        db.create_all()

        # 2. Inject Lyceum Tenant
        print("[2/7] Seeding Lyceum tenant...")
        lyceum = Lyceum(
            name="Профессиональный Лицей №14",
            contact_email="info@lyceum14.edu"
        )
        db.session.add(lyceum)
        db.session.flush()

        subscription = Subscription(
            lyceum_id=lyceum.id,
            plan_tier="pro",
            max_groups_limit=15,
            is_active=True
        )
        db.session.add(subscription)

        settings = LyceumSettings(
            lyceum_id=lyceum.id,
            academic_year_start=date(2026, 9, 1),
            academic_year_end=date(2027, 6, 30),
            working_days_mask=[0, 1, 2, 3, 4, 5],  # Пн - Сб (6-дневная учебная неделя, 36 ч/нед)
            pairs_per_day=3,
            single_lessons_per_day=1,
            day_start_time=time(8, 30),
            pair_duration_minutes=90,
            single_lesson_duration_minutes=45,
            regular_break_minutes=10,
            long_break_after_pair=2,
            long_break_minutes=20,
            reserve_days_count=3
        )
        db.session.add(settings)

        # Standard Kyrgyzstan public holidays
        holidays_data = [
            (date(2026, 11, 7), "Дни истории и памяти предков"),
            (date(2026, 11, 8), "Дни истории и памяти предков"),
            (date(2027, 1, 1), "Новый год"),
            (date(2027, 2, 23), "День защитника Отечества"),
            (date(2027, 3, 8), "Международный женский день"),
            (date(2027, 3, 21), "Народный праздник Нооруз"),
            (date(2027, 5, 1), "Праздник труда"),
            (date(2027, 5, 5), "День Конституции Кыргызской Республики"),
            (date(2027, 5, 9), "День Победы")
        ]
        for h_date, h_title in holidays_data:
            db.session.add(AcademicHoliday(lyceum_id=lyceum.id, date=h_date, title=h_title))

        print(f"      -> Created Lyceum: '{lyceum.name}' (ID: {lyceum.id})")

        # 3. Inject Admin User
        print("[3/7] Seeding Lyceum Admin user...")
        admin_email = "admin@lyceum14.edu"
        admin_password = "password123"
        hashed_password = generate_password_hash(admin_password)

        admin_user = User(
            lyceum_id=lyceum.id,
            role="LYCEUM_ADMIN",
            email=admin_email,
            password_hash=hashed_password
        )
        db.session.add(admin_user)
        print(f"      -> Created Admin: '{admin_email}' (Password: '{admin_password}')")

        # 4. Inject Classrooms & Labs
        print("[4/7] Seeding Classrooms & Specialized Labs...")
        r_201 = Room(lyceum_id=lyceum.id, room_number="Каб. 201", room_type="lecture", capacity=30)
        r_202 = Room(lyceum_id=lyceum.id, room_number="Каб. 202", room_type="lecture", capacity=30)
        r_203 = Room(lyceum_id=lyceum.id, room_number="Каб. 203", room_type="lecture", capacity=30)
        r_lab1 = Room(lyceum_id=lyceum.id, room_number="Компьютерная лаборатория №1", room_type="computer_lab", capacity=25)
        r_it = Room(lyceum_id=lyceum.id, room_number="IT-мастерская (веб-разработка)", room_type="computer_lab", capacity=25)
        r_gym = Room(lyceum_id=lyceum.id, room_number="Спортзал", room_type="gym", capacity=40)
        db.session.add_all([r_201, r_202, r_203, r_lab1, r_it, r_gym])
        db.session.flush()

        # 5. Inject Pedagogical Staff (Teachers)
        print("[5/7] Seeding Pedagogical Staff (Realistic Lyceum Teachers)...")
        t_kyrgyz = Teacher(lyceum_id=lyceum.id, full_name="Асанова Айгуль Бакытовна", max_weekly_hours=36)
        t_russian = Teacher(lyceum_id=lyceum.id, full_name="Смирнова Елена Васильевна", max_weekly_hours=36)
        t_math = Teacher(lyceum_id=lyceum.id, full_name="Исаков Данияр Алымкулович", max_weekly_hours=36)
        t_history = Teacher(lyceum_id=lyceum.id, full_name="Жумабеков Канат Темирович", max_weekly_hours=36)
        t_science = Teacher(lyceum_id=lyceum.id, full_name="Токтосунова Жылдыз Муратовна", max_weekly_hours=36)
        t_it = Teacher(lyceum_id=lyceum.id, full_name="Калиев Самат Бектурович", max_weekly_hours=36)
        t_master = Teacher(lyceum_id=lyceum.id, full_name="Бакиров Руслан Эркинович", max_weekly_hours=36)
        t_english = Teacher(lyceum_id=lyceum.id, full_name="Айтматова Назгуль Чынгызовна", max_weekly_hours=36)
        t_pe_dpt = Teacher(lyceum_id=lyceum.id, full_name="Мамбетов Кубат Садыкович", max_weekly_hours=36)
        db.session.add_all([t_kyrgyz, t_russian, t_math, t_history, t_science, t_it, t_master, t_english, t_pe_dpt])
        db.session.flush()

        # 6. Inject Student Group «ВЕБ-25» & Official Curriculum (1440 Academic Hours)
        print("[6/7] Seeding Group «ВЕБ-25» & Official Ministry Curriculum (1440 hours)...")
        group_web = StudentGroup(
            lyceum_id=lyceum.id,
            name="ВЕБ-25",
            course_year=1,
            student_count=25,
            years_of_study=2
        )
        db.session.add(group_web)
        db.session.flush()

        # Breakdown of subjects strictly from the Ministry Curriculum Plan:
        # I. Общеобразовательный компонент (952 ч) + II. Профессиональный компонент (488 ч) = 1440 ч
        curriculum_disciplines = [
            # I. Общеобразовательный компонент (952 часа)
            ("Кыргызский язык", 102, t_kyrgyz.id, r_201.id, True, "general"),
            ("Кыргызская литература", 34, t_kyrgyz.id, r_201.id, True, "general"),
            ("Русский язык", 68, t_russian.id, r_202.id, True, "general"),
            ("Русская литература", 102, t_russian.id, r_202.id, True, "general"),
            ("Иностранный язык (Английский)", 68, t_english.id, r_201.id, True, "general"),
            ("История", 68, t_history.id, r_203.id, True, "general"),
            ("Человек и общество", 34, t_history.id, r_203.id, True, "general"),
            ("Алгебра", 102, t_math.id, r_201.id, True, "general"),
            ("Геометрия", 34, t_math.id, r_201.id, True, "general"),
            ("Биология", 34, t_science.id, r_202.id, True, "general"),
            ("География", 34, t_science.id, r_202.id, True, "general"),
            ("Физика / Астрономия", 102, t_science.id, r_202.id, True, "general"),
            ("Химия", 68, t_science.id, r_202.id, True, "general"),
            ("Допризывная подготовка", 68, t_pe_dpt.id, r_203.id, True, "general"),
            ("Физическое воспитание", 34, t_pe_dpt.id, r_gym.id, True, "general"),

            # II. Профессиональный компонент (488 часов)
            ("Охрана труда и производственная экология", 24, t_master.id, r_it.id, False, "vocational"),
            ("Правовые основы профессиональной деятельности", 24, t_history.id, r_203.id, False, "vocational"),
            ("Безопасный здоровый образ жизни", 24, t_pe_dpt.id, r_203.id, False, "vocational"),
            ("Основы компьютерных вычислений", 42, t_math.id, r_lab1.id, False, "vocational"),
            ("Библиотека языков программирования", 30, t_it.id, r_lab1.id, False, "vocational"),
            ("Основы программирования", 60, t_it.id, r_lab1.id, False, "vocational"),
            ("Технология программирования", 40, t_it.id, r_lab1.id, False, "vocational"),
            ("Производственное обучение (Практикум в лаборатории)", 244, t_master.id, r_it.id, False, "vocational"),
        ]

        total_curriculum_hours = 0
        for s_name, hours, t_id, r_id, is_gen, s_type in curriculum_disciplines:
            total_curriculum_hours += hours
            db.session.add(SubjectCurriculum(
                group_id=group_web.id,
                subject_name=s_name,
                total_hours=hours,
                allocated_hours=0,
                remaining_hours=hours,
                teacher_id=t_id,
                preferred_room_id=r_id,
                is_general_education=is_gen,
                subject_type=s_type
            ))

        db.session.commit()
        print(f"      -> Group «ВЕБ-25» created with {len(curriculum_disciplines)} subjects. Total planned: {total_curriculum_hours} hours.")

        # 7. Generate Schedule using Academic Calendar + Distributor Engine
        print("[7/7] Generating full schedule via schedule_service engine...")
        gen_res = run_lyceum_schedule_generation(lyceum.id)
        if gen_res["success"]:
            print(f"      -> SUCCESS: {gen_res['message']}")
            print(f"      -> Planned: {gen_res['total_planned_hours']}h | Allocated: {gen_res['total_allocated_hours']}h | Coverage: {gen_res['completion_percent']}% | Total Lessons: {gen_res['total_assignments']}")
        else:
            print(f"      -> WARNING: Generation returned: {gen_res.get('error')}")

        print("=" * 60)
        print(" SUCCESS: Database successfully seeded with Lyceum, Admin, Teachers, Rooms, Group «ВЕБ-25» and 1440-Hour Schedule!")
        print("=" * 60)

    except Exception as e:
        db.session.rollback()
        print("!" * 60)
        print(f" ERROR: Database seeding failed: {e}")
        print("!" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    with app.app_context():
        seed_database()
