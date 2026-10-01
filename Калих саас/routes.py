"""
Schedule Blueprint (`schedule_bp`)
Flask RESTful API for ScheduleSlot management and Excel Export in a multi-tenant SaaS application.
"""

from datetime import datetime, time
from typing import Tuple

from flask import Blueprint, request, jsonify, Response, send_file
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_

# Import database instance, models, and excel exporter
try:
    from models import db, ScheduleSlot, Lyceum, Group, Teacher, Room, Subject, DayOfWeek
except ImportError:
    from models import Base, ScheduleSlot, Lyceum, Group, Teacher, Room, Subject, DayOfWeek
    from flask_sqlalchemy import SQLAlchemy
    db = SQLAlchemy()

from excel_exporter import generate_excel_matrix

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api/schedule")


def parse_time(time_str: str) -> time:
    """Parses HH:MM or HH:MM:SS string to datetime.time."""
    if isinstance(time_str, time):
        return time_str
    formats = ["%H:%M:%S", "%H:%M"]
    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"Неверный формат времени: '{time_str}'. Ожидается HH:MM или HH:MM:SS.")


# =========================================================================
# 1. GET /api/schedule/<int:lyceum_id>
# =========================================================================
@schedule_bp.route("/<int:lyceum_id>", methods=["GET"])
def get_schedule(lyceum_id: int) -> Tuple[Response, int]:
    """
    Fetches all scheduled slots for a specific lyceum tenant.
    Returns nested relations (group, teacher, room, subject).
    """
    try:
        slots = (
            ScheduleSlot.query
            .filter(ScheduleSlot.lyceum_id == lyceum_id)
            .join(ScheduleSlot.group)
            .join(ScheduleSlot.teacher)
            .join(ScheduleSlot.room)
            .join(ScheduleSlot.subject)
            .all()
        )

        result = []
        for slot in slots:
            result.append({
                "id": slot.id,
                "lyceum_id": slot.lyceum_id,
                "day_of_week": slot.day_of_week.value if hasattr(slot.day_of_week, "value") else slot.day_of_week,
                "start_time": slot.start_time.strftime("%H:%M"),
                "end_time": slot.end_time.strftime("%H:%M"),
                "group": {
                    "id": slot.group.id,
                    "group_number": slot.group.group_number,
                    "course_year": slot.group.course_year,
                    "student_count": slot.group.student_count
                },
                "teacher": {
                    "id": slot.teacher.id,
                    "full_name": slot.teacher.full_name
                },
                "room": {
                    "id": slot.room.id,
                    "room_number": slot.room.room_number,
                    "capacity": slot.room.capacity,
                    "is_computer_lab": slot.room.is_computer_lab
                },
                "subject": {
                    "id": slot.subject.id,
                    "name": slot.subject.name,
                    "credits": slot.subject.credits,
                    "total_hours": slot.subject.total_hours
                }
            })

        return jsonify(result), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"error": "Ошибка базы данных при получении расписания", "details": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "Внутренняя ошибка сервера", "details": str(e)}), 500


# =========================================================================
# 2. POST /api/schedule/<int:lyceum_id>/add
# =========================================================================
@schedule_bp.route("/<int:lyceum_id>/add", methods=["POST"])
def add_schedule_slot(lyceum_id: int) -> Tuple[Response, int]:
    """
    Creates a new schedule slot after verifying double-booking constraints.
    Payload: {group_id, teacher_id, room_id, subject_id, day_of_week, start_time, end_time}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Отсутствует тело JSON запроса"}), 400

    required_fields = [
        "group_id", "teacher_id", "room_id", 
        "subject_id", "day_of_week", "start_time", "end_time"
    ]
    missing = [field for field in required_fields if field not in data]
    if missing:
        return jsonify({"error": f"Отсутствуют обязательные поля: {', '.join(missing)}"}), 400

    try:
        group_id = int(data["group_id"])
        teacher_id = int(data["teacher_id"])
        room_id = int(data["room_id"])
        subject_id = int(data["subject_id"])
        
        day_input = data["day_of_week"]
        if isinstance(day_input, int):
            day_of_week = DayOfWeek(day_input)
        elif isinstance(day_input, str) and day_input.isdigit():
            day_of_week = DayOfWeek(int(day_input))
        elif isinstance(day_input, str) and day_input.upper() in DayOfWeek.__members__:
            day_of_week = DayOfWeek[day_input.upper()]
        else:
            day_of_week = day_input

        new_start = parse_time(data["start_time"])
        new_end = parse_time(data["end_time"])

        if new_start >= new_end:
            return jsonify({"error": "Время начала занятия должно быть раньше времени окончания"}), 400

    except (ValueError, KeyError) as err:
        return jsonify({"error": f"Неверный формат данных: {str(err)}"}), 400

    try:
        # BACKEND CONFLICT VALIDATION (DOUBLE-BOOKING CHECK)
        target_dow = day_of_week.value if hasattr(day_of_week, "value") else int(day_of_week)
        overlapping_slots = ScheduleSlot.query.filter(
            ScheduleSlot.lyceum_id == lyceum_id,
            ScheduleSlot.start_time < new_end,
            ScheduleSlot.end_time > new_start
        ).all()

        day_slots = [
            s for s in overlapping_slots
            if (s.day_of_week.value if hasattr(s.day_of_week, "value") else int(s.day_of_week)) == target_dow
        ]

        teacher_conflict = any(s.teacher_id == teacher_id for s in day_slots)
        if teacher_conflict:
            return jsonify({
                "error": "Преподаватель уже занят в это время",
                "code": "TEACHER_DOUBLE_BOOKED"
            }), 409

        room_conflict = any(s.room_id == room_id for s in day_slots)
        if room_conflict:
            return jsonify({
                "error": "Аудитория уже занята в это время",
                "code": "ROOM_DOUBLE_BOOKED"
            }), 409

        group_conflict = any(s.group_id == group_id for s in day_slots)
        if group_conflict:
            return jsonify({
                "error": "Учебная группа уже имеет занятие в это время",
                "code": "GROUP_DOUBLE_BOOKED"
            }), 409

        new_slot = ScheduleSlot(
            lyceum_id=lyceum_id,
            group_id=group_id,
            teacher_id=teacher_id,
            room_id=room_id,
            subject_id=subject_id,
            day_of_week=day_of_week,
            start_time=new_start,
            end_time=new_end
        )

        db.session.add(new_slot)
        db.session.commit()

        created_slot = db.session.get(ScheduleSlot, new_slot.id)

        return jsonify({
            "message": "Слот расписания успешно добавлен",
            "slot": {
                "id": created_slot.id,
                "lyceum_id": created_slot.lyceum_id,
                "day_of_week": created_slot.day_of_week.value if hasattr(created_slot.day_of_week, "value") else created_slot.day_of_week,
                "start_time": created_slot.start_time.strftime("%H:%M"),
                "end_time": created_slot.end_time.strftime("%H:%M"),
                "group_id": created_slot.group_id,
                "teacher_id": created_slot.teacher_id,
                "room_id": created_slot.room_id,
                "subject_id": created_slot.subject_id
            }
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"error": "Ошибка базы данных при сохранении слота", "details": str(e)}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Внутренняя ошибка сервера", "details": str(e)}), 500


# =========================================================================
# 3. GET /api/schedule/<int:lyceum_id>/export
# =========================================================================
@schedule_bp.route("/<int:lyceum_id>/export", methods=["GET"])
def export_schedule_excel(lyceum_id: int):
    """
    Exports the generated schedule into a styled Excel (.xlsx) file
    grouped by student Group worksheets.
    """
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
        return jsonify({"error": "Ошибка при формировании файла Excel", "details": str(e)}), 500
