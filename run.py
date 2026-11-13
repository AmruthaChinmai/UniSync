"""
run.py - Main entry point to launch the UniSync platform.
Initializes the database, seeds initial campus records, starts the background scheduler,
and launches the Flask web application.
Exposes 'app' for WSGI runners (Gunicorn, Waitress, uWSGI).
"""
import os
import sys

# Ensure root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.db.db import init_db, SessionLocal, seed_initial_data
from app.web.app import create_app
from app.scheduler.scheduler import start_background_scheduler

# 1. Initialize DB and seed initial data
init_db()
with SessionLocal() as db:
    seed_initial_data(db)

# 2. Start background maintenance scheduler
start_background_scheduler(interval_minutes=60)

# 3. Create the Flask app instance for WSGI servers
app = create_app()

def main():
    port = int(os.getenv("PORT", 5000))
    print("=" * 60)
    print("⚡ UniSync - AI-Maintained Student Information Platform")
    print("   RGUKT Basar · Computer Science & Engineering")
    print("=" * 60)
    print(f"🚀 Server running on http://127.0.0.1:{port}")
    print("   - Student Portal:  http://127.0.0.1:5000/")
    print("   - Admin Review:    http://127.0.0.1:5000/admin")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()
