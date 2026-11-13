"""
scheduler.py - Recurring maintenance daemon for UniSync.
Periodically triggers:
1. Source extraction via extractor.py
2. Dual-agent discovery & review cycle
3. Automatic expiration of overdue active listings
"""
import time
import threading
from datetime import date, datetime, timezone
import schedule

from app.db.db import SessionLocal, Resource
from app.scraper.extractor import extract_all_sources
from app.ai.ai_agent import run_dual_agent_pipeline


def check_and_expire_deadlines(db) -> int:
    """Finds active resources whose deadlines have passed and marks them expired."""
    today = date.today()
    expired_items = (
        db.query(Resource)
        .filter(Resource.status == "current", Resource.deadline < today)
        .all()
    )
    for item in expired_items:
        item.status = "expired"
        item.last_checked = datetime.now(timezone.utc)
        db.add(item)
    db.commit()
    return len(expired_items)


def run_maintenance_job():
    """Single full execution of the scheduled maintenance workflow."""
    print(f"\n⏰ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting UniSync Maintenance Workflow...")
    db = SessionLocal()
    try:
        # 1. Expire outdated listings
        expired_count = check_and_expire_deadlines(db)
        if expired_count:
            print(f"📦 [scheduler] Marked {expired_count} overdue resources as expired.")

        # 2. Extract new campus information
        notices = extract_all_sources()
        print(f"🔎 [scheduler] Extracted {len(notices)} notices across sources.")

        # 3. Run dual-agent discovery + review pipeline
        results = run_dual_agent_pipeline(notices, db)
        accepted = sum(1 for r in results if r["agent2_verdict"] == "accept")
        flagged = sum(1 for r in results if r["agent2_verdict"] == "flag")
        rejected = sum(1 for r in results if r["agent2_verdict"] == "reject")

        print(f"🤖 [scheduler] Pipeline complete -> Accepted: {accepted}, Flagged: {flagged}, Rejected: {rejected}")
    except Exception as exc:
        print(f"❌ [scheduler] Error during maintenance run: {exc}")
    finally:
        db.close()


def start_background_scheduler(interval_minutes: int = 60):
    """Starts the scheduler in a non-blocking background daemon thread."""
    schedule.every(interval_minutes).minutes.do(run_maintenance_job)

    def _loop():
        while True:
            schedule.run_pending()
            time.sleep(1)

    thread = threading.Thread(target=_loop, daemon=True, name="UniSyncScheduler")
    thread.start()
    print(f"🚀 [scheduler] Background maintenance daemon active (runs every {interval_minutes}m).")
    return thread


if __name__ == "__main__":
    print("▶️ Running one-off maintenance pass...")
    run_maintenance_job()
    print("✅ Maintenance complete.")
