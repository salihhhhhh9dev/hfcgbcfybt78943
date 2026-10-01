"""
build_deploy_zip.py
Automated script to build production deployment archives with UTF-8 filename preservation.
Generates:
1. kalix_saas_release.zip (Clean production deploy package)
2. kalix_saas_project.zip (Complete project package including test suites)
"""

import os
import stat
import datetime
import zipfile

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Core application files for both release and project
CORE_FILES = [
    "app.py",
    "core_schema.py",
    "models.py",
    "auth.py",
    "routes.py",
    "groups.py",
    "schedule_distributor.py",
    "schedule_service.py",
    "scheduler_engine.py",
    "academic_calendar.py",
    "excel_exporter.py",
    "seed_admin.py",
    "seed_db.py",
    "create_excel_curriculum.py",
    "Procfile",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    ".env.example",
    "runtime.txt",
    "wsgi.py",
    "deploy.sh",
    "deploy.bat",
    "README_DEPLOY.md",
    "Учебный_План_1440_часов_ВЕБ-25.xlsx",
    "Учебный_План_3000_часов.xlsx",
]

# Database instance
INSTANCE_FILES = [
    "instance/local_test.db",
]

# HTML Templates
TEMPLATE_FILES = [
    "templates/base.html",
    "templates/dashboard.html",
    "templates/directories.html",
    "templates/distribution.html",
    "templates/group_detail.html",
    "templates/groups_list.html",
    "templates/login.html",
    "templates/register.html",
    "templates/rooms.html",
    "templates/schedule_calendar_config.html",
    "templates/settings.html",
    "templates/tariffs.html",
    "templates/teachers.html",
    "templates/weekly_schedule.html",
    "templates/yearly_matrix.html",
]

# Test suites & extra tools (for project archive)
TEST_FILES = [
    "test_core_calendar.py",
    "test_distinct_pairs_and_grid.py",
    "test_e2e_integration.py",
    "test_official_curriculum_verification.py",
    "test_pedagogical_prioritization_and_reserve.py",
    "test_schedule_distributor.py",
    "index.html",
    "schedule_matrix.html",
]


def build_zip(zip_filename, files):
    zip_path = os.path.join(ROOT_DIR, zip_filename)
    print(f"\n==========================================")
    print(f"Building: {zip_filename}")
    print(f"==========================================")
    
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel_path in files:
            abs_path = os.path.join(ROOT_DIR, rel_path)
            if not os.path.exists(abs_path):
                print(f"[SKIP/MISSING] {rel_path}")
                continue

            arcname = rel_path.replace("\\", "/")
            with open(abs_path, "rb") as f:
                data = f.read()

            zinfo = zipfile.ZipInfo(arcname)
            # CRITICAL: Bit 11 (0x800) forces UTF-8 encoding for filenames (prevents Cyrillic corruption!)
            zinfo.flag_bits |= 0x800

            # Set file timestamp
            mtime = os.path.getmtime(abs_path)
            dt = datetime.datetime.fromtimestamp(mtime)
            zinfo.date_time = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

            # Unix permissions
            if rel_path.endswith((".sh", ".bat")):
                zinfo.external_attr = (0o755 | stat.S_IFREG) << 16
            else:
                zinfo.external_attr = (0o644 | stat.S_IFREG) << 16

            zf.writestr(zinfo, data)
            print(f"  + [{len(data):8d} bytes] {arcname}")

    print(f"SUCCESS: {zip_filename} written ({os.path.getsize(zip_path):,} bytes, {len(files)} files).")


def main():
    # 1. Build kalix_saas_release.zip (production deployment package)
    release_files = CORE_FILES + INSTANCE_FILES + TEMPLATE_FILES
    build_zip("kalix_saas_release.zip", release_files)

    # 2. Build kalix_saas_project.zip (full project archive with test suites)
    project_files = CORE_FILES + INSTANCE_FILES + TEMPLATE_FILES + TEST_FILES
    build_zip("kalix_saas_project.zip", project_files)


if __name__ == "__main__":
    main()
