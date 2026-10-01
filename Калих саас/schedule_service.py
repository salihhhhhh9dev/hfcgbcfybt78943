"""
schedule_service.py — Сервис связки БД, Академического календаря и Диспетчера часов.
Обеспечивает сквозную генерацию расписания лицея:
1. Загрузка настроек календаря (плавающий старт, дни недели, праздники)
2. Генерация слотов учебного года через academic_calendar.py
3. Распределение часов и разрешение конфликтов через schedule_distributor.py
4. Сохранение в ScheduleAssignment с обновлением remaining_hours
"""
from datetime import date, time, datetime, timezone
from typing import Dict, Any, List, Set, Optional

from models import (
    db, Lyceum, LyceumSettings, AcademicHoliday, Teacher, Room,
    StudentGroup, SubjectCurriculum, ScheduleAssignment, SlotType
)
from academic_calendar import generate_academic_calendar_slots
from schedule_distributor import ScheduleDistributor


def run_lyceum_schedule_generation(lyceum_id: int) -> Dict[str, Any]:
    """
    Запускает полный цикл генерации расписания лицея.
    """
    lyceum = db.session.get(Lyceum, lyceum_id)
    if not lyceum:
        return {"success": False, "error": "Лицей не найден"}

    # 1. Настройки академического календаря
    settings = lyceum.settings
    if not settings:
        settings = LyceumSettings(
            lyceum_id=lyceum.id,
            academic_year_start=date(2026, 9, 1),
            academic_year_end=date(2027, 6, 30),
            working_days_mask=[0, 1, 2, 3, 4, 5],
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
        db.session.flush()
    else:
        # Убеждаемся, что используются 3 пары и 1 одиночный урок
        if settings.pairs_per_day != 3 or settings.single_lessons_per_day != 1:
            settings.pairs_per_day = 3
            settings.single_lessons_per_day = 1
            db.session.flush()

    # 2. Праздники и исключенные дни
    holiday_dates: Set[date] = {h.date for h in lyceum.holidays}

    # 3. Генерация доступных слотов на весь год с удержанием резервных дней
    calendar_slots = generate_academic_calendar_slots(
        start_date=settings.academic_year_start,
        end_date=settings.academic_year_end,
        working_weekdays=settings.working_days_mask if settings.working_days_mask is not None else [0, 1, 2, 3, 4, 5],
        holiday_dates=holiday_dates,
        pairs_per_day=settings.pairs_per_day or 3,
        single_lessons_per_day=settings.single_lessons_per_day if settings.single_lessons_per_day is not None else 1,
        day_start_time=settings.day_start_time or time(8, 30),
        pair_duration_mins=settings.pair_duration_minutes or 90,
        single_duration_mins=settings.single_lesson_duration_minutes or 45,
        break_mins=settings.regular_break_minutes or 10,
        long_break_after_slot=settings.long_break_after_pair or 2,
        long_break_mins=settings.long_break_minutes or 20,
        reserve_days_count=settings.reserve_days_count if settings.reserve_days_count is not None else 3
    )

    if not calendar_slots:
        return {"success": False, "error": "Календарная сетка не содержит доступных учебных слотов"}

    # 4. Загрузка групп
    groups = StudentGroup.query.filter_by(lyceum_id=lyceum.id).all()
    if not groups:
        return {"success": False, "error": "В лицее пока нет учебных групп. Добавьте группы во вкладке «Группы и часы»"}

    groups_data = [{"id": g.id, "name": g.name} for g in groups]
    group_ids = [g.id for g in groups]

    # 5. Загрузка предметов и часов с педагогической классификацией
    curriculum_items = SubjectCurriculum.query.filter(SubjectCurriculum.group_id.in_(group_ids)).all()
    if not curriculum_items:
        return {"success": False, "error": "Учебные планы групп пусты. Заполните предметы во вкладке «Группы и часы»"}

    curricula_data = []
    for c in curriculum_items:
        total = int(c.total_hours)
        curricula_data.append({
            "id": c.id,
            "group_id": c.group_id,
            "subject_name": c.subject_name,
            "teacher_id": c.teacher_id,
            "preferred_room_id": c.preferred_room_id,
            "total_hours": total,
            "allocated_hours": 0,
            "remaining_hours": total,  # Сброс остатка для нового расчета
            "is_general_education": getattr(c, "is_general_education", True),
            "subject_type": getattr(c, "subject_type", "general")
        })

    # 6. Запуск алгоритма распределения часов и разрешения конфликтов
    distributor = ScheduleDistributor(
        calendar_slots=calendar_slots,
        groups=groups_data,
        curriculum_items=curricula_data,
        max_daily_subject_hours=3,
        pedagogical_boost=15
    )
    dist_results = distributor.run_distribution()

    # 7. Сохранение в базу данных
    try:
        # Удаляем предыдущие назначения для данного лицея
        ScheduleAssignment.query.filter_by(lyceum_id=lyceum.id).delete()

        new_assignments = []
        for a in dist_results["assignments"]:
            st = SlotType.PAIR if a["slot_type"] == "pair" else SlotType.SINGLE_LESSON
            new_assignments.append(
                ScheduleAssignment(
                    lyceum_id=lyceum.id,
                    date=a["date"],
                    slot_number=a["slot_number"],
                    slot_type=st,
                    start_time=a["start_time"],
                    end_time=a["end_time"],
                    group_id=a["group_id"],
                    subject_id=a["subject_id"],
                    teacher_id=a["teacher_id"],
                    room_id=a["room_id"]
                )
            )

        db.session.bulk_save_objects(new_assignments)

        # Обновляем часы в SubjectCurriculum
        for item in dist_results["updated_curriculum"]:
            subj = db.session.get(SubjectCurriculum, item["id"])
            if subj:
                subj.allocated_hours = item["allocated_hours"]
                subj.remaining_hours = item["remaining_hours"]

        lyceum.schedule_generated_at = datetime.now(timezone.utc)
        db.session.commit()

        return {
            "success": True,
            "total_assignments": dist_results["total_assignments"],
            "total_planned_hours": dist_results["total_planned_hours"],
            "total_allocated_hours": dist_results["total_allocated_hours"],
            "total_unallocated_hours": dist_results["total_unallocated_hours"],
            "completion_percent": dist_results["completion_percent"],
            "conflicts_resolved_count": dist_results["conflicts_resolved_count"],
            "conflicts_log": dist_results["conflicts_log"],
            "message": f"Расписание успешно сгенерировано! Создано {dist_results['total_assignments']} занятий ({dist_results['completion_percent']}% покрытия часов). Разрешено конфликтов: {dist_results['conflicts_resolved_count']}."
        }

    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": f"Ошибка сохранения расписания: {str(e)}"}
