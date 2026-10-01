"""
WSGI Production Entry Point
KALIX SaaS — Lyceum Schedule Generator
"""
import os
from app import app, db

# Pre-flight check and table initialization
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        app.logger.warning(f"Database pre-flight check notice: {e}")

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true")
    app.run(host=host, port=port, debug=debug)
