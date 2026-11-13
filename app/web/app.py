"""
app.py - Flask Web Application for UniSync.
Provides:
1. Student-facing portal with category tabs, live search, and deadline tracking.
2. Admin Dashboard & Review Queue with side-by-side Dual-Agent audit trails.
3. Interactive Pipeline Runner & Live Notice Simulator.
"""
import os
import json
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from app.db.db import (
    init_db,
    SessionLocal,
    Resource,
    AuditLog,
    get_active_resources,
    get_flagged_proposals,
    get_all_proposals,
    apply_proposal,
    seed_initial_data,
)
from app.shared.constants import CATEGORIES, CATEGORY_LABELS
from app.shared.models import ExtractedNotice, Proposal
from app.scraper.extractor import extract_all_sources, scrape_html
from app.ai.ai_agent import process_notice_pipeline, run_dual_agent_pipeline
from app.scheduler.scheduler import start_background_scheduler, check_and_expire_deadlines


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static")
    )
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "unisync-dev-key-2026")

    # Initialize tables and seed initial data
    init_db()
    with SessionLocal() as db:
        seed_initial_data(db)

    # ------------------------------------------------------------------
    # Context Processors / Jinja filters
    # ------------------------------------------------------------------
    @app.template_filter("format_date")
    def format_date(value):
        if not value:
            return "No fixed deadline"
        if isinstance(value, str):
            try:
                value = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return value
        return value.strftime("%b %d, %Y")

    @app.template_filter("days_left")
    def days_left(deadline):
        if not deadline:
            return None
        if isinstance(deadline, str):
            try:
                deadline = datetime.strptime(deadline, "%Y-%m-%d").date()
            except ValueError:
                return None
        today = date.today()
        diff = (deadline - today).days
        return diff

    @app.template_filter("parse_json")
    def parse_json(json_str):
        if not json_str:
            return {}
        try:
            return json.loads(json_str)
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # 1️⃣ Student Portal Route
    # ------------------------------------------------------------------
    @app.route("/")
    def index():
        selected_category = request.args.get("category", "all")
        search_query = request.args.get("q", "").strip().lower()

        db = SessionLocal()
        try:
            # First check for any newly expired deadlines
            check_and_expire_deadlines(db)
            all_resources = get_active_resources(db)

            # Filter by category
            if selected_category and selected_category != "all":
                filtered = [r for r in all_resources if r.category.lower() == selected_category.lower()]
            else:
                filtered = all_resources

            # Filter by search
            if search_query:
                filtered = [
                    r for r in filtered
                    if search_query in r.title.lower() or search_query in (r.description or "").lower()
                ]

            # Category stats
            stats = {
                "total": len(all_resources),
                "academic": sum(1 for r in all_resources if r.category == "academic"),
                "opportunity": sum(1 for r in all_resources if r.category == "opportunity"),
                "campus": sum(1 for r in all_resources if r.category == "campus"),
            }

            return render_template(
                "index.html",
                resources=filtered,
                stats=stats,
                selected_category=selected_category,
                search_query=search_query,
                category_labels=CATEGORY_LABELS,
                today=date.today(),
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 2️⃣ Admin Review Queue & Audit Dashboard
    # ------------------------------------------------------------------
    @app.route("/admin")
    def admin_dashboard():
        db = SessionLocal()
        try:
            flagged = get_flagged_proposals(db)
            all_proposals = get_all_proposals(db, limit=30)
            total_active = db.query(Resource).filter(Resource.status == "current").count()
            total_flagged = len(flagged)

            # Decode draft_json for each flagged proposal for template rendering
            for f in flagged:
                try:
                    f.decoded_draft = json.loads(f.draft_json)
                except Exception:
                    f.decoded_draft = {}

            return render_template(
                "admin.html",
                flagged=flagged,
                all_proposals=all_proposals,
                total_active=total_active,
                total_flagged=total_flagged,
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 3️⃣ Admin Action on Proposal (Accept / Reject / Flag)
    # ------------------------------------------------------------------
    @app.route("/admin/proposal/<int:audit_id>/action", methods=["POST"])
    def proposal_action(audit_id):
        verdict = request.form.get("verdict")
        admin_note = request.form.get("reason", "Action taken by Administrator via Admin UI.")

        if verdict not in ("accept", "reject", "flag"):
            flash("Invalid action verdict.", "error")
            return redirect(url_for("admin_dashboard"))

        db = SessionLocal()
        try:
            apply_proposal(db, audit_id=audit_id, verdict=verdict, reason=admin_note)
            flash(f"Proposal #{audit_id} successfully marked as '{verdict.upper()}'.", "success")
        except Exception as exc:
            flash(f"Error updating proposal #{audit_id}: {exc}", "error")
        finally:
            db.close()

        return redirect(url_for("admin_dashboard"))

    # ------------------------------------------------------------------
    # 4️⃣ Interactive Dual-Agent Simulator (Test any notice live)
    # ------------------------------------------------------------------
    @app.route("/admin/simulate-notice", methods=["POST"])
    def simulate_notice():
        title = request.form.get("title", "").strip()
        raw_date = request.form.get("raw_date", "").strip()
        url = request.form.get("url", "").strip() or "https://hub.rgukt.ac.in/notices/manual"
        description = request.form.get("description", "").strip()

        if not title:
            flash("Notice Title is required.", "error")
            return redirect(url_for("admin_dashboard"))

        notice = ExtractedNotice(
            title=title,
            raw_date=raw_date or None,
            description=description or None,
            url=url,
            source="Manual Admin Input"
        )

        db = SessionLocal()
        try:
            result = process_notice_pipeline(notice, db)
            verdict = result["agent2_verdict"].upper()
            flash(f"Processed through Dual-Agent pipeline! Agent 2 Verdict: {verdict}. (Reason: {result['agent2_reason']})", "info")
        except Exception as exc:
            flash(f"Pipeline simulation failed: {exc}", "error")
        finally:
            db.close()

        return redirect(url_for("admin_dashboard"))

    # ------------------------------------------------------------------
    # 5️⃣ API Endpoints for Automation & AJAX
    # ------------------------------------------------------------------
    @app.route("/api/resources", methods=["GET"])
    def api_resources():
        db = SessionLocal()
        try:
            resources = get_active_resources(db)
            data = [
                {
                    "id": r.id,
                    "title": r.title,
                    "category": r.category,
                    "description": r.description,
                    "url": r.url,
                    "deadline": r.deadline.isoformat() if r.deadline else None,
                    "status": r.status,
                    "last_checked": r.last_checked.isoformat(),
                }
                for r in resources
            ]
            return jsonify({"status": "success", "count": len(data), "data": data})
        finally:
            db.close()

    @app.route("/api/pipeline/run-now", methods=["POST"])
    def api_run_pipeline():
        """Triggers source scraping + dual-agent evaluation immediately."""
        db = SessionLocal()
        try:
            notices = extract_all_sources()
            results = run_dual_agent_pipeline(notices, db)
            return jsonify({
                "status": "success",
                "extracted_count": len(notices),
                "processed_results": results
            })
        except Exception as exc:
            return jsonify({"status": "error", "message": str(exc)}), 500
        finally:
            db.close()

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    # Start the background maintenance scheduler
    start_background_scheduler(interval_minutes=60)
    print(f"🌟 Starting UniSync Platform on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
