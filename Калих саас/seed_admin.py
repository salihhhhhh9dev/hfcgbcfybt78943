"""
Standalone Database Seeder Script (`seed_admin.py`)
Creates dummy Lyceum tenant and test Admin user for local authentication testing.
"""

from werkzeug.security import generate_password_hash

try:
    from models import db, Lyceum, User, UserRole
except ImportError:
    from models import Base, Lyceum, User, UserRole
    from flask_sqlalchemy import SQLAlchemy
    db = SQLAlchemy()


def seed_database():
    """
    Seeds a test Lyceum tenant and Admin user.
    Test Credentials:
      Email: admin@lyceum.com
      Password: password123
    """
    print("[SEED] Starting admin database seeding...")

    # 1. Create or query Lyceum tenant
    lyceum = Lyceum.query.filter_by(contact_email="contact@lyceum1.edu").first()
    if not lyceum:
        lyceum = Lyceum(
            name="Профессиональный Лицей №1",
            contact_email="contact@lyceum1.edu",
            subscription_active=True
        )
        db.session.add(lyceum)
        db.session.commit()
        print(f"[SEED] Created Lyceum tenant: '{lyceum.name}' (ID: {lyceum.id})")
    else:
        print(f"[SEED] Found existing Lyceum tenant ID: {lyceum.id}")

    # 2. Create or update test Admin user
    test_email = "admin@lyceum.com"
    test_password = "password123"
    hashed = generate_password_hash(test_password)

    user = User.query.filter_by(email=test_email).first()
    if not user:
        user = User(
            lyceum_id=lyceum.id,
            role=UserRole.LYCEUM_ADMIN,
            email=test_email,
            password_hash=hashed
        )
        db.session.add(user)
        db.session.commit()
        print(f"[SEED] Created Admin User: '{test_email}' (Password: '{test_password}')")
    else:
        user.password_hash = hashed
        user.lyceum_id = lyceum.id
        db.session.commit()
        print(f"[SEED] Updated existing Admin User credentials for: '{test_email}'")

    print("[SEED] Database seeding complete successfully!")


if __name__ == "__main__":
    from flask import Flask
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///local_test.db"  # Fallback for standalone test
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed_database()
