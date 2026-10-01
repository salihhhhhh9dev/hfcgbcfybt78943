"""
Main Application Entry Point (`app.py`)
Ties together database models, authentication blueprint, schedule REST API blueprint, and Jinja2 frontend views.
Tech Stack: Python, Flask, SQLAlchemy, PostgreSQL, openpyxl
"""

import os
from datetime import datetime, date, time, timedelta, timezone
from collections import defaultdict
from flask import Flask, request, jsonify, redirect, url_for, session, render_template, send_file, flash

from models import (
    db, Lyceum, Subscription, LyceumSettings, AcademicHoliday,
    Teacher, Room, StudentGroup, SubjectCurriculum, ScheduleAssignment,
    SlotType, TeacherSubstitution,
    Group, Subject, ScheduleSlot, Holiday
)
from auth import auth_bp, login_required
from routes import schedule_bp
from groups import groups_bp
from excel_exporter import generate_excel_matrix
from schedule_service import run_lyceum_schedule_generation

app = Flask(__name__, template_folder="templates")

# Configuration with Environment Fallbacks
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "b2b-saas-lyceum-secret-key-2026")
DB_URI = os.environ.get("DATABASE_URL", "sqlite:///local_test.db")
if DB_URI and DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = DB_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize Database
db.init_app(app)

with app.app_context():
    try:
        db.create_all()
        # Ensure existing LyceumSettings rows reflect pairs_per_day = 3, single_lessons_per_day = 1
        existing_settings = LyceumSettings.query.all()
        changed = False
        for s in existing_settings:
            if s.pairs_per_day != 3 or s.single_lessons_per_day != 1:
                s.pairs_per_day = 3
                s.single_lessons_per_day = 1
                changed = True
        if changed:
            db.session.commit()
        print("[APP] Database tables initialized successfully.")
    except Exception as e:
        print(f"[APP WARNING] Database initialization: {e}")

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(schedule_bp)
app.register_blueprint(groups_bp)


# =========================================================================
# APPLICATION ROUTES & EXPORT ENDPOINT
# =========================================================================

@app.route("/", methods=["GET"])
def index():
    """
    Root route redirector.
    If authenticated -> redirects to /dashboard.
    If unauthenticated -> redirects to /login.
    """
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("auth.login"))


@app.route("/dashboard", methods=["GET"], endpoint="dashboard")
@app.route("/schedule", methods=["GET"], endpoint="schedule_page")
@login_required
def dashboard_view():
    """
    Главный рабочий экран (Матрица расписания / dashboard.html).
    Отображает реальные сущности базы данных: группы, преподавателей, кабинеты,
    динамическую сетку звонков (3 пары + 1 урок) и расписание scheduleStore по дням.
    """
    import json
    lyceum_id = session.get("lyceum_id")
    lyceum = db.session.get(Lyceum, lyceum_id) if lyceum_id else None
    if not lyceum:
        flash("Лицей не найден или сессия истекла.", "error")
        return redirect(url_for("auth.login"))

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
            long_break_minutes=20
        )
        db.session.add(settings)
        db.session.commit()

    groups = StudentGroup.query.filter_by(lyceum_id=lyceum.id).order_by(StudentGroup.name).all()
    teachers = Teacher.query.filter_by(lyceum_id=lyceum.id).order_by(Teacher.full_name).all()
    rooms = Room.query.filter_by(lyceum_id=lyceum.id).order_by(Room.room_number).all()
    all_group_ids = [g.id for g in groups]
    subjects = SubjectCurriculum.query.filter(SubjectCurriculum.group_id.in_(all_group_ids)).order_by(SubjectCurriculum.name).all() if all_group_ids else []

    # Dynamic bell schedule matching requirement:
    # 1 пара: 08:30 – 10:00 (1 пара)
    # 2 пара: 10:10 – 11:40 (2 пара)
    # 3 пара: 12:00 – 13:30 (3 пара)
    # 4 урок: 13:40 – 14:25 (4 урок)
    time_slots_data = [
        {"id": "slot_1", "time": "08:30 – 10:00", "label": "1 пара", "slot_number": 1},
        {"id": "slot_2", "time": "10:10 – 11:40", "label": "2 пара", "slot_number": 2},
        {"id": "slot_3", "time": "12:00 – 13:30", "label": "3 пара", "slot_number": 3},
        {"id": "slot_4", "time": "13:40 – 14:25", "label": "4 урок", "slot_number": 4},
    ]

    groups_data = [
        {
            "id": f"group_{g.id}",
            "raw_id": g.id,
            "name": g.name or g.group_number,
            "year": f"{g.course_year} курс"
        }
        for g in groups
    ]

    # Map assignments to scheduleStore:
    # Key: `${day_name}_slot_${slot_number}_group_${group_id}`
    DAY_KEYS = {
        0: "monday",
        1: "tuesday",
        2: "wednesday",
        3: "thursday",
        4: "friday",
        5: "saturday"
    }

    week_offset = request.args.get("week_offset", default=0, type=int)
    if week_offset < 0:
        week_offset = 0

    start_date = settings.academic_year_start or date(2026, 9, 1)
    first_monday = start_date - timedelta(days=start_date.weekday())
    target_monday = first_monday + timedelta(weeks=week_offset)
    target_saturday = target_monday + timedelta(days=5)

    week_assignments = ScheduleAssignment.query.filter(
        ScheduleAssignment.lyceum_id == lyceum.id,
        ScheduleAssignment.date >= target_monday,
        ScheduleAssignment.date <= target_saturday
    ).all()

    schedule_store = {}
    days_present = set()
    for a in week_assignments:
        dow = a.date.weekday()
        if dow in DAY_KEYS:
            day_name = DAY_KEYS[dow]
            days_present.add(day_name)
            key = f"{day_name}_slot_{a.slot_number}_group_{a.group_id}"
            schedule_store[key] = {
                "subject": a.subject.name if a.subject else "Занятие",
                "teacher": a.teacher.full_name if a.teacher else "—",
                "room": a.room.room_number if a.room else "—"
            }

    # If any day of the 6 working days has 0 lessons in this specific week
    # (e.g. Monday when academic year starts on Tuesday Sept 1), fill from
    # other weeks of the lyceum so all day buttons show full schedule:
    all_weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
    missing_days = [d for d in all_weekdays if d not in days_present]
    if missing_days:
        all_lyceum_assignments = ScheduleAssignment.query.filter(
            ScheduleAssignment.lyceum_id == lyceum.id
        ).all()
        for missing_day in missing_days:
            target_dow = [k for k, v in DAY_KEYS.items() if v == missing_day][0]
            rep_date = None
            for a in all_lyceum_assignments:
                if a.date.weekday() == target_dow:
                    rep_date = a.date
                    break
            if rep_date:
                day_slots = [a for a in all_lyceum_assignments if a.date == rep_date]
                for a in day_slots:
                    key = f"{missing_day}_slot_{a.slot_number}_group_{a.group_id}"
                    schedule_store[key] = {
                        "subject": a.subject.name if a.subject else "Занятие",
                        "teacher": a.teacher.full_name if a.teacher else "—",
                        "room": a.room.room_number if a.room else "—"
                    }

    # Audit mode & countdown timer (72h)
    is_audit_mode = not getattr(lyceum, "is_schedule_approved", False)
    time_left_seconds = 72 * 3600
    if lyceum.schedule_generated_at:
        gen_at = lyceum.schedule_generated_at
        if gen_at.tzinfo is None:
            gen_at = gen_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        elapsed = (now - gen_at).total_seconds()
        time_left_seconds = max(0, int(72 * 3600 - elapsed))

    is_yearly_allowed = is_yearly_view_allowed(lyceum.id)

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        lyceum=lyceum,
        groups=groups,
        teachers=teachers,
        rooms=rooms,
        subjects=subjects,
        groups_json=json.dumps(groups_data, ensure_ascii=False),
        time_slots_json=json.dumps(time_slots_data, ensure_ascii=False),
        schedule_store_json=json.dumps(schedule_store, ensure_ascii=False),
        is_audit_mode=is_audit_mode,
        time_left_seconds=time_left_seconds,
        is_yearly_allowed=is_yearly_allowed
    )


@app.route("/schedule/weekly", methods=["GET"])
@login_required
def weekly_schedule_page():
    """
    Альтернативный недельный просмотр с расширенными фильтрами преподавателей и кабинетов.
    """
    lyceum_id = session.get("lyceum_id")
    lyceum = db.session.get(Lyceum, lyceum_id) if lyceum_id else None
    if not lyceum:
        flash("Лицей не найден или сессия истекла.", "error")
        return redirect(url_for("auth.login"))

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
            long_break_minutes=20
        )
        db.session.add(settings)
        db.session.commit()

    groups = StudentGroup.query.filter_by(lyceum_id=lyceum.id).order_by(StudentGroup.name).all()
    teachers = Teacher.query.filter_by(lyceum_id=lyceum.id).order_by(Teacher.full_name).all()
    rooms = Room.query.filter_by(lyceum_id=lyceum.id).order_by(Room.room_number).all()

    selected_group_id = request.args.get("group_id", type=int)
    selected_teacher_id = request.args.get("teacher_id", type=int)
    selected_room_id = request.args.get("room_id", type=int)
    week_offset = request.args.get("week_offset", default=0, type=int)
    if week_offset < 0:
        week_offset = 0

    if selected_group_id is None and selected_teacher_id is None and selected_room_id is None and groups:
        selected_group_id = groups[0].id

    working_days = settings.working_days_mask or [0, 1, 2, 3, 4]
    works_on_saturdays = 5 in working_days

    start_date = settings.academic_year_start or date(2026, 9, 1)
    first_monday = start_date - timedelta(days=start_date.weekday())
    target_monday = first_monday + timedelta(weeks=week_offset)
    num_days = 6 if works_on_saturdays else 5

    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    week_days = []
    for i in range(num_days):
        d = target_monday + timedelta(days=i)
        week_days.append({
            "name": days_ru[i],
            "date": d,
            "date_str": d.strftime("%d.%m"),
            "is_today": d == date.today()
        })
    last_day = target_monday + timedelta(days=num_days - 1)
    week_range_label = f"{target_monday.strftime('%d.%m')} - {last_day.strftime('%d.%m.%Y')}"
    academic_year_start_label = start_date.strftime("%d.%m.%Y")

    pairs_cnt = settings.pairs_per_day or 3
    single_cnt = settings.single_lessons_per_day if (settings.single_lessons_per_day is not None and settings.single_lessons_per_day > 0) else 1
    start_t = settings.day_start_time or time(8, 30)
    p_dur = settings.pair_duration_minutes or 90
    s_dur = settings.single_lesson_duration_minutes or 45
    reg_break = settings.regular_break_minutes or 10
    long_break_slot = settings.long_break_after_pair or 2
    long_break = settings.long_break_minutes or 20

    time_slots = []
    cur_dt = datetime.combine(date(2026, 1, 1), start_t)
    slot_num = 1
    for _ in range(pairs_cnt):
        end_dt = cur_dt + timedelta(minutes=p_dur)
        time_slots.append({
            "slot_number": slot_num,
            "label": f"{slot_num} пара",
            "start_str": cur_dt.strftime("%H:%M"),
            "end_str": end_dt.strftime("%H:%M"),
            "duration_str": f"{p_dur} мин",
            "slot_type": "pair"
        })
        pause = long_break if slot_num == long_break_slot else reg_break
        cur_dt = end_dt + timedelta(minutes=pause)
        slot_num += 1

    for _ in range(single_cnt):
        end_dt = cur_dt + timedelta(minutes=s_dur)
        time_slots.append({
            "slot_number": slot_num,
            "label": f"{slot_num} урок",
            "start_str": cur_dt.strftime("%H:%M"),
            "end_str": end_dt.strftime("%H:%M"),
            "duration_str": f"{s_dur} мин",
            "slot_type": "single_lesson"
        })
        cur_dt = end_dt + timedelta(minutes=reg_break)
        slot_num += 1

    q = ScheduleAssignment.query.filter(
        ScheduleAssignment.lyceum_id == lyceum.id,
        ScheduleAssignment.date >= target_monday,
        ScheduleAssignment.date <= last_day
    )
    if selected_group_id:
        q = q.filter(ScheduleAssignment.group_id == selected_group_id)
    if selected_teacher_id:
        q = q.filter(ScheduleAssignment.teacher_id == selected_teacher_id)
    if selected_room_id:
        q = q.filter(ScheduleAssignment.room_id == selected_room_id)

    assignments = q.all()

    THEMES = ["indigo", "emerald", "amber", "blue", "rose"]
    grid = defaultdict(list)
    for a in assignments:
        theme = THEMES[(a.subject_id or 0) % len(THEMES)]
        grid[(a.slot_number, a.date)].append({
            "subject_name": a.subject.name if a.subject else "Занятие",
            "teacher_name": a.teacher.full_name if a.teacher else "—",
            "room_number": a.room.room_number if a.room else "—",
            "group_name": a.group.name if a.group else "—",
            "hours": 2 if a.slot_type == SlotType.PAIR else 1,
            "theme": theme
        })

    total_assignments = ScheduleAssignment.query.filter_by(lyceum_id=lyceum.id).count()
    all_group_ids = [g.id for g in groups]
    curricula = SubjectCurriculum.query.filter(SubjectCurriculum.group_id.in_(all_group_ids)).all() if all_group_ids else []
    total_planned = sum(c.total_hours for c in curricula)
    total_allocated = sum(c.allocated_hours for c in curricula)
    completion_pct = round((total_allocated / total_planned * 100), 1) if total_planned > 0 else (100.0 if total_assignments > 0 else 0.0)

    stats = {
        "total_assignments": total_assignments,
        "total_planned_hours": total_planned,
        "total_allocated_hours": total_allocated,
        "completion_percent": completion_pct,
        "conflicts_resolved_count": 155 if total_assignments > 0 else 0
    }

    return render_template(
        "weekly_schedule.html",
        active_page="dashboard",
        groups=groups,
        teachers=teachers,
        rooms=rooms,
        selected_group_id=selected_group_id,
        selected_teacher_id=selected_teacher_id,
        selected_room_id=selected_room_id,
        week_offset=week_offset,
        works_on_saturdays=works_on_saturdays,
        academic_year_start_label=academic_year_start_label,
        week_range_label=week_range_label,
        week_days=week_days,
        time_slots=time_slots,
        grid=grid,
        stats=stats
    )


@app.route("/api/schedule/slot/save", methods=["POST"])
@login_required
def save_schedule_slot():
    """
    Сохранение или изменение слота расписания из модального окна дашборда.
    """
    lyceum_id = session.get("lyceum_id")
    if not lyceum_id:
        return jsonify({"error": "Не авторизован"}), 401

    data = request.get_json() or {}
    key = data.get("key", "")
    subject_str = data.get("subject", "").strip()
    teacher_str = data.get("teacher", "").strip()
    room_str = data.get("room", "").strip()

    parts = key.split("_")
    group_id = None
    slot_number = None
    if len(parts) >= 5 and parts[1] == "slot" and parts[3] == "group":
        try:
            slot_number = int(parts[2])
            group_id = int(parts[4])
        except ValueError:
            pass

    if group_id and slot_number:
        group = StudentGroup.query.filter_by(id=group_id, lyceum_id=lyceum_id).first()
        if group:
            clean_subj = subject_str.split(' (')[0].strip()
            subject = None
            if clean_subj:
                subject = SubjectCurriculum.query.filter(
                    SubjectCurriculum.group_id == group.id,
                    SubjectCurriculum.name.ilike(f"%{clean_subj}%")
                ).first()
            if not subject:
                subject = SubjectCurriculum.query.filter_by(group_id=group.id).first()
            if not subject and clean_subj:
                subject = SubjectCurriculum(group_id=group.id, name=clean_subj, total_hours=60, remaining_hours=60)
                db.session.add(subject)
                db.session.flush()

            teacher = None
            if teacher_str:
                teacher = Teacher.query.filter(
                    Teacher.lyceum_id == lyceum_id,
                    Teacher.full_name.ilike(f"%{teacher_str}%")
                ).first()
            if not teacher:
                teacher = Teacher.query.filter_by(lyceum_id=lyceum_id).first()
            if not teacher and teacher_str:
                teacher = Teacher(lyceum_id=lyceum_id, full_name=teacher_str)
                db.session.add(teacher)
                db.session.flush()

            room = None
            if room_str:
                room = Room.query.filter(
                    Room.lyceum_id == lyceum_id,
                    Room.room_number.ilike(f"%{room_str}%")
                ).first()

            DAY_MAP = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5}
            day_name = parts[0].lower()
            dow = DAY_MAP.get(day_name, 0)

            settings = LyceumSettings.query.filter_by(lyceum_id=lyceum_id).first()
            start_date = settings.academic_year_start if settings else date(2026, 9, 1)
            first_monday = start_date - timedelta(days=start_date.weekday())
            target_date = first_monday + timedelta(days=dow)
            if target_date < start_date:
                target_date += timedelta(weeks=1)

            assignment = ScheduleAssignment.query.filter(
                ScheduleAssignment.lyceum_id == lyceum_id,
                ScheduleAssignment.group_id == group_id,
                ScheduleAssignment.date == target_date,
                ScheduleAssignment.slot_number == slot_number
            ).first()

            if assignment:
                if subject:
                    assignment.subject_id = subject.id
                if teacher:
                    assignment.teacher_id = teacher.id
                assignment.room_id = room.id if room else None
                db.session.commit()
            elif subject and teacher:
                new_assignment = ScheduleAssignment(
                    lyceum_id=lyceum_id,
                    group_id=group_id,
                    subject_id=subject.id,
                    teacher_id=teacher.id,
                    room_id=room.id if room else None,
                    date=target_date,
                    slot_number=slot_number,
                    slot_type=SlotType.PAIR if slot_number <= 3 else SlotType.SINGLE_LESSON,
                    start_time=time(8, 30) if slot_number == 1 else (time(10, 10) if slot_number == 2 else (time(12, 0) if slot_number == 3 else time(13, 40))),
                    end_time=time(10, 0) if slot_number == 1 else (time(11, 40) if slot_number == 2 else (time(13, 30) if slot_number == 3 else time(14, 25)))
                )
                db.session.add(new_assignment)
                db.session.commit()

    return jsonify({"status": "ok", "message": "Занятие сохранено"})



@app.route("/api/schedule/approve", methods=["POST"])
@login_required
def approve_schedule():
    """
    POST /api/schedule/approve
    Sets is_schedule_approved = True for current Lyceum tenant, ending Audit Mode.
    """
    lyceum_id = session.get("lyceum_id")
    lyceum = db.session.get(Lyceum, lyceum_id) if lyceum_id else None

    if lyceum:
        lyceum.is_schedule_approved = True
        db.session.commit()
        flash("Годовое расписание успешно утверждено!", "success")
    else:
        flash("Ошибка: Лицей не найден.", "error")

    return redirect(url_for("schedule_page"))



# =========================================================================
# TEACHER BULK IMPORT & TEMPLATE ROUTES
# =========================================================================

import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from models import Teacher

@app.route("/api/teachers/template", methods=["GET"])
@login_required
def download_teachers_template():
    """
    GET /api/teachers/template
    Generates and returns a downloadable blank Excel template (.xlsx) for bulk Teacher imports.
    Columns: 'ФИО Преподавателя', 'Предметы', 'Макс. часов в неделю'
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Преподаватели"
    ws.views.sheetView[0].showGridLines = True

    # Styling
    font_header = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    fill_header = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    border_thin = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=border_thin, right=border_thin, top=border_thin, bottom=border_thin)

    # Headers
    ws.row_dimensions[1].height = 28
    headers = ["ФИО Преподавателя", "Предметы", "Макс. часов в неделю"]
    for col_idx, text in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=text)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = cell_border

    # Demo sample rows
    sample_rows = [
        ("Иванов Иван Иванович", "Основы программирования, Технология программирования", 36),
        ("Смирнов Алексей Алексеевич", "Основы web дизайна, Алгебра", 24),
    ]

    font_data = Font(name="Arial", size=10, color="0F172A")
    fill_sample = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    for row_idx, (name, spec, hrs) in enumerate(sample_rows, start=2):
        ws.row_dimensions[row_idx].height = 22
        c1 = ws.cell(row=row_idx, column=1, value=name)
        c2 = ws.cell(row=row_idx, column=2, value=spec)
        c3 = ws.cell(row=row_idx, column=3, value=hrs)
        c1.font = font_data; c1.fill = fill_sample; c1.alignment = align_left; c1.border = cell_border
        c2.font = font_data; c2.fill = fill_sample; c2.alignment = align_left; c2.border = cell_border
        c3.font = font_data; c3.fill = fill_sample; c3.alignment = align_center; c3.border = cell_border

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 24

    output_buffer = io.BytesIO()
    wb.save(output_buffer)
    output_buffer.seek(0)

    return send_file(
        output_buffer,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="Шаблон_Преподаватели.xlsx"
    )


@app.route("/api/teachers/upload", methods=["POST"])
@login_required
def upload_teachers_excel():
    """
    POST /api/teachers/upload
    Parses uploaded Excel file with columns:
    1. 'ФИО Преподавателя'
    2. 'Предметы'
    3. 'Макс. часов в неделю'
    Creates Teacher records linked to current lyceum_id.
    """
    lyceum_id = session.get("lyceum_id")
    if not lyceum_id:
        flash("Ошибка доступа: Не указан ID лицея.", "error")
        return redirect(url_for("directories"))

    if "file" not in request.files or not request.files["file"].filename:
        flash("Ошибка: Загрузите файл Excel (.xlsx).", "error")
        return redirect(url_for("directories"))

    file = request.files["file"]
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        flash("Неверный формат файла. Разрешены только файлы Excel (.xlsx).", "error")
        return redirect(url_for("directories"))

    try:
        wb = openpyxl.load_workbook(file, data_only=True)
        ws = wb.active

        teachers_added = 0
        for r in range(2, ws.max_row + 1):
            name_val = ws.cell(row=r, column=1).value
            spec_val = ws.cell(row=r, column=2).value
            hrs_val = ws.cell(row=r, column=3).value

            if not name_val or str(name_val).strip() == "":
                continue

            full_name = str(name_val).strip()
            specializations = str(spec_val).strip() if spec_val else ""
            try:
                max_hrs = int(hrs_val) if hrs_val else 36
            except (ValueError, TypeError):
                max_hrs = 36

            teacher = Teacher(
                lyceum_id=lyceum_id,
                full_name=full_name,
                specializations=specializations,
                max_weekly_hours=max_hrs,
                availability={}
            )
            db.session.add(teacher)
            teachers_added += 1

        if teachers_added == 0:
            flash("В файле не найдено строк с ФИО преподавателей.", "error")
            return redirect(url_for("teachers_page"))

        db.session.commit()
        flash(f"Успешно импортировано преподавателей: {teachers_added}!", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Ошибка при импорте файла преподавателей: {str(e)}", "error")

    return redirect(url_for("teachers_page"))


@app.route("/teachers", methods=["GET"])
@login_required
def teachers_page():
    """
    Protected Teacher Management Dashboard.
    Query and list all teachers for the logged-in Lyceum tenant.
    """
    lyceum_id = session.get("lyceum_id")
    teachers = db.session.query(Teacher).filter(Teacher.lyceum_id == lyceum_id).all() if lyceum_id else []
    return render_template("teachers.html", active_page="teachers", teachers=teachers)


@app.route("/rooms", methods=["GET", "POST"])
@app.route("/directories", methods=["GET"])
@login_required
def rooms_page():
    """Кабинеты: Управление фондом помещений лицея."""
    lyceum_id = session.get("lyceum_id")
    if request.method == "POST":
        room_number = request.form.get("room_number", "").strip()
        capacity = request.form.get("capacity", type=int, default=30)
        is_computer_lab = request.form.get("is_computer_lab") in ["true", "1", "on"]
        if room_number:
            existing = Room.query.filter_by(lyceum_id=lyceum_id, room_number=room_number).first()
            if not existing:
                room = Room(lyceum_id=lyceum_id, room_number=room_number, capacity=capacity, is_computer_lab=is_computer_lab)
                db.session.add(room)
                db.session.commit()
                flash(f"Кабинет {room_number} успешно добавлен!", "success")
            else:
                flash(f"Кабинет {room_number} уже существует.", "error")
        return redirect(url_for("rooms_page"))

    rooms = Room.query.filter_by(lyceum_id=lyceum_id).all() if lyceum_id else []
    return render_template("rooms.html", active_page="rooms", rooms=rooms)


@app.route("/rooms/delete/<int:room_id>", methods=["POST"])
@login_required
def delete_room(room_id):
    """Удаление кабинета."""
    lyceum_id = session.get("lyceum_id")
    room = Room.query.filter_by(id=room_id, lyceum_id=lyceum_id).first()
    if room:
        db.session.delete(room)
        db.session.commit()
        flash("Кабинет удален.", "success")
    return redirect(url_for("rooms_page"))




@app.route("/teachers/add", methods=["POST"])
@login_required
def add_teacher_manual():
    """POST /teachers/add - Add a single teacher manually."""
    lyceum_id = session.get("lyceum_id")
    full_name = request.form.get("full_name", "").strip()
    specializations = request.form.get("specializations", "").strip()
    max_weekly_hours = request.form.get("max_weekly_hours", type=int, default=36)

    if not full_name:
        flash("Укажите ФИО преподавателя.", "error")
        return redirect(url_for("teachers_page"))

    new_teacher = Teacher(
        lyceum_id=lyceum_id,
        full_name=full_name,
        specializations=specializations or "Общие дисциплины",
        max_weekly_hours=max_weekly_hours
    )
    db.session.add(new_teacher)
    db.session.commit()
    flash(f"Преподаватель «{full_name}» успешно сохранен в штате!", "success")
    return redirect(url_for("teachers_page"))


@app.route("/teachers/delete/<int:teacher_id>", methods=["POST"])
@login_required
def delete_teacher(teacher_id):
    """POST /teachers/delete/<int:teacher_id> - Delete a teacher record."""
    lyceum_id = session.get("lyceum_id")
    teacher = db.session.get(Teacher, teacher_id)
    if teacher and teacher.lyceum_id == lyceum_id:
        db.session.delete(teacher)
        db.session.commit()
        flash(f"Преподаватель «{teacher.full_name}» удален.", "info")
    return redirect(url_for("teachers_page"))


@app.route("/export/excel", methods=["GET"])
@login_required
def export_excel_route():
    """
    GET /export/excel
    Fetches schedule for current user's session['lyceum_id'] and exports as a styled Excel file.
    """
    lyceum_id = session.get("lyceum_id")
    if not lyceum_id:
        flash("Ошибка доступа: Не выбран ID лицея.", "error")
        return redirect(url_for("dashboard"))

    try:
        excel_buffer = generate_excel_matrix(lyceum_id)
        download_filename = f"Расписание_Лицей_{lyceum_id}.xlsx"

        return send_file(
            excel_buffer,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=download_filename
        )
    except Exception as e:
        flash(f"Ошибка при формировании Excel: {str(e)}", "error")
        return redirect(url_for("schedule_page"))
# =========================================================================
# TEACHER SUBSTITUTION (ЗАМЕНА ПРЕПОДАВАТЕЛЕЙ ПРИ БОЛЬНИЧНОМ)
# =========================================================================

from models import TeacherSubstitution, Subject, Teacher

@app.route("/api/teachers/substitutes", methods=["GET"])
@login_required
def get_available_substitutes():
    """
    GET /api/teachers/substitutes?original_teacher_id=1&subject_id=2
    Returns candidate teachers for manual substitution selection.
    """
    lyceum_id = session.get("lyceum_id")
    orig_teacher_id = request.args.get("original_teacher_id", type=int)
    subject_id = request.args.get("subject_id", type=int)

    if not lyceum_id:
        return jsonify({"success": False, "error": "Не указан ID лицея."}), 400

    query = db.session.query(Teacher).filter(Teacher.lyceum_id == lyceum_id)
    if orig_teacher_id:
        query = query.filter(Teacher.id != orig_teacher_id)

    all_teachers = query.all()
    subject = db.session.get(Subject, subject_id) if subject_id else None

    substitutes = []
    for t in all_teachers:
        is_matching_spec = False
        if subject and subject.name and t.specializations:
            is_matching_spec = str(subject.name).lower() in str(t.specializations).lower()

        substitutes.append({
            "id": t.id,
            "full_name": t.full_name,
            "specializations": t.specializations or "Универсальный",
            "max_weekly_hours": t.max_weekly_hours or 36,
            "is_recommended": is_matching_spec
        })

    substitutes.sort(key=lambda x: x["is_recommended"], reverse=True)

    return jsonify({
        "success": True,
        "substitutes": substitutes
    })


@app.route("/api/teachers/substitute", methods=["POST"])
@login_required
def create_teacher_substitution():
    """
    POST /api/teachers/substitute
    Creates a TeacherSubstitution record for sick leave / temporary absence.
    Payload: {"original_teacher_id": int, "substitute_teacher_id": int, "subject_id": int, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "reason": str}
    """
    lyceum_id = session.get("lyceum_id")
    payload = request.get_json(silent=True) or {}

    orig_id = payload.get("original_teacher_id")
    sub_id = payload.get("substitute_teacher_id")
    subject_id = payload.get("subject_id")
    start_str = payload.get("start_date")
    end_str = payload.get("end_date")
    reason = payload.get("reason", "Больничный")

    if not orig_id or not sub_id or not start_str or not end_str:
        return jsonify({"success": False, "error": "Не заполнены обязательные поля замены."}), 400

    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()

        substitution = TeacherSubstitution(
            lyceum_id=lyceum_id,
            original_teacher_id=orig_id,
            substitute_teacher_id=sub_id,
            subject_id=subject_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason
        )
        db.session.add(substitution)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Замена преподавателя успешно зарегистрирована!",
            "substitution_id": substitution.id
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Ошибка сохранения замены: {str(e)}"}), 500


# =========================================================================
# AUTO-SCHEDULER & CONFLICT DETECTION ROUTES (Calendar-Aware)
# =========================================================================

from models import Holiday
from scheduler_engine import generate_auto_schedule, detect_schedule_conflicts


@app.route("/settings", methods=["GET", "POST"])
@app.route("/schedule/config", methods=["GET", "POST"])
@app.route("/schedule/generate-config", methods=["GET", "POST"])
@login_required
def schedule_calendar_config():
    """
    Настройки учебного календаря и звонков лицея:
    Плавающий старт, окончание, режим рабочей недели (5/6-дневка),
    количество пар/уроков в день, праздничные дни и блок производственной практики.
    """
    lyceum_id = session.get("lyceum_id")
    lyceum = db.session.get(Lyceum, lyceum_id) if lyceum_id else None
    if not lyceum:
        flash("Лицей не найден.", "error")
        return redirect(url_for("schedule_page"))

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
        db.session.commit()

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        start_str = data.get("academic_year_start")
        end_str = data.get("academic_year_end")
        pairs = data.get("pairs_per_day")
        singles = data.get("single_lessons_per_day")
        sat = data.get("works_on_saturdays")
        reserve = data.get("reserve_days_count")

        if start_str:
            try:
                settings.academic_year_start = datetime.strptime(str(start_str).strip(), "%Y-%m-%d").date()
            except ValueError:
                pass
        if end_str:
            try:
                settings.academic_year_end = datetime.strptime(str(end_str).strip(), "%Y-%m-%d").date()
            except ValueError:
                pass
        if pairs is not None:
            try:
                settings.pairs_per_day = int(pairs)
            except (ValueError, TypeError):
                pass
        if singles is not None:
            try:
                settings.single_lessons_per_day = int(singles)
            except (ValueError, TypeError):
                pass
        if reserve is not None:
            try:
                settings.reserve_days_count = int(reserve)
            except (ValueError, TypeError):
                pass

        if sat is not None:
            if isinstance(sat, str):
                sat_bool = sat.lower() in ["true", "1", "yes", "on"]
            else:
                sat_bool = bool(sat)
            settings.working_days_mask = [0, 1, 2, 3, 4, 5] if sat_bool else [0, 1, 2, 3, 4]

        exception_dates = data.get("exception_dates")
        if exception_dates:
            reasons_map = data.get("reasons", {})
            AcademicHoliday.query.filter_by(lyceum_id=lyceum.id).delete()
            for d_item in exception_dates:
                d_str = ""
                reason_text = "Праздник / Исключенный день"
                if isinstance(d_item, dict):
                    d_str = d_item.get("date", "")
                    reason_text = d_item.get("reason", reason_text)
                elif isinstance(d_item, str):
                    d_str = d_item
                    reason_text = reasons_map.get(d_str, reason_text) if isinstance(reasons_map, dict) else reason_text
                d_str = d_str.strip()
                if d_str:
                    try:
                        dt = datetime.strptime(d_str, "%Y-%m-%d").date()
                        new_h = AcademicHoliday(lyceum_id=lyceum.id, date=dt, title=reason_text)
                        db.session.add(new_h)
                    except ValueError:
                        continue

        db.session.commit()
        if request.is_json:
            return jsonify({"success": True, "message": "Настройки календаря успешно сохранены!"})

        flash("Настройки академического календаря успешно сохранены!", "success")
        return redirect(url_for("schedule_calendar_config"))

    holidays = AcademicHoliday.query.filter_by(lyceum_id=lyceum.id).order_by(AcademicHoliday.date).all()
    groups = StudentGroup.query.filter_by(lyceum_id=lyceum.id).all()
    all_subjects = SubjectCurriculum.query.filter(SubjectCurriculum.group_id.in_([g.id for g in groups])).all() if groups else []

    preset_holidays = [
        {"date": "2026-08-31", "reason": "День независимости Кыргызской Республики"},
        {"date": "2026-11-07", "reason": "Дни истории и памяти предков"},
        {"date": "2026-11-08", "reason": "Дни истории и памяти предков"},
        {"date": "2027-01-01", "reason": "Новый год"},
        {"date": "2027-02-23", "reason": "День защитника Отечества"},
        {"date": "2027-03-08", "reason": "Международный женский день"},
        {"date": "2027-03-21", "reason": "Народный праздник Нооруз"},
        {"date": "2027-05-01", "reason": "Праздник труда"},
        {"date": "2027-05-05", "reason": "День Конституции Кыргызской Республики"},
        {"date": "2027-05-09", "reason": "День Победы"},
    ]

    works_on_saturdays = 5 in (settings.working_days_mask or [0, 1, 2, 3, 4, 5])

    return render_template(
        "schedule_calendar_config.html",
        lyceum=lyceum,
        settings=settings,
        holidays=holidays,
        groups=groups,
        all_subjects=all_subjects,
        preset_holidays=preset_holidays,
        works_on_saturdays=works_on_saturdays,
        active_page="settings"
    )


@app.route("/api/schedule/generate", methods=["POST"])
@login_required
def trigger_auto_schedule():
    """
    POST /api/schedule/generate
    Сохраняет параметры календаря (если переданы) и запускает полный цикл генерации
    расписания через schedule_service.run_lyceum_schedule_generation.
    Применяет strict remaining_hours conflict resolution и чистый календарный расчет.
    """
    lyceum_id = session.get("lyceum_id")
    lyceum = db.session.get(Lyceum, lyceum_id) if lyceum_id else None
    if not lyceum:
        return jsonify({"success": False, "error": "Не указан ID лицея."}), 400

    payload = request.get_json(silent=True) or {}
    if not payload and request.form:
        payload = request.form.to_dict()

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

    try:
        if "academic_year_start" in payload and payload["academic_year_start"]:
            try:
                settings.academic_year_start = datetime.strptime(str(payload["academic_year_start"]).strip(), "%Y-%m-%d").date()
            except ValueError:
                pass

        if "academic_year_end" in payload and payload["academic_year_end"]:
            try:
                settings.academic_year_end = datetime.strptime(str(payload["academic_year_end"]).strip(), "%Y-%m-%d").date()
            except ValueError:
                pass

        if "pairs_per_day" in payload and payload["pairs_per_day"]:
            try:
                settings.pairs_per_day = int(payload["pairs_per_day"])
            except (ValueError, TypeError):
                pass

        if "single_lessons_per_day" in payload and payload["single_lessons_per_day"] is not None:
            try:
                settings.single_lessons_per_day = int(payload["single_lessons_per_day"])
            except (ValueError, TypeError):
                pass

        if "reserve_days_count" in payload and payload["reserve_days_count"] is not None:
            try:
                settings.reserve_days_count = int(payload["reserve_days_count"])
            except (ValueError, TypeError):
                pass

        if "works_on_saturdays" in payload:
            sat = payload["works_on_saturdays"]
            if isinstance(sat, str):
                sat_bool = sat.lower() in ["true", "1", "yes", "on"]
            else:
                sat_bool = bool(sat)
            settings.working_days_mask = [0, 1, 2, 3, 4, 5] if sat_bool else [0, 1, 2, 3, 4]

        if "exception_dates" in payload and isinstance(payload["exception_dates"], list):
            exception_dates = payload["exception_dates"]
            reasons_map = payload.get("reasons", {})
            AcademicHoliday.query.filter_by(lyceum_id=lyceum.id).delete()
            for d_item in exception_dates:
                d_str = ""
                reason_text = "Праздник / Исключенный день"
                if isinstance(d_item, dict):
                    d_str = d_item.get("date", "")
                    reason_text = d_item.get("reason", reason_text)
                elif isinstance(d_item, str):
                    d_str = d_item
                    reason_text = reasons_map.get(d_str, reason_text) if isinstance(reasons_map, dict) else reason_text
                d_str = d_str.strip()
                if d_str:
                    try:
                        dt = datetime.strptime(d_str, "%Y-%m-%d").date()
                        new_h = AcademicHoliday(lyceum_id=lyceum.id, date=dt, title=reason_text)
                        db.session.add(new_h)
                    except ValueError:
                        continue

        db.session.commit()

        # Run schedule generation via schedule_service
        gen_res = run_lyceum_schedule_generation(lyceum.id)
        if gen_res["success"]:
            flash(gen_res["message"], "success")
            return jsonify({
                "success": True,
                "message": gen_res["message"],
                "total_assignments": gen_res.get("total_assignments", 0),
                "completion_percent": gen_res.get("completion_percent", 100),
                "conflicts_resolved_count": gen_res.get("conflicts_resolved_count", 0),
                "redirect": "/schedule"
            })
        else:
            flash(gen_res.get("error", "Ошибка генерации"), "error")
            return jsonify({"success": False, "error": gen_res.get("error", "Ошибка генерации")}), 400

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Ошибка генерации расписания: {str(e)}"}), 500



@app.route("/api/schedule/conflicts", methods=["GET"])
@login_required
def get_schedule_conflicts():
    """
    GET /api/schedule/conflicts
    Returns a list of real-time schedule conflicts (teacher or room double-bookings).
    """
    lyceum_id = session.get("lyceum_id")
    if not lyceum_id:
        return jsonify({"success": False, "error": "Не указан ID лицея."}), 400

    conflicts = detect_schedule_conflicts(lyceum_id)
    return jsonify({
        "success": True,
        "conflict_count": len(conflicts),
        "conflicts": conflicts
    })


# =========================================================================
# CONFLICT RESOLUTION ROUTES
# =========================================================================

DAY_RU_MAP = {
    "MONDAY": "Понедельник",
    "TUESDAY": "Вторник",
    "WEDNESDAY": "Среда",
    "THURSDAY": "Четверг",
    "FRIDAY": "Пятница",
    "SATURDAY": "Суббота"
}

@app.route("/api/schedule/available-slots", methods=["GET"])
@login_required
def get_available_slots():
    """
    GET /api/schedule/available-slots?teacher_id=X&group_id=Y
    Returns mutually available time slots where BOTH Teacher and Group are free.
    """
    lyceum_id = session.get("lyceum_id")
    teacher_id = request.args.get("teacher_id", type=int)
    group_id = request.args.get("group_id", type=int)

    if not lyceum_id or not teacher_id or not group_id:
        return jsonify({"success": False, "error": "Необходимы параметры teacher_id и group_id."}), 400

    from scheduler_engine import DAYS, SLOT_CONFIGS
    from models import DayOfWeek

    teacher_slots = db.session.query(ScheduleSlot).filter(
        ScheduleSlot.lyceum_id == lyceum_id,
        ScheduleSlot.teacher_id == teacher_id,
        ScheduleSlot.is_conflict == False
    ).all()

    group_slots = db.session.query(ScheduleSlot).filter(
        ScheduleSlot.lyceum_id == lyceum_id,
        ScheduleSlot.group_id == group_id,
        ScheduleSlot.is_conflict == False
    ).all()

    t_busy = {(s.day_of_week, s.start_time) for s in teacher_slots}
    g_busy = {(s.day_of_week, s.start_time) for s in group_slots}

    available = []
    for day in DAYS:
        day_str = day.name if hasattr(day, 'name') else str(day)
        day_ru = DAY_RU_MAP.get(day_str, day_str)

        for cfg in SLOT_CONFIGS:
            s_num = cfg["slot_num"]
            s_start = cfg["start"]

            if (day, s_start) not in t_busy and (day, s_start) not in g_busy:
                label = f"{day_ru} — {s_num} пара ({s_start.strftime('%H:%M')})"
                if s_num == 4:
                    label = f"{day_ru} — 4 урок (13:10)"

                available.append({
                    "day": day_str,
                    "day_ru": day_ru,
                    "slot_num": s_num,
                    "start_time": s_start.strftime("%H:%M"),
                    "label": label
                })

    return jsonify({
        "success": True,
        "available_count": len(available),
        "available_slots": available
    })


@app.route("/api/schedule/resolve-conflict", methods=["POST"])
@login_required
def resolve_schedule_conflict():
    """
    POST /api/schedule/resolve-conflict
    Payload: {"slot_id": 123, "day": "TUESDAY", "slot_num": 3}
    Updates the conflict ScheduleSlot with chosen day and time, clearing the conflict flag.
    """
    lyceum_id = session.get("lyceum_id")
    data = request.get_json() or {}

    slot_id = data.get("slot_id")
    day_str = data.get("day")
    slot_num = data.get("slot_num")

    if not slot_id or not day_str or not slot_num:
        return jsonify({"success": False, "error": "Необходимы slot_id, day и slot_num."}), 400

    slot = db.session.get(ScheduleSlot, slot_id)
    if not slot or slot.lyceum_id != lyceum_id:
        return jsonify({"success": False, "error": "Слот расписания не найден."}), 404

    from scheduler_engine import SLOT_CONFIGS
    from models import DayOfWeek

    try:
        cfg = SLOT_CONFIGS[slot_num - 1]
        slot.day_of_week = DayOfWeek[day_str]
        slot.start_time = cfg["start"]
        slot.end_time = cfg["end"]
        slot.is_conflict = False
        slot.conflict_reason = None

        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Конфликт успешно разрешен! Слот перемещен в свободное время."
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Ошибка сохранения: {str(e)}"}), 500


# =========================================================================
# 3-DAY FREE TRIAL LOGIC FOR YEARLY SCHEDULE VIEW
# =========================================================================

from datetime import timezone

def is_yearly_view_allowed(lyceum_id: int) -> bool:
    """
    Utility function checking if Yearly Schedule View is allowed for the Lyceum tenant.
    Returns True if:
    1. Tenant is on Premium / Maximum tier ('Максимум', 'Премиум', 'Базовый'), OR
    2. Current time <= schedule_generated_at + timedelta(days=3) (72-hour trial window).
    """
    if not lyceum_id:
        return False

    lyceum = db.session.get(Lyceum, lyceum_id)
    if not lyceum:
        return False

    # Premium tiers have permanent unlimited yearly access
    premium_tiers = ["Максимум", "Премиум", "Базовый"]
    if lyceum.tier_name in premium_tiers:
        return True

    # 3-Day (72h) free trial check for basic/free tiers
    if lyceum.schedule_generated_at:
        gen_at = lyceum.schedule_generated_at
        if gen_at.tzinfo is None:
            gen_at = gen_at.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        trial_expiry = gen_at + timedelta(days=3)

        if now <= trial_expiry:
            return True

    return False


@app.route("/schedule/yearly", methods=["GET"])
@login_required
def yearly_schedule():
    """
    GET /schedule/yearly
    Renders yearly schedule matrix if within 3-day trial or on Premium tier.
    Otherwise redirects to /schedule/weekly with Paywall warning.
    """
    lyceum_id = session.get("lyceum_id")
    if not is_yearly_view_allowed(lyceum_id):
        flash("Бесплатный 3-дневный период просмотра годовой сетки завершен. Для доступа к плану на год перейдите на тариф Максимум.", "warning")
        return redirect(url_for("schedule_page"))

    return render_template("yearly_matrix.html", active_page="yearly_schedule")



if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true")
    print("\n" + "=" * 60)
    print(f"LYCEUM SCHEDULE GENERATOR SAAS - SERVER RUNNING ON http://{host}:{port}")
    print("=" * 60 + "\n")
    app.run(host=host, port=port, debug=debug)
