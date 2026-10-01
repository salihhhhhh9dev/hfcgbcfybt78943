"""
Authentication & User Journey Blueprint (`auth_bp`)
Handles Tenant Registration, User Login, Tariff Selection, and Route Protection.
Tech Stack: Python, Flask, SQLAlchemy, Werkzeug
"""

from functools import wraps
from typing import Callable, Any

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from datetime import date
from models import db, Lyceum, User, UserRole, Subscription, LyceumSettings

auth_bp = Blueprint("auth", __name__)


# =========================================================================
# @login_required DECORATOR
# =========================================================================
def login_required(f: Callable) -> Callable:
    """
    Decorator function ensuring that a user session exists before granting access to protected routes.
    If no active session is found, redirects to the login screen with a flash alert.
    """
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if "user_id" not in session:
            flash("Пожалуйста, войдите в систему для доступа к этой странице.", "error")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


# =========================================================================
# 1. GET / POST /register (Tenant & Admin Creation)
# =========================================================================
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """
    Creates a new Lyceum tenant and the primary Admin user.
    On success, logs user in and redirects to Tariff Selection (/tariffs).
    """
    if request.method == "POST":
        lyceum_name = request.form.get("lyceum_name", "").strip()
        contact_email = request.form.get("contact_email", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not lyceum_name or not contact_email or not email or not password:
            flash("Все поля формы обязательны для заполнения.", "error")
            return render_template("register.html")

        # Check existing lyceum or admin user
        existing_lyceum = Lyceum.query.filter_by(contact_email=contact_email).first()
        if existing_lyceum:
            flash("Лицей с таким контактным email уже зарегистрирован.", "error")
            return render_template("register.html")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Пользователь с таким email уже существует.", "error")
            return render_template("register.html")

        try:
            # 1. Create Lyceum tenant
            new_lyceum = Lyceum(
                name=lyceum_name,
                contact_email=contact_email
            )
            db.session.add(new_lyceum)
            db.session.flush()  # Generate new_lyceum.id

            sub = Subscription(
                lyceum_id=new_lyceum.id,
                plan_tier="pro",
                max_groups_limit=15
            )
            settings = LyceumSettings(
                lyceum_id=new_lyceum.id,
                academic_year_start=date(2026, 9, 15),
                academic_year_end=date(2027, 5, 31),
                working_days_mask=[0, 1, 2, 3, 4],
                pairs_per_day=3,
                single_lessons_per_day=1
            )
            db.session.add_all([sub, settings])

            # 2. Create Admin user
            hashed_pwd = generate_password_hash(password)
            new_user = User(
                lyceum_id=new_lyceum.id,
                role="LYCEUM_ADMIN",
                email=email,
                password_hash=hashed_pwd
            )
            db.session.add(new_user)
            db.session.commit()

            # 3. Store session state
            session["user_id"] = new_user.id
            session["lyceum_id"] = new_lyceum.id
            session["lyceum_name"] = new_lyceum.name
            session["role"] = str(new_user.role)
            session["email"] = new_user.email
            session["tier_name"] = new_lyceum.tier_name
            session["group_limit"] = new_lyceum.group_limit

            flash("Лицей успешно зарегистрирован! Выберите тарифный план.", "success")
            return redirect(url_for("auth.tariffs"))

        except Exception as e:
            db.session.rollback()
            flash(f"Ошибка при регистрации: {str(e)}", "error")
            return render_template("register.html")

    return render_template("register.html")


# =========================================================================
# 2. GET / POST /subscriptions & /tariffs (Subscription Selector)
# =========================================================================
@auth_bp.route("/tariffs", methods=["GET", "POST"])
@auth_bp.route("/subscriptions", methods=["GET", "POST"])
@login_required
def tariffs():
    """
    Renders Tariff Selection on GET.
    Updates Lyceum Subscription plan_tier and max_groups_limit on POST, then redirects to /subscriptions.
    """
    lyceum_id = session.get("lyceum_id")
    lyceum = db.session.get(Lyceum, lyceum_id) if lyceum_id else None

    if request.method == "POST":
        tier_name = request.form.get("tier_name", "Про")
        try:
            group_limit = int(request.form.get("group_limit", 15))
        except ValueError:
            group_limit = 15

        if lyceum:
            sub = lyceum.subscription
            if not sub:
                sub = Subscription(lyceum_id=lyceum.id, plan_tier="pro", max_groups_limit=15)
                db.session.add(sub)

            sub.plan_tier = tier_name
            sub.max_groups_limit = group_limit
            db.session.commit()

            # Update session state
            session["tier_name"] = tier_name
            session["group_limit"] = group_limit

            flash(f"Тариф «{tier_name}» успешно активирован!", "success")
            return redirect(url_for("auth.tariffs"))
        else:
            flash("Ошибка: Лицей не найден.", "error")

    return render_template("tariffs.html", active_page="subscriptions")


# =========================================================================
# 3. GET / POST /login
# =========================================================================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Renders login page on GET.
    Authenticates user against PostgreSQL User table on POST using password hash verification.
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("Заполните все поля для входа.", "error")
            return render_template("login.html")

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("Неверный email или пароль.", "error")
            return render_template("login.html")

        # Fetch lyceum details
        lyceum = db.session.get(Lyceum, user.lyceum_id) if user.lyceum_id else None

        # Store session payload
        session["user_id"] = user.id
        session["lyceum_id"] = user.lyceum_id
        session["lyceum_name"] = lyceum.name if lyceum else "Глобальный доступ"
        session["role"] = user.role.value if hasattr(user.role, "value") else str(user.role)
        session["email"] = user.email
        session["tier_name"] = lyceum.tier_name if lyceum else "Суперадмин"
        session["group_limit"] = lyceum.group_limit if lyceum else 9999

        flash("Добро пожаловать в систему!", "success")

        next_page = request.args.get("next")
        if next_page:
            return redirect(next_page)
        
        return redirect(url_for("dashboard"))

    return render_template("login.html")


# =========================================================================
# 4. GET /logout
# =========================================================================
@auth_bp.route("/logout", methods=["GET"])
def logout():
    """
    Clears user session and redirects to login page.
    """
    session.clear()
    flash("Вы успешно вышли из системы.", "info")
    return redirect(url_for("auth.login"))
