"""
core_schema.py — База Данных KALIX SaaS (Систематизированная архитектура).
Связывает:
- Настройки лицея (адаптивные рабочие дни, пары, уроки, плавающий старт)
- Праздники и каникулы
- Подписки (тарифные ограничения: Базовый, Про, Корпоративный)
- Преподавателей и Кабинеты
- Группы и Часы (с полем remaining_hours для разрешения конфликтов)
- Расписание занятий (ScheduleAssignment)
- Пользователей системы (User)
"""
from datetime import date, time, datetime, timezone, timedelta
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Boolean, Date, Time, DateTime,
    ForeignKey, Enum, JSON, CheckConstraint, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship, synonym

Base = declarative_base()


class PlanTier(str, PyEnum):
    BASE = "base"              # Базовый
    PRO = "pro"                # Про
    CORPORATE = "corporate"    # Корпоративный
    START = "start"            # Старт
    MAXIMUM = "maximum"        # Максимум


class SlotType(str, PyEnum):
    PAIR = "pair"                   # Пара (90 мин / 2 акад. часа)
    SINGLE_LESSON = "single_lesson" # Отдельный урок (45 мин / 1 акад. час)


class UserRole(str, PyEnum):
    SUPERADMIN = "SUPERADMIN"
    LYCEUM_ADMIN = "LYCEUM_ADMIN"


# =========================================================================
# 1. ТЕНАНТ ЛИЦЕЯ, ПОЛЬЗОВАТЕЛИ И ПОДПИСКИ
# =========================================================================

class User(Base):
    """Пользователь системы (Superadmin или Lyceum Admin)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), nullable=True)
    role = Column(String(50), default="LYCEUM_ADMIN")
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)

    lyceum = relationship("Lyceum", back_populates="users")


class Lyceum(Base):
    """Тенант отдельного профессионального лицея."""
    __tablename__ = "lyceums"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    schedule_generated_at = Column(DateTime, nullable=True)
    is_schedule_approved = Column(Boolean, default=False)

    users = relationship("User", back_populates="lyceum", cascade="all, delete-orphan")
    settings = relationship("LyceumSettings", back_populates="lyceum", uselist=False, cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="lyceum", uselist=False, cascade="all, delete-orphan")
    holidays = relationship("AcademicHoliday", back_populates="lyceum", cascade="all, delete-orphan")
    teachers = relationship("Teacher", back_populates="lyceum", cascade="all, delete-orphan")
    rooms = relationship("Room", back_populates="lyceum", cascade="all, delete-orphan")
    groups = relationship("StudentGroup", back_populates="lyceum", cascade="all, delete-orphan")
    schedule_assignments = relationship("ScheduleAssignment", back_populates="lyceum", cascade="all, delete-orphan")

    @property
    def tier_name(self):
        if self.subscription and self.subscription.plan_tier:
            val = self.subscription.plan_tier
            if hasattr(val, "value"):
                val = val.value
            ru_map = {
                "base": "Базовый", "pro": "Про", "corporate": "Корпоративный",
                "start": "Старт", "maximum": "Максимум",
                "базовый": "Базовый", "про": "Про", "корпоративный": "Корпоративный"
            }
            return ru_map.get(str(val).lower(), str(val))
        return "Про"

    @property
    def group_limit(self):
        if self.subscription:
            return self.subscription.max_groups_limit
        return 15

    @property
    def works_on_saturdays(self):
        if self.settings and self.settings.working_days_mask:
            return 5 in self.settings.working_days_mask
        return False


class Subscription(Base):
    """Подписка лицея (Тарифные ограничения)."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), unique=True, nullable=False)
    plan_tier = Column(String(50), default="pro", nullable=False)
    max_groups_limit = Column(Integer, default=15)
    is_active = Column(Boolean, default=True)
    valid_until = Column(DateTime, nullable=True)

    lyceum = relationship("Lyceum", back_populates="subscription")


# =========================================================================
# 2. ГЛОБАЛЬНЫЕ АДАПТИВНЫЕ НАСТРОЙКИ И КАЛЕНДАРЬ
# =========================================================================

class LyceumSettings(Base):
    """Адаптивные параметры сетки и звонков."""
    __tablename__ = "lyceum_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), unique=True, nullable=False)

    academic_year_start = Column(Date, nullable=False, default=date(2026, 9, 1))
    academic_year_end = Column(Date, nullable=False, default=date(2027, 6, 30))

    # Дни недели: [0, 1, 2, 3, 4, 5] = Пн-Сб. 6-дневная учебная неделя (36 часов в неделю)
    working_days_mask = Column(JSON, default=[0, 1, 2, 3, 4, 5], nullable=False)

    # Параметры сетки: директор/завуч может изменить в любой момент
    pairs_per_day = Column(Integer, default=3, nullable=False)
    single_lessons_per_day = Column(Integer, default=1, nullable=False)

    day_start_time = Column(Time, default=time(8, 30), nullable=False)
    pair_duration_minutes = Column(Integer, default=90)
    single_lesson_duration_minutes = Column(Integer, default=45)
    regular_break_minutes = Column(Integer, default=10)
    long_break_after_pair = Column(Integer, default=2)
    long_break_minutes = Column(Integer, default=20)

    # Резервные дни в конце учебного года (по умолчанию 3 рабочих дня)
    reserve_days_count = Column(Integer, default=3, nullable=False)

    lyceum = relationship("Lyceum", back_populates="settings")


class AcademicHoliday(Base):
    """Исключенные праздничные и каникулярные дни."""
    __tablename__ = "academic_holidays"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    title = Column(String(255), nullable=False)

    lyceum = relationship("Lyceum", back_populates="holidays")
    __table_args__ = (UniqueConstraint("lyceum_id", "date", name="uq_lyceum_holiday_date"),)

    @property
    def reason(self):
        return self.title

    @reason.setter
    def reason(self, val):
        self.title = val


# =========================================================================
# 3. ПРЕПОДАВАТЕЛИ И КАБИНЕТЫ
# =========================================================================

class Teacher(Base):
    """Преподаватель лицея."""
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), nullable=False)
    full_name = Column(String(255), nullable=False)
    max_weekly_hours = Column(Integer, default=36)

    lyceum = relationship("Lyceum", back_populates="teachers")
    curriculum_items = relationship("SubjectCurriculum", back_populates="teacher")
    assignments = relationship("ScheduleAssignment", back_populates="teacher", cascade="all, delete-orphan")

    @property
    def specializations(self):
        if self.curriculum_items:
            names = [item.subject_name for item in self.curriculum_items if item.subject_name]
            if names:
                return ", ".join(sorted(set(names)))
        return getattr(self, "_spec_cached", None) or "Общие дисциплины"

    @specializations.setter
    def specializations(self, val):
        self._spec_cached = val

    def __init__(self, **kwargs):
        if "specializations" in kwargs:
            self._spec_cached = kwargs.pop("specializations")
        kwargs.pop("availability", None)
        super().__init__(**kwargs)




class Room(Base):
    """Кабинет или лаборатория."""
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), nullable=False)
    room_number = Column(String(50), nullable=False)
    room_type = Column(String(50), default="lecture")
    capacity = Column(Integer, default=30)

    lyceum = relationship("Lyceum", back_populates="rooms")
    curriculum_items = relationship("SubjectCurriculum", back_populates="preferred_room")
    assignments = relationship("ScheduleAssignment", back_populates="room")

    @property
    def is_computer_lab(self):
        return self.room_type == "computer_lab" or "комп" in (self.room_number or "").lower()

    @is_computer_lab.setter
    def is_computer_lab(self, val):
        self.room_type = "computer_lab" if val else "lecture"

    def __init__(self, **kwargs):
        if "is_computer_lab" in kwargs:
            is_lab = kwargs.pop("is_computer_lab")
            if "room_type" not in kwargs:
                kwargs["room_type"] = "computer_lab" if is_lab else "lecture"
        super().__init__(**kwargs)


# =========================================================================
# 4. ГРУППЫ И ЧАСЫ
# =========================================================================

class StudentGroup(Base):
    """
    Учебная группа. Факт наличия группы определяет нагрузку.
    Количество учеников не влияет на распределение.
    """
    __tablename__ = "student_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(50), nullable=False)
    course_year = Column(Integer, default=1)
    student_count = Column(Integer, default=25)
    years_of_study = Column(Integer, default=3)

    group_number = synonym("name")

    lyceum = relationship("Lyceum", back_populates="groups")
    curriculum = relationship("SubjectCurriculum", back_populates="group", cascade="all, delete-orphan")
    assignments = relationship("ScheduleAssignment", back_populates="group", cascade="all, delete-orphan")

    @property
    def subjects(self):
        return self.curriculum

    def __init__(self, **kwargs):
        if "group_number" in kwargs and "name" not in kwargs:
            kwargs["name"] = kwargs.pop("group_number")
        super().__init__(**kwargs)


class SubjectCurriculum(Base):
    """
    Пул учебных часов дисциплины.
    remaining_hours используется правилом разрешения конфликтов:
    приоритет отдается группе с максимальным remaining_hours!
    """
    __tablename__ = "subject_curriculum"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("student_groups.id", ondelete="CASCADE"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    preferred_room_id = Column(Integer, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)

    subject_name = Column(String(255), nullable=False)
    total_hours = Column(Integer, nullable=False)
    allocated_hours = Column(Integer, default=0)
    remaining_hours = Column(Integer, nullable=False)

    # Педагогическая классификация: общеобразовательный vs профессиональный компонент
    is_general_education = Column(Boolean, default=True, nullable=False)
    subject_type = Column(String(50), default="general", nullable=False)

    name = synonym("subject_name")

    group = relationship("StudentGroup", back_populates="curriculum")
    teacher = relationship("Teacher", back_populates="curriculum_items")
    preferred_room = relationship("Room", back_populates="curriculum_items")
    assignments = relationship("ScheduleAssignment", back_populates="subject", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        if "name" in kwargs and "subject_name" not in kwargs:
            kwargs["subject_name"] = kwargs.pop("name")
        kwargs.pop("lyceum_id", None)
        if "remaining_hours" not in kwargs and "total_hours" in kwargs:
            kwargs["remaining_hours"] = kwargs["total_hours"]
        if "is_general_education" in kwargs and "subject_type" not in kwargs:
            kwargs["subject_type"] = "general" if kwargs["is_general_education"] else "vocational"
        elif "subject_type" in kwargs and "is_general_education" not in kwargs:
            kwargs["is_general_education"] = (str(kwargs["subject_type"]).lower() in ("general", "общеобразовательный", "общеобразовательные"))
        elif "is_general_education" not in kwargs and "subject_type" not in kwargs:
            # Автоматическая педагогическая классификация по названию предмета (для загрузок из Excel и ручного ввода)
            s_low = str(kwargs.get("subject_name") or "").lower()
            voc_keywords = [
                "производствен", "практик", "программирован", "охрана труда",
                "правовые основы", "здоровый образ", "бзож", "вычислени",
                "библиотека яп", "библиотека языков", "мастерск", "лаборатор",
                "web", "веб", "дизайн", "сетев", "баз данн"
            ]
            if any(k in s_low for k in voc_keywords):
                kwargs["is_general_education"] = False
                kwargs["subject_type"] = "vocational"
            else:
                kwargs["is_general_education"] = True
                kwargs["subject_type"] = "general"
        super().__init__(**kwargs)



# =========================================================================
# 5. НАЗНАЧЕНИЕ В РАСПИСАНИИ И ЗАМЕНЫ
# =========================================================================

class ScheduleAssignment(Base):
    """Конкретный назначенный слот занятия в расписании."""
    __tablename__ = "schedule_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    slot_number = Column(Integer, nullable=False)
    slot_type = Column(Enum(SlotType), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    group_id = Column(Integer, ForeignKey("student_groups.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subject_curriculum.id", ondelete="CASCADE"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)

    lyceum = relationship("Lyceum", back_populates="schedule_assignments")
    group = relationship("StudentGroup", back_populates="assignments")
    subject = relationship("SubjectCurriculum", back_populates="assignments")
    teacher = relationship("Teacher", back_populates="assignments")
    room = relationship("Room", back_populates="assignments")

    @property
    def day_of_week(self):
        if self.date is not None:
            return self.date.weekday() + 1
        return getattr(self, "_day_of_week", 1)

    @day_of_week.setter
    def day_of_week(self, val):
        self._day_of_week = val

    def __init__(self, **kwargs):
        dow = kwargs.pop("day_of_week", None)
        if dow is not None:
            self._day_of_week = dow
        if "date" not in kwargs:
            val = dow.value if hasattr(dow, "value") else (dow or 1)
            try:
                dow_int = int(val)
            except (ValueError, TypeError):
                dow_int = 1
            # 2026-08-31 is Monday (1)
            kwargs["date"] = date(2026, 8, 30) + timedelta(days=dow_int)
        if "slot_number" not in kwargs:
            kwargs["slot_number"] = 1
        if "slot_type" not in kwargs:
            kwargs["slot_type"] = SlotType.PAIR
        super().__init__(**kwargs)


class TeacherSubstitution(Base):
    """Временная замена преподавателя при болезни."""
    __tablename__ = "teacher_substitutions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lyceum_id = Column(Integer, ForeignKey("lyceums.id", ondelete="CASCADE"), nullable=False)
    original_teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    substitute_teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subject_curriculum.id", ondelete="CASCADE"), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(String(255), nullable=True, default="Больничный")

    lyceum = relationship("Lyceum")
    original_teacher = relationship("Teacher", foreign_keys=[original_teacher_id])
    substitute_teacher = relationship("Teacher", foreign_keys=[substitute_teacher_id])
    subject = relationship("SubjectCurriculum", foreign_keys=[subject_id])


# =========================================================================
# АЛИАСЫ ДЛЯ ПОЛНОЙ ОБРАТНОЙ СОВМЕСТИМОСТИ
# =========================================================================
Group = StudentGroup
Subject = SubjectCurriculum
ScheduleSlot = ScheduleAssignment
Holiday = AcademicHoliday
ScheduleEntry = ScheduleAssignment
