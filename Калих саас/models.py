"""
models.py — Унифицированные модели базы данных KALIX SaaS.
Полная интеграция с core_schema.py.
"""
from enum import Enum as PyEnum
from flask_sqlalchemy import SQLAlchemy
from core_schema import (
    Base, PlanTier, SlotType, UserRole, User, Lyceum, Subscription,
    LyceumSettings, AcademicHoliday, Teacher, Room, StudentGroup,
    SubjectCurriculum, ScheduleAssignment, TeacherSubstitution,
    Group, Subject, ScheduleSlot, Holiday, ScheduleEntry
)

db = SQLAlchemy(model_class=Base)


class DayOfWeek(int, PyEnum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


__all__ = [
    "Base",
    "db",
    "PlanTier",
    "SlotType",
    "UserRole",
    "User",
    "Lyceum",
    "Subscription",
    "LyceumSettings",
    "AcademicHoliday",
    "Teacher",
    "Room",
    "StudentGroup",
    "SubjectCurriculum",
    "ScheduleAssignment",
    "TeacherSubstitution",
    "Group",
    "Subject",
    "ScheduleSlot",
    "Holiday",
    "ScheduleEntry",
    "DayOfWeek"
]
