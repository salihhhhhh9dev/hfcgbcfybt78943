# 🚀 KALIX SaaS — Инструкция по деплою и развертыванию

Профессиональная система составления годового и недельного расписания для лицеев и колледжей (B2B SaaS).

---

## 📋 Системные требования
- **Python**: 3.10+ (рекомендуется Python 3.11)
- **ОС**: Linux (Ubuntu 20.04+, Debian 11+), Windows 10/11 / Windows Server, macOS
- **База данных**: SQLite (по умолчанию, не требует отдельного сервера) или PostgreSQL (для продакшена)

---

## 🐳 Вариант 1: Запуск через Docker & Docker Compose (Рекомендуемый для сервера)

Развертывание в 1 команду:

```bash
docker-compose up -d --build
```

Сервер запустится на порту `5000`:
- URL: `http://localhost:5000`
- Учётные данные администратора:
  - **Email**: `admin@lyceum14.edu`
  - **Пароль**: `password123`

---

## 🐧 Вариант 2: Запуск на Linux VPS / Сервере

```bash
# 1. Распакуйте архив и перейдите в папку
cd kalix_saas

# 2. Сделайте скрипт исполняемым и запустите деплой
chmod +x deploy.sh
./deploy.sh
```

Или вручную через `systemd`:
```ini
[Unit]
Description=KALIX Lyceum SaaS Service
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/kalix_saas
Environment="PATH=/var/www/kalix_saas/venv/bin"
Environment="PORT=5000"
Environment="HOST=0.0.0.0"
ExecStart=/var/www/kalix_saas/venv/bin/gunicorn --bind 0.0.0.0:5000 --workers 3 --timeout 120 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 🪟 Вариант 3: Запуск на Windows

Просто дважды кликните на `deploy.bat` или выполните в консоли:

```cmd
deploy.bat
```

Скрипт автоматически создаст виртуальное окружение `venv`, установит все зависимости и запустит локальный сервер на `http://127.0.0.1:5000`.

---

## ☁️ Вариант 4: Деплой на Cloud PaaS (Render, Railway, Heroku)

1. Загрузите файлы в Git-репозиторий.
2. В панели платформы создайте Web Service:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn wsgi:app` (уже настроено в `Procfile`)
   - **Environment Variables**:
     - `SECRET_KEY`: ваш уникальный секретный ключ
     - `DATABASE_URL`: строка подключения к БД (SQLite или PostgreSQL)

---

## 🔑 Учётные записи по умолчанию
- **Администратор лицея**: `admin@lyceum14.edu`
- **Пароль**: `password123`

---

## 📁 Структура проекта
- `app.py` — Главное приложение Flask и маршруты
- `core_schema.py`, `models.py` — Модели базы данных SQLAlchemy
- `auth.py` — Аутентификация и сессии
- `groups.py` — Управление группами, студентами и PDF-парсером
- `routes.py` — REST API расписания
- `schedule_service.py`, `scheduler_engine.py` — Алгоритм 100% покрытия расписания (3 пары + 1 урок)
- `excel_exporter.py` — Двухстраничный профессиональный экспорт в Excel (.xlsx)
- `templates/` — Шаблоны Jinja2 в светлой корпоративной теме
- `seed_db.py` — Скрипт наполнения тестовыми данными (Лицей №14, ВЕБ-25, 1440 часов)
- `Dockerfile`, `docker-compose.yml`, `Procfile` — Конфигурации для продакшн-деплоя
