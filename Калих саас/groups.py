"""
Group & Curriculum Blueprint (`groups_bp`)
Handles Group Listing, Curriculum Details, Blank Excel Template Download, and Curriculum Upload Parsing.
Tech Stack: Python, Flask, SQLAlchemy, openpyxl
"""

import io
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from models import db, Group, Subject, Lyceum, Teacher, Room, StudentGroup, SubjectCurriculum
from auth import login_required

groups_bp = Blueprint("groups", __name__)


# =========================================================================
# 1. GET /groups & POST /groups/add (Groups Dashboard)
# =========================================================================
@groups_bp.route("/groups", methods=["GET"])
@login_required
def groups_list():
    """
    Renders groups_list.html with list of Groups for current session's lyceum_id.
    """
    lyceum_id = session.get("lyceum_id")
    groups = Group.query.filter_by(lyceum_id=lyceum_id).order_by(Group.group_number).all()
    return render_template("groups_list.html", groups=groups, active_page="groups")


@groups_bp.route("/groups/add", methods=["POST"])
@login_required
def add_group():
    """
    Creates a new Group entity for current lyceum.
    Fields: group_number, student_count, years_of_study.
    """
    lyceum_id = session.get("lyceum_id")
    group_number = request.form.get("group_number", "").strip()
    
    try:
        student_count = int(request.form.get("student_count", 25))
        years_of_study = int(request.form.get("years_of_study", 1))
        course_year = int(request.form.get("course_year", 1))
    except ValueError:
        flash("Ошибка: Неверный числовой формат полей.", "error")
        return redirect(url_for("groups.groups_list"))

    if not group_number:
        flash("Укажите номер группы.", "error")
        return redirect(url_for("groups.groups_list"))

    # Check limit against Lyceum subscription
    lyceum = db.session.get(Lyceum, lyceum_id)
    existing_count = Group.query.filter_by(lyceum_id=lyceum_id).count()
    if lyceum and existing_count >= lyceum.group_limit:
        flash(f"Превышен лимит групп вашего тарифа '{lyceum.tier_name}' (макс. {lyceum.group_limit} групп).", "error")
        return redirect(url_for("groups.groups_list"))

    try:
        new_group = Group(
            lyceum_id=lyceum_id,
            group_number=group_number,
            student_count=student_count,
            years_of_study=years_of_study,
            course_year=course_year
        )
        db.session.add(new_group)
        db.session.commit()
        flash(f"Группа '{group_number}' успешно добавлена!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Ошибка при добавлении группы: {str(e)}", "error")

    return redirect(url_for("groups.groups_list"))


# =========================================================================
# 2. GET /groups/<int:group_id> (Group Detail & Curriculum)
# =========================================================================
@groups_bp.route("/groups/<int:group_id>", methods=["GET"])
@login_required
def group_detail(group_id: int):
    """
    Renders group_detail.html displaying stats and curriculum (Subject list).
    """
    lyceum_id = session.get("lyceum_id")
    group = Group.query.filter_by(id=group_id, lyceum_id=lyceum_id).first_or_404()
    subjects = Subject.query.filter_by(group_id=group.id).order_by(Subject.subject_name).all()
    teachers = Teacher.query.filter_by(lyceum_id=lyceum_id).order_by(Teacher.full_name).all()
    rooms = Room.query.filter_by(lyceum_id=lyceum_id).order_by(Room.room_number).all()
    total_curriculum_hours = sum(s.total_hours for s in subjects)

    return render_template(
        "group_detail.html",
        group=group,
        subjects=subjects,
        teachers=teachers,
        rooms=rooms,
        total_hours=total_curriculum_hours,
        active_page="groups"
    )


# =========================================================================
# 3. GET /api/groups/<int:group_id>/template (Download Blank Excel Template)
# =========================================================================
@groups_bp.route("/api/groups/<int:group_id>/template", methods=["GET"])
@login_required
def download_curriculum_template(group_id: int):
    """
    Generates and returns a styled blank Excel template (.xlsx) with two columns:
    1. 'Название предмета' (Subject Name)
    2. 'Всего часов' (Total Hours)
    """
    lyceum_id = session.get("lyceum_id")
    group = Group.query.filter_by(id=group_id, lyceum_id=lyceum_id).first_or_404()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Учебный план"
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
    headers = ["Название предмета", "Всего часов"]
    for col_idx, text in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=text)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = cell_border

    # Demo sample rows to guide user
    sample_rows = [
        ("Основы программирования", 120),
        ("Основы web дизайна", 60),
        ("Технология программирования", 90),
    ]

    font_data = Font(name="Arial", size=10, color="0F172A")
    fill_sample = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    for row_idx, (s_name, s_hours) in enumerate(sample_rows, start=2):
        ws.row_dimensions[row_idx].height = 22
        c1 = ws.cell(row=row_idx, column=1, value=s_name)
        c2 = ws.cell(row=row_idx, column=2, value=s_hours)
        c1.font = font_data; c1.fill = fill_sample; c1.alignment = align_left; c1.border = cell_border
        c2.font = font_data; c2.fill = fill_sample; c2.alignment = align_center; c2.border = cell_border

    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 18

    output_buffer = io.BytesIO()
    wb.save(output_buffer)
    output_buffer.seek(0)

    filename = f"Шаблон_Учебный_План_Группа_{group.group_number}.xlsx"
    return send_file(
        output_buffer,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )


@groups_bp.route("/download/curriculum_3000", methods=["GET"])
def download_curriculum_3000():
    """
    Downloads pre-filled Excel file with all 24 subjects totaling 3000 hours.
    """
    import os
    filepath = "Учебный_План_3000_часов.xlsx"
    if not os.path.exists(filepath):
        from create_excel_curriculum import create_excel_curriculum
        create_excel_curriculum()

    return send_file(
        filepath,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="Учебный_План_Лицей_3000_часов.xlsx"
    )


# =========================================================================
# 4. POST /api/groups/<int:group_id>/upload (Parse & Save Excel Curriculum)
# =========================================================================
@groups_bp.route("/api/groups/<int:group_id>/upload", methods=["POST"])
@login_required
def upload_curriculum_excel(group_id: int):
    """
    Parses uploaded Excel file, validates columns, replaces/adds Subject records
    linked to this group_id.
    """
    lyceum_id = session.get("lyceum_id")
    group = Group.query.filter_by(id=group_id, lyceum_id=lyceum_id).first_or_404()

    if "file" not in request.files:
        flash("Ошибка: Файл не выбран.", "error")
        return redirect(url_for("groups.group_detail", group_id=group.id))

    file = request.files["file"]
    if not file or file.filename == "":
        flash("Ошибка: Выберите файл формата .xlsx.", "error")
        return redirect(url_for("groups.group_detail", group_id=group.id))

    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        flash("Неверный формат файла. Разрешены только файлы Excel (.xlsx).", "error")
        return redirect(url_for("groups.group_detail", group_id=group.id))

    try:
        wb = openpyxl.load_workbook(file, data_only=True)
        ws = wb.active

        # Validate headers
        col1_header = str(ws.cell(row=1, column=1).value or "").strip()
        col2_header = str(ws.cell(row=1, column=2).value or "").strip()

        if "предмет" not in col1_header.lower() or "часов" not in col2_header.lower():
            flash("Ошибка формата заголовков. Столбец 1 должен содержать 'Название предмета', Столбец 2 — 'Всего часов'.", "error")
            return redirect(url_for("groups.group_detail", group_id=group.id))

        subjects_to_add = []
        rows_parsed = 0

        for r in range(2, ws.max_row + 1):
            name_val = ws.cell(row=r, column=1).value
            hours_val = ws.cell(row=r, column=2).value

            if not name_val or str(name_val).strip() == "":
                continue  # Skip empty rows

            subject_name = str(name_val).strip()
            try:
                hours_num = int(hours_val)
                if hours_num <= 0:
                    continue
            except (ValueError, TypeError):
                continue  # Skip invalid numeric values

            subjects_to_add.append((subject_name, hours_num))
            rows_parsed += 1

        if not subjects_to_add:
            flash("В файле не найдено подходящих строк с предметами и часами.", "error")
            return redirect(url_for("groups.group_detail", group_id=group.id))

        # Clear existing subjects for clean import
        Subject.query.filter_by(group_id=group.id).delete()

        # Insert new subjects
        for s_name, s_hours in subjects_to_add:
            subj = Subject(
                lyceum_id=lyceum_id,
                group_id=group.id,
                name=s_name,
                total_hours=s_hours
            )
            db.session.add(subj)

        db.session.commit()
        flash(f"Учебный план группы '{group.group_number}' успешно обновлен ({rows_parsed} предметов)! ", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Ошибка при обработке файла Excel: {str(e)}", "error")

    return redirect(url_for("groups.group_detail", group_id=group.id))


# =========================================================================
# 5. GET /subjects/<int:subject_id>/distribution & POST /api/subjects/<int:subject_id>/distribute
# =========================================================================
@groups_bp.route("/subjects/<int:subject_id>/distribution", methods=["GET"])
@login_required
def subject_distribution_page(subject_id: int):
    """
    Renders distribution.html UI for interactive semester hours distribution.
    """
    lyceum_id = session.get("lyceum_id")
    subject = Subject.query.filter_by(id=subject_id, lyceum_id=lyceum_id).first_or_404()
    group = Group.query.get_or_404(subject.group_id)
    
    num_semesters = (group.years_of_study or 1) * 2

    return render_template(
        "distribution.html",
        subject=subject,
        group=group,
        num_semesters=num_semesters,
        active_page="groups"
    )


@groups_bp.route("/api/subjects/<int:subject_id>/distribute", methods=["POST"])
@login_required
def save_subject_distribution(subject_id: int):
    """
    POST /api/subjects/<int:subject_id>/distribute
    Receives JSON payload with semester distribution breakdown.
    Validates that sum(hours) == subject.total_hours.
    """
    lyceum_id = session.get("lyceum_id")
    subject = Subject.query.filter_by(id=subject_id, lyceum_id=lyceum_id).first_or_404()

    payload = request.get_json(silent=True) or {}
    distribution = payload.get("distribution", {})

    if not isinstance(distribution, dict):
        return jsonify({"success": False, "error": "Неверный формат данных распределения."}), 400

    try:
        sum_hours = sum(int(v) for v in distribution.values())
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Неверный формат часов в семестрах."}), 400

    if sum_hours != subject.total_hours:
        diff = subject.total_hours - sum_hours
        return jsonify({
            "success": False,
            "error": f"Сумма часов ({sum_hours} ч.) не совпадает с общим объемом дисциплины ({subject.total_hours} ч.)."
        }), 400

    try:
        subject.semester_distribution = distribution
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Распределение часов по семестрам успешно сохранено!",
            "distribution": subject.semester_distribution
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Ошибка сохранения в БД: {str(e)}"}), 500


# =========================================================================
# 5. SMART PDF CURRICULUM PARSER (Multimodal AI Vision Pipeline)
# =========================================================================

import os
import json
import io
import re
import warnings


def extract_curriculum_from_scanned_pdf(file_bytes: bytes) -> list:
    """
    Multimodal AI Vision Parser using pdf2image and Gemini (gemini-1.5-flash).
    Converts scanned PDF pages (with stamps, signatures, handwritten notes) to images
    and uses Gemini Vision to extract table of Subjects and Total Hours.
    """
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        convert_from_bytes = None

    images = []

    # 1. Convert first 1-2 pages of scanned PDF to images using pdf2image (with pypdfium2 fallback)
    if convert_from_bytes:
        try:
            images = convert_from_bytes(file_bytes, first_page=1, last_page=2)
        except Exception as e:
            print(f"[pdf2image Warning] Fallback to pypdfium2 renderer: {e}")

    if not images:
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(file_bytes)
            for page_i in range(min(2, len(pdf))):
                images.append(pdf[page_i].render(scale=2).to_pil())
        except Exception as e2:
            print(f"[PDF Render Error] {e2}")

    if not images:
        raise ValueError("Не удалось преобразовать страницы PDF файла в изображения.")

    # 2. Configure Gemini API Key (Placeholder: GEMINI_API_KEY env var)
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        print("[WARNING] GEMINI_API_KEY environment variable is not set!")
        # Friendly configuration exception when key is not provided yet
        raise ValueError("Ключ API GEMINI_API_KEY не установлен в переменных окружения на сервере. Пожалуйста, установите GEMINI_API_KEY.")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai

    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    # Exact prompt required for scanned table extraction
    prompt = (
        "Analyze this scanned curriculum table. Extract the list of subjects (Наименование дисциплин) "
        "and the total hours (Всего часов). Return strictly a JSON array of objects with keys "
        "'subject' (string) and 'hours' (integer). Do not return markdown, just the JSON."
    )

    # 3. Call Gemini Multimodal Vision API
    response = model.generate_content([prompt] + images)
    response_text = response.text.strip() if (response and hasattr(response, 'text') and response.text) else "[]"

    # Strip markdown codeblocks ```json ... ``` if present
    if "```" in response_text:
        response_text = re.sub(r"^```(?:json)?\s*", "", response_text, flags=re.MULTILINE)
        response_text = re.sub(r"```$", "", response_text, flags=re.MULTILINE).strip()

    # Parse JSON array
    try:
        raw_items = json.loads(response_text)
    except Exception as parse_err:
        print(f"[GEMINI JSON PARSE ERROR] {parse_err}. Response: {response_text}")
        raise ValueError(f"Ошибка разбора ответа от Gemini Vision AI: {parse_err}")

    # Map keys to match frontend Validation Table format (subject_name & total_hours)
    formatted_items = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict):
                subject_name = item.get("subject") or item.get("subject_name") or ""
                total_hours = item.get("hours") or item.get("total_hours") or 0

                try:
                    total_hours = int(total_hours)
                except (ValueError, TypeError):
                    total_hours = 0

                if subject_name and total_hours > 0:
                    formatted_items.append({
                        "subject_name": str(subject_name).strip(),
                        "total_hours": total_hours
                    })

    return formatted_items


@groups_bp.route("/api/curriculum/parse-pdf", methods=["POST"])
@login_required
def parse_curriculum_pdf():
    """
    POST /api/curriculum/parse-pdf
    Multimodal AI Vision PDF Parser:
    Converts scanned PDF pages into JPEG images via pdf2image and sends them to Gemini Vision (gemini-1.5-flash).
    Extracts JSON array of subjects and total hours for Human-in-the-loop validation table.
    """
    if "file" not in request.files and "pdf_file" not in request.files:
        return jsonify({"success": False, "error": "Файл PDF не передан"}), 400

    file = request.files.get("file") or request.files.get("pdf_file")
    if not file or not file.filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "error": "Пожалуйста, выберите скан-копию файла в формате .pdf"}), 400

    try:
        file_bytes = file.read()
        items = extract_curriculum_from_scanned_pdf(file_bytes)

        if not items:
            return jsonify({
                "success": False,
                "error": "Gemini AI Vision не удалось извлечь предметы из скан-копии PDF. Убедитесь, что таблица четко видна."
            }), 422

        return jsonify({
            "success": True,
            "filename": file.filename,
            "count": len(items),
            "items": items
        })
    except ValueError as val_err:
        return jsonify({"success": False, "error": str(val_err)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Ошибка Multimodal AI Vision Парсера: {str(e)}"}), 500


@groups_bp.route("/api/curriculum/confirm-save", methods=["POST"])
@login_required
def confirm_save_curriculum():
    """
    Route 2: POST /api/curriculum/confirm-save
    Accepts validated JSON array from frontend and creates/updates Subject records for Group.
    """
    lyceum_id = session.get("lyceum_id")
    data = request.get_json(silent=True) or {}

    group_id = data.get("group_id")
    items = data.get("items", [])

    if not group_id:
        return jsonify({"success": False, "error": "Пожалуйста, выберите учебную группу"}), 400

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Неверный формат ID группы"}), 400

    group = Group.query.filter_by(id=group_id, lyceum_id=lyceum_id).first()
    if not group:
        return jsonify({"success": False, "error": "Указанная группа не найдена"}), 404

    if not items or not isinstance(items, list):
        return jsonify({"success": False, "error": "Список предметов пуст"}), 400

    saved_count = 0
    updated_count = 0

    try:
        for item in items:
            name = str(item.get("subject_name", "")).strip()
            hours = item.get("total_hours")

            try:
                hours = int(hours)
            except (ValueError, TypeError):
                continue

            if not name or hours <= 0:
                continue

            # Check if subject already exists for this group
            existing = Subject.query.filter_by(group_id=group.id, name=name).first()
            if existing:
                existing.total_hours = hours
                updated_count += 1
            else:
                new_subj = Subject(
                    lyceum_id=lyceum_id,
                    group_id=group.id,
                    name=name,
                    total_hours=hours
                )
                db.session.add(new_subj)
                saved_count += 1

        db.session.commit()

        msg = f"Успешно сохранено {saved_count} новых предметов"
        if updated_count > 0:
            msg += f" и обновлено {updated_count}"
        msg += f" в учебный план группы '{group.group_number}'!"

        return jsonify({
            "success": True,
            "message": msg,
            "group_id": group.id,
            "saved_count": saved_count,
            "updated_count": updated_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Ошибка сохранения в базу данных: {str(e)}"}), 500


@groups_bp.route("/groups/delete/<int:group_id>", methods=["POST"])
@login_required
def delete_group(group_id: int):
    """Удаление группы и её учебного плана."""
    lyceum_id = session.get("lyceum_id")
    group = Group.query.filter_by(id=group_id, lyceum_id=lyceum_id).first()
    if group:
        g_name = group.name
        db.session.delete(group)
        db.session.commit()
        flash(f"Группа «{g_name}» и её учебный план успешно удалены.", "info")
    return redirect(url_for("groups.groups_list"))


@groups_bp.route("/groups/<int:group_id>/subjects/add", methods=["POST"])
@login_required
def add_subject_manual(group_id: int):
    """Ручное добавление дисциплины в учебный план группы."""
    lyceum_id = session.get("lyceum_id")
    group = Group.query.filter_by(id=group_id, lyceum_id=lyceum_id).first_or_404()

    subject_name = request.form.get("subject_name", "").strip()
    total_hours = request.form.get("total_hours", type=int, default=60)
    teacher_id = request.form.get("teacher_id", type=int)
    preferred_room_id = request.form.get("preferred_room_id", type=int)
    subj_type = request.form.get("subject_type", "").strip()

    if not subject_name:
        flash("Укажите название предмета.", "error")
        return redirect(url_for("groups.group_detail", group_id=group.id))

    subj_kwargs = {
        "group_id": group.id,
        "subject_name": subject_name,
        "total_hours": total_hours,
        "allocated_hours": 0,
        "remaining_hours": total_hours,
        "teacher_id": teacher_id if teacher_id else None,
        "preferred_room_id": preferred_room_id if preferred_room_id else None
    }
    if subj_type:
        is_gen = (subj_type.lower() in ("general", "общеобразовательный", "общеобразовательные"))
        subj_kwargs["is_general_education"] = is_gen
        subj_kwargs["subject_type"] = "general" if is_gen else "vocational"

    subj = Subject(**subj_kwargs)
    db.session.add(subj)
    db.session.commit()
    comp_label = "общеобразовательный" if subj.is_general_education else "профессиональный"
    flash(f"Предмет «{subject_name}» ({total_hours} ч., {comp_label}) добавлен в учебный план!", "success")
    return redirect(url_for("groups.group_detail", group_id=group.id))


@groups_bp.route("/groups/subjects/delete/<int:subject_id>", methods=["POST"])
@login_required
def delete_subject(subject_id: int):
    """Удаление предмета из учебного плана."""
    subject = db.session.get(Subject, subject_id)
    if subject:
        group_id = subject.group_id
        db.session.delete(subject)
        db.session.commit()
        flash(f"Предмет «{subject.name}» удален.", "info")
        return redirect(url_for("groups.group_detail", group_id=group_id))
    return redirect(url_for("groups.groups_list"))



