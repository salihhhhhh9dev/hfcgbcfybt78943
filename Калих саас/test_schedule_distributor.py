"""
test_schedule_distributor.py — Тестирование алгоритма распределения часов
и правила разрешения конфликтов по remaining_hours.
"""
from datetime import date, time
from academic_calendar import generate_academic_calendar_slots
from schedule_distributor import ScheduleDistributor


def test_conflict_resolution_by_remaining_hours():
    """
    КРИТИЧЕСКИЙ ТЕСТ:
    Две группы (ИТ-21 и ИТ-22) делят одного и того же преподавателя (Учитель #1, Математика).
    - У ИТ-21 осталось 120 часов.
    - У ИТ-22 осталось 40 часов.
    ПРАВИЛО: Алгоритм обязан отдать приоритет ИТ-21 (у нее больше нераспределенных часов).
    ИТ-22 должна получить альтернативный предмет (Информатика, Учитель #2).
    """
    # 1. Генерируем тестовый календарь на 5 рабочих дней
    slots = generate_academic_calendar_slots(
        start_date=date(2026, 9, 15),
        end_date=date(2026, 9, 21),
        working_weekdays=[0, 1, 2, 3, 4], # 5 рабочих дней
        holiday_dates=set(),
        pairs_per_day=3,
        single_lessons_per_day=1
    )

    groups = [
        {'id': 1, 'name': 'ИТ-21'},
        {'id': 2, 'name': 'ИТ-22'}
    ]

    curricula = [
        # ИТ-21: 120 часов Математики с Учителем #1
        {'id': 101, 'group_id': 1, 'subject_name': 'Математика', 'teacher_id': 1, 'preferred_room_id': 10, 'total_hours': 120, 'remaining_hours': 120},
        {'id': 102, 'group_id': 1, 'subject_name': 'Физика', 'teacher_id': 3, 'preferred_room_id': 12, 'total_hours': 60, 'remaining_hours': 60},

        # ИТ-22: 40 часов Математики с тем же Учителем #1
        {'id': 201, 'group_id': 2, 'subject_name': 'Математика', 'teacher_id': 1, 'preferred_room_id': 10, 'total_hours': 40, 'remaining_hours': 40},
        {'id': 202, 'group_id': 2, 'subject_name': 'Информатика', 'teacher_id': 2, 'preferred_room_id': 11, 'total_hours': 80, 'remaining_hours': 80},
    ]

    distributor = ScheduleDistributor(slots, groups, curricula)
    results = distributor.run_distribution()

    assert results['success'] is True
    assignments = results['assignments']
    assert len(assignments) > 0

    # Проверяем самый первый слот (2026-09-15, Слот 1)
    slot1_assignments = [a for a in assignments if a['date'] == date(2026, 9, 15) and a['slot_number'] == 1]
    assert len(slot1_assignments) == 2, f"Ожидалось 2 назначения на слот 1, получено {len(slot1_assignments)}"

    it21_slot1 = next(a for a in slot1_assignments if a['group_id'] == 1)
    it22_slot1 = next(a for a in slot1_assignments if a['group_id'] == 2)

    # ИТ-21 должна получить Учителя #1 (Математика) благодаря remaining_hours=120 > 40!
    assert it21_slot1['teacher_id'] == 1, "ИТ-21 должна получить учителя #1 (приоритет по remaining_hours)"
    assert it21_slot1['subject_name'] == 'Математика'

    # ИТ-22 не должна получить Учителя #1 (конфликт исключен), а должна получить альтернативу (Информатика, Учитель #2)
    assert it22_slot1['teacher_id'] != 1, "Учитель #1 не должен быть назначен в две группы одновременно!"
    assert it22_slot1['subject_name'] == 'Информатика'
    assert it22_slot1['teacher_id'] == 2

    # Проверяем полное отсутствие накладок учителей по всей сетке
    teacher_time_map = {}
    for a in assignments:
        key = (a['date'], a['slot_number'], a['teacher_id'])
        if a['teacher_id'] is not None:
            assert key not in teacher_time_map, f"ОБНАРУЖЕНА НАКЛАДКА УЧИТЕЛЯ: {key}"
            teacher_time_map[key] = a

    print("[OK] test_conflict_resolution_by_remaining_hours PASSED! (Приоритет по remaining_hours работает безупречно)")


def test_full_year_even_distribution():
    """
    Тест равномерного распределения пула часов (120ч) на полный учебный год
    (15 сентября 2026 - 31 мая 2027) без превышения лимитов.
    """
    slots = generate_academic_calendar_slots(
        start_date=date(2026, 9, 15),
        end_date=date(2027, 5, 31),
        working_weekdays=[0, 1, 2, 3, 4], # Пн-Пт
        holiday_dates={date(2026, 11, 7), date(2027, 1, 1), date(2027, 3, 8), date(2027, 3, 21), date(2027, 5, 9)},
        pairs_per_day=3,
        single_lessons_per_day=1
    )

    groups = [{'id': 1, 'name': 'ИТ-21'}]
    curricula = [
        {'id': 1, 'group_id': 1, 'subject_name': 'Математика', 'teacher_id': 1, 'preferred_room_id': 101, 'total_hours': 120, 'remaining_hours': 120},
        {'id': 2, 'group_id': 1, 'subject_name': 'Физика', 'teacher_id': 2, 'preferred_room_id': 102, 'total_hours': 80, 'remaining_hours': 80},
        {'id': 3, 'group_id': 1, 'subject_name': 'Программирование', 'teacher_id': 3, 'preferred_room_id': 103, 'total_hours': 200, 'remaining_hours': 200},
        {'id': 4, 'group_id': 1, 'subject_name': 'Английский язык', 'teacher_id': 4, 'preferred_room_id': 104, 'total_hours': 70, 'remaining_hours': 70},
    ]

    distributor = ScheduleDistributor(slots, groups, curricula)
    results = distributor.run_distribution()

    assert results['success'] is True
    assert results['completion_percent'] == 100.0, f"Все 470 часов должны быть распределены, факт: {results['completion_percent']}%"
    assert results['total_unallocated_hours'] == 0

    print(f"[OK] test_full_year_even_distribution PASSED! (100% часов распределено: {results['total_allocated_hours']} из {results['total_planned_hours']}ч)")


def test_5_day_week_mixed_slots_100_percent():
    """
    ЭДЖ-КЕЙС 1:
    Проверка распределения 1440 часов при переключении на 5-дневную неделю (Пн-Пт)
    с 3 парами (6ч) + 1 одиночным уроком (1ч) = 7ч в день.
    """
    slots = generate_academic_calendar_slots(
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        working_weekdays=[0, 1, 2, 3, 4], # Пн - Пт
        holiday_dates={date(2026, 11, 7), date(2027, 1, 1), date(2027, 3, 8), date(2027, 3, 21), date(2027, 5, 9)},
        pairs_per_day=3,
        single_lessons_per_day=1
    )

    groups = [{'id': 1, 'name': 'ВЕБ-25'}]
    # 23 предмета официального плана суммой 1440 часов
    curricula = [
        {'id': 1, 'group_id': 1, 'subject_name': 'Кыргызский язык', 'teacher_id': 1, 'preferred_room_id': 101, 'total_hours': 102},
        {'id': 2, 'group_id': 1, 'subject_name': 'Кыргызская литература', 'teacher_id': 1, 'preferred_room_id': 101, 'total_hours': 34},
        {'id': 3, 'group_id': 1, 'subject_name': 'Русский язык', 'teacher_id': 2, 'preferred_room_id': 102, 'total_hours': 68},
        {'id': 4, 'group_id': 1, 'subject_name': 'Русская литература', 'teacher_id': 2, 'preferred_room_id': 102, 'total_hours': 102},
        {'id': 5, 'group_id': 1, 'subject_name': 'Иностранный язык', 'teacher_id': 3, 'preferred_room_id': 101, 'total_hours': 68},
        {'id': 6, 'group_id': 1, 'subject_name': 'История', 'teacher_id': 4, 'preferred_room_id': 103, 'total_hours': 68},
        {'id': 7, 'group_id': 1, 'subject_name': 'Человек и общество', 'teacher_id': 4, 'preferred_room_id': 103, 'total_hours': 34},
        {'id': 8, 'group_id': 1, 'subject_name': 'Алгебра', 'teacher_id': 5, 'preferred_room_id': 101, 'total_hours': 102},
        {'id': 9, 'group_id': 1, 'subject_name': 'Геометрия', 'teacher_id': 5, 'preferred_room_id': 101, 'total_hours': 34},
        {'id': 10, 'group_id': 1, 'subject_name': 'Биология', 'teacher_id': 6, 'preferred_room_id': 102, 'total_hours': 34},
        {'id': 11, 'group_id': 1, 'subject_name': 'География', 'teacher_id': 6, 'preferred_room_id': 102, 'total_hours': 34},
        {'id': 12, 'group_id': 1, 'subject_name': 'Физика', 'teacher_id': 6, 'preferred_room_id': 102, 'total_hours': 102},
        {'id': 13, 'group_id': 1, 'subject_name': 'Химия', 'teacher_id': 6, 'preferred_room_id': 102, 'total_hours': 68},
        {'id': 14, 'group_id': 1, 'subject_name': 'ДПМ', 'teacher_id': 7, 'preferred_room_id': 103, 'total_hours': 68},
        {'id': 15, 'group_id': 1, 'subject_name': 'Физкультура', 'teacher_id': 7, 'preferred_room_id': 106, 'total_hours': 34},
        {'id': 16, 'group_id': 1, 'subject_name': 'Охрана труда', 'teacher_id': 8, 'preferred_room_id': 105, 'total_hours': 24},
        {'id': 17, 'group_id': 1, 'subject_name': 'Право', 'teacher_id': 4, 'preferred_room_id': 103, 'total_hours': 24},
        {'id': 18, 'group_id': 1, 'subject_name': 'БЗОЖ', 'teacher_id': 7, 'preferred_room_id': 103, 'total_hours': 24},
        {'id': 19, 'group_id': 1, 'subject_name': 'Компьютерные вычисления', 'teacher_id': 5, 'preferred_room_id': 104, 'total_hours': 42},
        {'id': 20, 'group_id': 1, 'subject_name': 'Библиотека ЯП', 'teacher_id': 9, 'preferred_room_id': 104, 'total_hours': 30},
        {'id': 21, 'group_id': 1, 'subject_name': 'Основы программирования', 'teacher_id': 9, 'preferred_room_id': 104, 'total_hours': 60},
        {'id': 22, 'group_id': 1, 'subject_name': 'Технология программирования', 'teacher_id': 9, 'preferred_room_id': 104, 'total_hours': 40},
        {'id': 23, 'group_id': 1, 'subject_name': 'Производственное обучение', 'teacher_id': 8, 'preferred_room_id': 105, 'total_hours': 244},
    ]

    distributor = ScheduleDistributor(slots, groups, curricula, max_daily_subject_hours=4)
    results = distributor.run_distribution()

    assert results['success'] is True
    assert results['completion_percent'] == 100.0, f"5-дневка должна покрыть 100%, факт: {results['completion_percent']}%"
    assert results['total_allocated_hours'] == 1440
    assert results['total_unallocated_hours'] == 0
    print("[OK] test_5_day_week_mixed_slots_100_percent PASSED! (1440h allocated on 5-day week)")


def test_multi_group_contention_resolution():
    """
    ЭДЖ-КЕЙС 2:
    Две параллельные группы («ВЕБ-25» и «РВМ-25») с нагрузкой по 1440 часов каждая
    (суммарно 2880 часов) делят один и тот же преподавательский состав и кабинеты.
    Проверяется бесконфликтность и разрешение коллизий через remaining_hours.
    """
    slots = generate_academic_calendar_slots(
        start_date=date(2026, 9, 1),
        end_date=date(2027, 6, 30),
        working_weekdays=[0, 1, 2, 3, 4, 5],
        holiday_dates={date(2026, 11, 7), date(2027, 1, 1), date(2027, 3, 8), date(2027, 3, 21), date(2027, 5, 9)},
        pairs_per_day=3,
        single_lessons_per_day=1
    )

    groups = [
        {'id': 1, 'name': 'ВЕБ-25'},
        {'id': 2, 'name': 'РВМ-25'}
    ]

    base_plan = [
        ('Кыргызский язык', 102, 1, 101),
        ('Кыргызская литература', 34, 1, 101),
        ('Русский язык', 68, 2, 102),
        ('Русская литература', 102, 2, 102),
        ('Иностранный язык', 68, 3, 101),
        ('История', 68, 4, 103),
        ('Человек и общество', 34, 4, 103),
        ('Алгебра', 102, 5, 101),
        ('Геометрия', 34, 5, 101),
        ('Биология', 34, 6, 102),
        ('География', 34, 6, 102),
        ('Физика', 102, 6, 102),
        ('Химия', 68, 6, 102),
        ('ДПМ', 68, 7, 103),
        ('Физкультура', 34, 7, 106),
        ('Охрана труда', 24, 8, 105),
        ('Право', 24, 4, 103),
        ('БЗОЖ', 24, 7, 103),
        ('Компьютерные вычисления', 42, 5, 104),
        ('Библиотека ЯП', 30, 9, 104),
        ('Основы программирования', 60, 9, 104),
        ('Технология программирования', 40, 9, 104),
        ('Производственное обучение', 244, 8, 105),
    ]

    curricula = []
    idx = 1
    for s_name, hrs, t_id, r_id in base_plan:
        curricula.append({'id': idx, 'group_id': 1, 'subject_name': s_name, 'teacher_id': t_id, 'preferred_room_id': r_id, 'total_hours': hrs})
        idx += 1
    for s_name, hrs, t_id, r_id in base_plan:
        curricula.append({'id': idx, 'group_id': 2, 'subject_name': s_name, 'teacher_id': t_id, 'preferred_room_id': r_id, 'total_hours': hrs})
        idx += 1

    distributor = ScheduleDistributor(slots, groups, curricula, max_daily_subject_hours=3)
    results = distributor.run_distribution()

    assert results['success'] is True
    assert results['total_allocated_hours'] == 2880, f"Все 2880 часов должны быть распределены, факт: {results['total_allocated_hours']}"
    assert results['completion_percent'] == 100.0
    assert results['conflicts_resolved_count'] > 0

    # Проверка отсутствия накладок учителей и кабинетов
    teacher_slots = set()
    room_slots = set()
    from collections import defaultdict
    day_group_pairs = defaultdict(list)
    day_group_subject_hours = defaultdict(lambda: defaultdict(int))

    for a in results['assignments']:
        t_key = (a['date'], a['slot_number'], a['teacher_id'])
        if a['teacher_id']:
            assert t_key not in teacher_slots, f"Коллизия преподавателя: {t_key}"
            teacher_slots.add(t_key)

        r_key = (a['date'], a['slot_number'], a['room_id'])
        if a['room_id']:
            assert r_key not in room_slots, f"Коллизия аудитории: {r_key}"
            room_slots.add(r_key)

        hrs = 2 if a['slot_type'] == 'pair' else 1
        day_group_subject_hours[(a['date'], a['group_id'])][a['subject_id']] += hrs
        if a['slot_type'] == 'pair':
            day_group_pairs[(a['date'], a['group_id'])].append(a['subject_id'])

    # Проверка анти-сдваивания и лимита 3ч для обеих групп
    for (d, gid), pair_list in day_group_pairs.items():
        assert len(pair_list) == len(set(pair_list)), f"Обнаружено сдваивание пар на {d} для группы {gid}: {pair_list}"

    for (d, gid), subj_map in day_group_subject_hours.items():
        for s_id, h in subj_map.items():
            assert h <= 3, f"Предмет {s_id} превысил 3ч на {d} для группы {gid}: {h}ч"

    print(f"[OK] test_multi_group_contention_resolution PASSED! (2880h allocated across 2 groups, {results['conflicts_resolved_count']} conflicts cleanly resolved, 0 duplicate pairs)")


if __name__ == "__main__":
    test_conflict_resolution_by_remaining_hours()
    test_full_year_even_distribution()
    test_5_day_week_mixed_slots_100_percent()
    test_multi_group_contention_resolution()
    print("\n==================================================================")
    print("ALL TESTS FOR CONFLICT RESOLUTION & DISTRIBUTION PASSED 100%!")
    print("==================================================================")
