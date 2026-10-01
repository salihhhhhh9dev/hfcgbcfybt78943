# =========================================================================
# KALIX Lyceum SaaS — Production Docker Containerfile
# Python 3.11 Slim with system dependencies for PDF parsing and OpenPyXL
# =========================================================================
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app.py \
    PORT=5000 \
    HOST=0.0.0.0

WORKDIR /app

# Install minimal OS dependencies for PDF rendering and healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure instance folder exists for persistent SQLite database
RUN mkdir -p instance

# Expose web server port
EXPOSE 5000

# Healthcheck to ensure container is healthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Production WSGI command with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "--timeout", "120", "wsgi:app"]
