"""
test_core_calendar.py — Автоматические тесты ядра календаря и схемы БД.
"""
from datetime import date, time
from academic_calendar import generate_academic_calendar_slots
from core_schema import Base, Lyceum, LyceumSettings, AcademicHoliday, StudentGroup, SubjectCurriculum
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_calendar_floating_start_and_holidays():
    """Тест: плавающий старт, исключение выходных и праздников."""
    start_d = date(2026, 9, 15)
    end_d = date(2026, 9, 30)
    holidays = {date(2026, 9, 21)}

    slots = generate_academic_calendar_slots(
        start_date=start_d,
        end_date=end_d,
        working_weekdays=[0, 1, 2, 3, 4],
        holiday_dates=holidays,
        pairs_per_day=3,
        single_lessons_per_day=1
    )

    all_dates = sorted(list(set(s['date'] for s in slots)))

    # 1. Ни одной даты до 15 сентября быть не должно
    assert min(all_dates) == start_d, f"Дата старта должна быть {start_d}, но получили {min(all_dates)}"

    # 2. Праздник 21 сентября не должен войти
    assert date(2026, 9, 21) not in all_dates, "Праздничный день 2026-09-21 не должен быть в расписании"

    # 3. Суббот (5) и Воскресений (6) быть не должно
    for d in all_dates:
        assert d.weekday() not in [5, 6], f"Обнаружен выходной день недели: {d} ({d.weekday()})"

    # 4. Каждый день должен содержать ровно 4 слота (3 пары + 1 урок)
    slots_per_day = {}
    for s in slots:
        slots_per_day[s['date']] = slots_per_day.get(s['date'], 0) + 1
    for d, count in slots_per_day.items():
        assert count == 4, f"В день {d} должно быть 4 слота, получено {count}"

    print(f"[OK] test_calendar_floating_start_and_holidays PASSED! (Days: {len(all_dates)}, slots: {len(slots)})")


def test_custom_settings_adaptation():
    """Тест: изменение настроек директором (6-дневка, 4 пары, 0 уроков)."""
    start_d = date(2026, 10, 1)
    end_d = date(2026, 10, 7)

    # Директор задал 6-дневную неделю и 4 пары в день без одиночных уроков
    slots = generate_academic_calendar_slots(
        start_date=start_d,
        end_date=end_d,
        working_weekdays=[0, 1, 2, 3, 4, 5],
        holiday_dates=set(),
        pairs_per_day=4,
        single_lessons_per_day=0
    )

    all_dates = set(s['date'] for s in slots)
    assert len(all_dates) == 6, f"Ожидалось 6 рабочих дней, получено {len(all_dates)}"
    assert len(slots) == 24, f"Ожидалось 24 слота (6 дней * 4 пары), получено {len(slots)}"
    for s in slots:
        assert s['slot_type'] == 'pair'
        assert s['academic_hours'] == 2

    print("[OK] test_custom_settings_adaptation PASSED! (Adaptation to 6 days and 4 pairs works)")


def test_database_schema_instantiation():
    """Тест: создание схемы БД в памяти SQLite и проверка связей."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    lyceum = Lyceum(name="Бишкекский технический лицей №14")
    session.add(lyceum)
    session.flush()

    settings = LyceumSettings(lyceum_id=lyceum.id, pairs_per_day=3, single_lessons_per_day=1)
    group = StudentGroup(lyceum_id=lyceum.id, name="ИТ-21")
    session.add_all([settings, group])
    session.flush()

    math_subj = SubjectCurriculum(
        group_id=group.id,
        subject_name="Математика",
        total_hours=120,
        allocated_hours=0,
        remaining_hours=120
    )
    session.add(math_subj)
    session.commit()

    assert math_subj.remaining_hours == 120
    assert group.curriculum[0].subject_name == "Математика"
    print("[OK] test_database_schema_instantiation PASSED! (DB Schema, FKs and relations are valid)")


if __name__ == "__main__":
    test_calendar_floating_start_and_holidays()
    test_custom_settings_adaptation()
    test_database_schema_instantiation()
    print("\n=======================================================")
    print("ALL TESTS FOR DATABASE AND CALENDAR ENGINE PASSED 100%!")
    print("=======================================================")
