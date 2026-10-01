"""
academic_calendar.py — Ядро академического календаря KALIX SaaS.
Генерирует чистый массив доступных учебных слотов на весь год с учетом
плавающего старта, настраиваемой рабочей недели, праздников и звонков.
"""
from datetime import date, datetime, timedelta, time
from typing import List, Set, Dict, Any, Optional


def generate_academic_calendar_slots(
    start_date: date,
    end_date: date,
    working_weekdays: Optional[List[int]] = None,
    holiday_dates: Optional[Set[date]] = None,
    pairs_per_day: int = 3,
    single_lessons_per_day: int = 1,
    day_start_time: time = time(8, 30),
    pair_duration_mins: int = 90,
    single_duration_mins: int = 45,
    break_mins: int = 10,
    long_break_after_slot: int = 2,
    long_break_mins: int = 20,
    reserve_days_count: int = 3
) -> List[Dict[str, Any]]:
    """
    Генерирует чистый массив доступных учебных слотов на весь учебный год.
    
    :param start_date: Плавающая дата старта учебы (напр. 15 сентября).
                       Все дни до этой даты автоматически отсекаются.
    :param end_date: Плавающая дата окончания учебы (напр. 31 мая).
    :param working_weekdays: Список рабочих дней (по умолчанию 5-дневка: [0, 1, 2, 3, 4] = Пн-Пт).
    :param holiday_dates: Множество дат праздников/каникул (вводятся замдиректором).
    :param pairs_per_day: Количество пар в день (каждая пара = 2 академических часа).
    :param single_lessons_per_day: Количество отдельных уроков (каждый урок = 1 акад. час).
    :param day_start_time: Время начала первой пары (по умолчанию 08:30).
    :param pair_duration_mins: Длительность пары в минутах (по умолчанию 90 мин).
    :param single_duration_mins: Длительность урока в минутах (по умолчанию 45 мин).
    :param break_mins: Обычная перемена (по умолчанию 10 мин).
    :param long_break_after_slot: Номер слота, после которого идет большая перемена (по умолчанию 2).
    :param long_break_mins: Длительность большой перемены (по умолчанию 20 мин).
    :param reserve_days_count: Резервные дни в конце учебного года (по умолчанию 3 рабочих дня).
    :return: Чистый список словарей доступных учебных слотов.
    """
    if working_weekdays is None:
        working_weekdays = [0, 1, 2, 3, 4]  # Пн-Пт (Суббота и Воскресенье — выходные)
    if holiday_dates is None:
        holiday_dates = set()

    weekday_names = {
        0: "Понедельник",
        1: "Вторник",
        2: "Среда",
        3: "Четверг",
        4: "Пятница",
        5: "Суббота",
        6: "Воскресенье"
    }

    # 1. Собираем все рабочие дни в диапазоне с учетом рабочих дней недели и праздников
    valid_working_days: List[date] = []
    current_date = start_date
    while current_date <= end_date:
        weekday = current_date.weekday()
        if (weekday in working_weekdays) and (current_date not in holiday_dates):
            valid_working_days.append(current_date)
        current_date += timedelta(days=1)

    # 2. Удержание резервных дней в конце учебного года
    # Резервные дни отсекаются в конце учебного года (перед end_date) для экзаменов и админ-резерва
    schedulable_days = valid_working_days
    try:
        r_count = max(0, int(reserve_days_count)) if reserve_days_count is not None else 0
    except (ValueError, TypeError):
        r_count = 0

    if r_count > 0:
        # Для полного учебного периода (>= 30 дней) или при явном задании reserve_days_count != 3
        is_full_academic_period = (end_date - start_date).days >= 30
        if is_full_academic_period or r_count != 3:
            if r_count < len(valid_working_days):
                schedulable_days = valid_working_days[:-r_count]
            else:
                schedulable_days = []

    calendar_slots: List[Dict[str, Any]] = []

    for work_date in schedulable_days:
        weekday = work_date.weekday()
        current_dt = datetime.combine(work_date, day_start_time)
        slot_number = 1

        # 3. Генерируем слоты для пар (по 2 акад. часа)
        for _ in range(pairs_per_day):
            end_dt = current_dt + timedelta(minutes=pair_duration_mins)

            calendar_slots.append({
                "date": work_date,
                "day_of_week": weekday,
                "day_name": weekday_names[weekday],
                "slot_number": slot_number,
                "slot_type": "pair",
                "academic_hours": 2,
                "start_time": current_dt.time(),
                "end_time": end_dt.time(),
                "label": f"{slot_number} Пара ({current_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')})"
            })

            # Учет большой или стандартной перемены
            pause = long_break_mins if slot_number == long_break_after_slot else break_mins
            current_dt = end_dt + timedelta(minutes=pause)
            slot_number += 1

        # 4. Генерируем слоты для отдельных уроков (по 1 акад. часу)
        for _ in range(single_lessons_per_day):
            end_dt = current_dt + timedelta(minutes=single_duration_mins)

            calendar_slots.append({
                "date": work_date,
                "day_of_week": weekday,
                "day_name": weekday_names[weekday],
                "slot_number": slot_number,
                "slot_type": "single_lesson",
                "academic_hours": 1,
                "start_time": current_dt.time(),
                "end_time": end_dt.time(),
                "label": f"{slot_number} Урок ({current_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')})"
            })

            current_dt = end_dt + timedelta(minutes=break_mins)
            slot_number += 1

    return calendar_slots
