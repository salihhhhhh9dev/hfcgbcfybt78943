"""
KALIX SaaS - Core Pedagogical Schedule Generator Engine
Technical Stack: Python 3, SQLAlchemy, Heuristic Constraint Satisfaction Problem (CSP) Solver

СТРОГАЯ СЕТКА И ОГРАНИЧЕНИЯ НАГРУЗКИ (HARD CONSTRAINTS):
1. Пн - Пт (Дни 1-5): Максимум 7 академ. часов в день
   - Слот 1, 2, 3: Пары по 2 часа (90 мин)
   - Слот 4: Одиночный урок 1 час (45 мин)
2. Суббота (День 6): Максимум 4 академ. часа в день
   - Слот 1, 2: Пары по 2 часа (90 мин)
   - Слоты 3 и 4 ЗАПРЕЩЕНЫ в субботу.
3. Абсолютный недельный лимит (Weekly Hard Cap): 39 часов в неделю на группу (5 * 7ч + 1 * 4ч = 39ч).
   - Если недельный учебный план группы превышает 39 часов, алгоритм СТРОГО отсекает генерацию на 39 часах
     и выдает системное предупреждение (System Overflow Warning).
"""

import math
from typing import List, Dict, Any, Tuple
from datetime import datetime, date, time, timedelta, timezone
from models import db, ScheduleSlot, Lyceum, Group, Teacher, Room, Subject, DayOfWeek, Holiday

# -------------------------------------------------------------------------
# СТРОГАЯ СЕТКА И ЕМКОСТЬ УЧЕБНОЙ НЕДЕЛИ ЛИЦЕЯ
# -------------------------------------------------------------------------
MAX_WEEKLY_HOURS_PER_GROUP = 39  # 5 дней * 7ч + 1 день * 4ч = 39 академических часов

SLOTS_MON_FRI = [
    {"slot_num": 1, "hours": 2, "start": time(8, 0), "end": time(9, 30)},
    {"slot_num": 2, "hours": 2, "start": time(9, 40), "end": time(11, 10)},
    {"slot_num": 3, "hours": 2, "start": time(11, 30), "end": time(13, 0)},
    {"slot_num": 4, "hours": 1, "start": time(13, 10), "end": time(13, 55)},
]

# В субботу разрешены ТОЛЬКО первые 2 пары (4 часа)
SLOTS_SATURDAY = [
    {"slot_num": 1, "hours": 2, "start": time(8, 0), "end": time(9, 30)},
    {"slot_num": 2, "hours": 2, "start": time(9, 40), "end": time(11, 10)},
]

WEEK_TEMPLATE = {
    DayOfWeek.MONDAY: SLOTS_MON_FRI,
    DayOfWeek.TUESDAY: SLOTS_MON_FRI,
    DayOfWeek.WEDNESDAY: SLOTS_MON_FRI,
    DayOfWeek.THURSDAY: SLOTS_MON_FRI,
    DayOfWeek.FRIDAY: SLOTS_MON_FRI,
    DayOfWeek.SATURDAY: SLOTS_SATURDAY,
}

SLOT_CONFIGS = SLOTS_MON_FRI
DAYS = list(WEEK_TEMPLATE.keys())


def is_academic_working_day(target_date: date, works_on_saturdays: bool, holiday_dates: set) -> Tuple[bool, str]:
    """
    Проверяет, является ли дата рабочим учебным днем лицея.
    - Воскресенье (weekday == 6): ВСЕГДА ВЫХОДНОЙ
    - Суббота (weekday == 5) при works_on_saturdays == False: ВЫХОДНОЙ
    - Дата в списке Holiday лицея: ПРАЗДНИК / ИСКЛЮЧЕНИЕ
    """
    if target_date.weekday() == 6:
        return False, "Воскресенье (Автоматический выходной)"

    if target_date.weekday() == 5 and not works_on_saturdays:
        return False, "Суббота (Выходной по настройкам лицея)"

    if target_date in holiday_dates:
        return False, "Праздничный или нерабочий день лицея"

    return True, "Учебный день"


def simulate_academic_year_calendar(lyceum_id: int, start_date: date = None) -> List[Dict[str, Any]]:
    """
    Итерирует по календарным датам datetime.date с 1 сентября.
    Применяет проверки недели и праздников.
    Пропущенные дни НЕ уменьшают остаток часов предметов.
    """
    if start_date is None:
        start_date = date(2026, 9, 1)

    lyceum = db.session.get(Lyceum, lyceum_id)
    if not lyceum:
        return []

    holidays = db.session.query(Holiday).filter(Holiday.lyceum_id == lyceum_id).all()
    holiday_dates = {h.date for h in holidays}
    works_on_saturdays = getattr(lyceum, "works_on_saturdays", True)

    calendar_days = []
    curr = start_date
    end_date = start_date + timedelta(days=305)  # ~10 месяцев учебного года

    while curr <= end_date:
        is_working, reason = is_academic_working_day(curr, works_on_saturdays, holiday_dates)
        calendar_days.append({
            "date": curr,
            "weekday": curr.weekday(),
            "is_working": is_working,
            "reason": reason
        })
        curr += timedelta(days=1)

    return calendar_days


def detect_schedule_conflicts(lyceum_id: int) -> List[Dict[str, Any]]:
    """
    Сканирует все ScheduleSlot для лицея и находит накладки преподавателей.
    Ограничения по аудиториям отменены согласно бизнес-требованиям.
    """
    slots = db.session.query(ScheduleSlot).filter(ScheduleSlot.lyceum_id == lyceum_id).all()
    conflicts = []

    time_map: Dict[Tuple[str, time], List[ScheduleSlot]] = {}
    for s in slots:
        key = (s.day_of_week.value if hasattr(s.day_of_week, 'value') else str(s.day_of_week), s.start_time)
        time_map.setdefault(key, []).append(s)

    for (day_str, s_time), slot_list in time_map.items():
        teacher_map: Dict[int, List[ScheduleSlot]] = {}
        for s in slot_list:
            if s.teacher_id:
                teacher_map.setdefault(s.teacher_id, []).append(s)

        for t_id, t_slots in teacher_map.items():
            if len(t_slots) > 1:
                teacher = db.session.get(Teacher, t_id)
                t_name = teacher.full_name if teacher else f"ID #{t_id}"
                for ts in t_slots:
                    conflicts.append({
                        "slot_id": ts.id,
                        "group_id": ts.group_id,
                        "conflict_type": "teacher_double_booking",
                        "message": f"⚠️ Накладка! Преподаватель {t_name} назначен в 2 группы одновременно ({day_str}, {s_time.strftime('%H:%M')})"
                    })

    return conflicts


def is_in_practice_period(target_date: date, group: Group) -> bool:
    """Проверяет, входит ли дата в период производственной практики группы."""
    if group.practice_start_date and group.practice_end_date:
        return group.practice_start_date <= target_date <= group.practice_end_date
    return False


def generate_auto_schedule(lyceum_id: int, current_date: date = None) -> Tuple[bool, str, int]:
    """
    Генератор расписания с учетом производственной практики и отсутствием ограничений на аудитории.
    Слот расписания состоит исключительно из Группы, Предмета и Преподавателя.
    """
    if current_date is None:
        current_date = date(2026, 9, 1)

    lyceum = db.session.get(Lyceum, lyceum_id)
    if not lyceum:
        return False, "Лицей не найден.", 0

    groups = db.session.query(Group).filter(Group.lyceum_id == lyceum_id).all()
    if not groups:
        return False, "Не найдено учебных групп в лицее.", 0

    teachers = db.session.query(Teacher).filter(Teacher.lyceum_id == lyceum_id).all()
    rooms = db.session.query(Room).filter(Room.lyceum_id == lyceum_id).all()
    default_room_id = rooms[0].id if rooms else None

    # Загрузка исключенных праздничных дат
    holidays = db.session.query(Holiday).filter(Holiday.lyceum_id == lyceum_id).all()
    holiday_dates = {h.date for h in holidays}
    works_on_saturdays = getattr(lyceum, "works_on_saturdays", True)

    # Очистка предыдущих сгенерированных слотов
    db.session.query(ScheduleSlot).filter(ScheduleSlot.lyceum_id == lyceum_id).delete()
    db.session.commit()

    created_count = 0
    overflow_warnings = []

    # Трекеры занятости преподавателей
    teacher_busy = set()

    for g in groups:
        subjects = db.session.query(Subject).filter(Subject.group_id == g.id).all()
        if not subjects:
            continue

        # Проверка режима Производственной Практики (Block Practice Period)
        is_practice_active = is_in_practice_period(current_date, g)
        practice_subject_obj = None

        if is_practice_active or g.practice_subject_id:
            if g.practice_subject_id:
                practice_subject_obj = db.session.get(Subject, g.practice_subject_id)
            if not practice_subject_obj:
                for s in subjects:
                    if any(kw in s.name.lower() for kw in ["производствен", "практик"]):
                        practice_subject_obj = s
                        break
            if not practice_subject_obj:
                practice_subject_obj = subjects[0]

        # Формирование пула дисциплин группы
        subj_pool = []
        total_group_req_hours = 0

        for s in subjects:
            assigned_teacher_id = s.teacher_id or (teachers[0].id if teachers else None)
            if not assigned_teacher_id:
                continue

            weekly_target_hours = max(1, min(14, math.ceil(s.total_hours / 30)))
            total_group_req_hours += weekly_target_hours

            subj_pool.append({
                "subject": s,
                "teacher_id": assigned_teacher_id,
                "total_hours": s.total_hours,
                "remaining_weekly_hours": weekly_target_hours,
                "is_light": s.total_hours < 70,
                "has_odd_hours": (s.total_hours % 2 != 0)
            })

        effective_max_weekly_hours = 39 if works_on_saturdays else 35

        if total_group_req_hours > effective_max_weekly_hours:
            overflow_warnings.append(
                f"Группа {g.group_number}: затребовано {total_group_req_hours}ч > лимита {effective_max_weekly_hours}ч. Генерация ограничена {effective_max_weekly_hours}ч."
            )

        weekly_hours_assigned = 0

        daily_subject_hours: Dict[Tuple[DayOfWeek, int], int] = {}
        teacher_daily_slots: Dict[Tuple[DayOfWeek, int], List[int]] = {}

        # ИТЕРАЦИЯ ПО ДНЯМ НЕДЕЛИ
        for day, day_slots in WEEK_TEMPLATE.items():
            if day == DayOfWeek.SATURDAY and not works_on_saturdays:
                continue

            if weekly_hours_assigned >= effective_max_weekly_hours:
                break

            for slot in day_slots:
                if weekly_hours_assigned >= effective_max_weekly_hours:
                    break

                slot_num = slot["slot_num"]
                slot_hours = slot["hours"]
                s_start = slot["start"]
                s_end = slot["end"]

                # =========================================================
                # БЛОК 1: РЕЖИМ ПРОИЗВОДСТВЕННОЙ ПРАКТИКИ (Practice Period)
                # Если группа на практике — ставится ИСКЛЮЧИТЕЛЬНО предмет практики.
                # Остаток часов обычных предметов НЕ уменьшается!
                # =========================================================
                if is_practice_active and practice_subject_obj:
                    t_id = practice_subject_obj.teacher_id or (teachers[0].id if teachers else None)
                    t_key = (day, slot_num, t_id)
                    is_conflict = t_key in teacher_busy

                    new_slot = ScheduleSlot(
                        lyceum_id=lyceum_id,
                        group_id=g.id,
                        subject_id=practice_subject_obj.id,
                        teacher_id=t_id,
                        room_id=default_room_id,
                        day_of_week=day,
                        start_time=s_start,
                        end_time=s_end,
                        is_conflict=is_conflict,
                        conflict_reason="⚠️ Накладка преподавание практики" if is_conflict else None
                    )
                    db.session.add(new_slot)
                    if t_id:
                        teacher_busy.add((day, slot_num, t_id))
                    weekly_hours_assigned += slot_hours
                    created_count += 1
                    continue

                # =========================================================
                # БЛОК 2: СТАНДАРТНЫЙ РАУНД-РОБИН ЭВРИСТИЧЕСКИЙ СОЛВЕР
                # Без ограничений на аудитории (Room constraints removed)
                # =========================================================
                def get_candidate_score(item):
                    s_obj = item["subject"]
                    rem = item["remaining_weekly_hours"]
                    already_today = daily_subject_hours.get((day, s_obj.id), 0)

                    if weekly_hours_assigned + slot_hours > effective_max_weekly_hours:
                        return -9999
                    if already_today + slot_hours > 3:
                        return -9999
                    if rem <= 0:
                        return -9999

                    score = 100 + rem * 10
                    t_id = item["teacher_id"]
                    assigned_t_slots = teacher_daily_slots.get((day, t_id), [])
                    if assigned_t_slots:
                        min_gap = min(abs(slot_num - existing_s) for existing_s in assigned_t_slots)
                        if min_gap == 1:
                            score += 250
                        elif min_gap == 2:
                            score += 50
                    else:
                        score += 20

                    if slot_num == 4:
                        if item["is_light"]:
                            score += 500
                        if item["has_odd_hours"] or (rem % 2 != 0):
                            score += 300
                    else:
                        if not item["is_light"]:
                            score += 200

                    if already_today == 0:
                        score += 50

                    return score

                candidates = sorted(subj_pool, key=get_candidate_score, reverse=True)

                chosen_item = None
                is_flagged_conflict = False
                conflict_reason_text = None

                # Назначение предмета и преподавателя (без привязки к аудиториям)
                for item in candidates:
                    if get_candidate_score(item) <= -9999:
                        continue

                    t_id = item["teacher_id"]
                    t_key = (day, slot_num, t_id)

                    if t_key not in teacher_busy:
                        chosen_item = item
                        break

                if not chosen_item:
                    for item in candidates:
                        if get_candidate_score(item) <= -9999:
                            continue
                        chosen_item = item
                        is_flagged_conflict = True
                        teacher_obj = db.session.get(Teacher, item["teacher_id"])
                        t_name = teacher_obj.full_name if teacher_obj else "Преподаватель"
                        conflict_reason_text = f"⚠️ Накладка: {t_name} назначен в другую группу в этот слот"
                        break

                if chosen_item:
                    s_obj = chosen_item["subject"]
                    t_id = chosen_item["teacher_id"]

                    new_slot = ScheduleSlot(
                        lyceum_id=lyceum_id,
                        group_id=g.id,
                        subject_id=s_obj.id,
                        teacher_id=t_id,
                        room_id=default_room_id,
                        day_of_week=day,
                        start_time=s_start,
                        end_time=s_end,
                        is_conflict=is_flagged_conflict,
                        conflict_reason=conflict_reason_text
                    )
                    db.session.add(new_slot)

                    if t_id:
                        teacher_busy.add((day, slot_num, t_id))
                        teacher_daily_slots.setdefault((day, t_id), []).append(slot_num)

                    already = daily_subject_hours.get((day, s_obj.id), 0)
                    daily_subject_hours[(day, s_obj.id)] = already + slot_hours

                    weekly_hours_assigned += slot_hours
                    chosen_item["remaining_weekly_hours"] -= slot_hours
                    created_count += 1

    lyceum.schedule_generated_at = datetime.now(timezone.utc)
    db.session.commit()

    warn_msg = (" (" + "; ".join(overflow_warnings) + ")") if overflow_warnings else ""
    return True, f"Педагогически выверенное расписание сгенерировано! Создано {created_count} слотов (без привязки к кабинетам).{warn_msg}", created_count
