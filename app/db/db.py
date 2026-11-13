# app/db/db.py
import os
from datetime import datetime, date, timezone
from typing import List, Optional

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Date,
    DateTime,
    Enum,
    Text,
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.shared import constants
from app.shared.models import Proposal, RecordDraft, ReviewVerdict

# ----------------------------------------------------------------------
# 1️⃣  Engine & Session
# ----------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./unisync.db"

# SQLite requires check_same_thread=False for multithreading
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# ----------------------------------------------------------------------
# 2️⃣  Table definitions (match the contract)
# ----------------------------------------------------------------------
class Resource(Base):
    """`records` table – stores the final, vetted resource."""
    __tablename__ = "records"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=True)
    url = Column(String(500), nullable=False, index=True)          # apply_url or source_url
    deadline = Column(Date, nullable=True, index=True)
    status = Column(
        Enum(*constants.RECORD_STATUS, name="record_status"),
        default="current",
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_checked = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("ix_records_title_category", "title", "category"),
    )


class AuditLog(Base):
    """`proposals` table – also serves as a review log."""
    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, nullable=True)  # null when action == add_new
    draft_json = Column(Text, nullable=False)    # JSON string of RecordDraft
    action = Column(
        Enum(*constants.PROPOSAL_ACTION, name="proposal_action"),
        nullable=False,
    )
    agent1_output = Column(Text, nullable=True)   # raw LLM output (for debugging)
    agent2_verdict = Column(
        Enum(*constants.REVIEW_VERDICT, name="review_verdict"),
        nullable=True,
    )
    reason = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


# ----------------------------------------------------------------------
# 3️⃣  Helper functions – thin wrappers around a scoped session
# ----------------------------------------------------------------------
def get_db():
    """FastAPI/Flask-style dependency – creates a short-lived session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------------------------------------------------
# CRUD helpers used by the engine / web layer
# ----------------------------------------------------------------------
def save_proposal(db: Session, proposal: Proposal, raw_agent1_output: str, resource_id: Optional[int] = None) -> AuditLog:
    """Persist a proposal (the engine’s suggestion)."""
    audit = AuditLog(
        resource_id=resource_id or proposal.resource_id,
        draft_json=proposal.draft.json(),
        action=proposal.action,
        agent1_output=raw_agent1_output,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def apply_proposal(db: Session, audit_id: int, verdict: str, reason: Optional[str] = None) -> Optional[Resource]:
    """
    Called from the pipeline or admin UI after a human (or an AI Review Agent)
    decides what to do with a proposal.
    """
    audit = db.query(AuditLog).filter(AuditLog.id == audit_id).one_or_none()
    if not audit:
        raise ValueError(f"AuditLog {audit_id} not found")

    audit.agent2_verdict = verdict
    if reason:
        audit.reason = reason
    db.add(audit)

    affected_resource = None

    # ------------------------------------------------------------------
    # 1️⃣  ACCEPT → write / update the Resource table
    # ------------------------------------------------------------------
    if verdict == "accept":
        proposal_obj = Proposal.parse_raw(audit.draft_json)
        draft_dict = proposal_obj.draft.dict()

        # Find existing resource if updating or by match
        existing = None
        if audit.resource_id:
            existing = db.query(Resource).filter(Resource.id == audit.resource_id).one_or_none()
        if not existing:
            existing = (
                db.query(Resource)
                .filter(Resource.title == draft_dict["title"], Resource.category == draft_dict["category"])
                .one_or_none()
            )

        if audit.action == "expire":
            if existing:
                existing.status = "expired"
                existing.last_checked = datetime.now(timezone.utc)
                db.add(existing)
                affected_resource = existing
        elif existing:
            # UPDATE path
            for key, value in draft_dict.items():
                if key != "id":
                    setattr(existing, key, value)
            existing.last_checked = datetime.now(timezone.utc)
            db.add(existing)
            audit.resource_id = existing.id
            affected_resource = existing
        else:
            # INSERT path
            new_res = Resource(**draft_dict)
            db.add(new_res)
            db.flush()                     # populate new_res.id without commit
            audit.resource_id = new_res.id
            affected_resource = new_res

    db.commit()
    return affected_resource


def get_active_resources(db: Session) -> List[Resource]:
    """Used by the student front-end."""
    return (
        db.query(Resource)
        .filter(Resource.status == "current")
        .order_by(Resource.deadline.asc().nulls_last())
        .all()
    )


def get_flagged_proposals(db: Session) -> List[AuditLog]:
    """Used by the admin UI."""
    return (
        db.query(AuditLog)
        .filter(AuditLog.agent2_verdict == "flag")
        .order_by(AuditLog.timestamp.desc())
        .all()
    )


def get_all_proposals(db: Session, limit: int = 50) -> List[AuditLog]:
    """Audit trail for administrative transparency."""
    return (
        db.query(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )


# ----------------------------------------------------------------------
# Seed initial sample data (RGUKT Basar sample notices & resources)
# ----------------------------------------------------------------------
def seed_initial_data(db: Session) -> None:
    count = db.query(Resource).count()
    if count > 0:
        return

    sample_items = [
        {
            "title": "RGUKT End-Semester Examinations Timetable - CSE Department",
            "category": "academic",
            "description": "Comprehensive schedule and room allotments for B.Tech Semester-II end exams.",
            "url": "https://hub.rgukt.ac.in/notices/cse-exam-schedule-2026",
            "deadline": date(2026, 12, 10),
            "status": "current"
        },
        {
            "title": "Google Summer of Code (GSoC) 2026 - Student Applications Open",
            "category": "opportunity",
            "description": "Global program focused on bringing student developers into open source software development.",
            "url": "https://summerofcode.withgoogle.com",
            "deadline": date(2026, 11, 30),
            "status": "current"
        },
        {
            "title": "Campus Placement Drive: Infosys & TCS Digital Recruitment",
            "category": "opportunity",
            "description": "Online registration for final year engineering students. Minimum CGPA required: 7.0.",
            "url": "https://rgukt.ac.in/placements/drives/it-2026",
            "deadline": date(2026, 11, 25),
            "status": "current"
        },
        {
            "title": "National Science & Engineering Hackathon: Smart India Hackathon",
            "category": "opportunity",
            "description": "Nationwide initiative to provide students a platform to solve pressing problems of society.",
            "url": "https://sih.gov.in",
            "deadline": date(2026, 12, 5),
            "status": "current"
        },
        {
            "title": "Hostel Maintenance & Mess Feedback Form - Basar Campus",
            "category": "campus",
            "description": "All students are requested to submit weekly mess and facility feedback.",
            "url": "https://hub.rgukt.ac.in/campus/mess-feedback",
            "deadline": date(2026, 11, 20),
            "status": "current"
        },
        {
            "title": "Data Structures & Algorithms in C++ Lecture Notes & Question Bank",
            "category": "academic",
            "description": "Curated syllabus notes, code examples, and 5-year previous question papers.",
            "url": "https://rgukt.ac.in/academics/cse/dsa-notes",
            "deadline": None,
            "status": "current"
        }
    ]

    for item in sample_items:
        db.add(Resource(**item))
    db.commit()


# ----------------------------------------------------------------------
# Run once to create tables (or use Alembic later)
# ----------------------------------------------------------------------
def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    seed_initial_data(db)
    db.close()
    print("✅ DB tables created / verified and seeded.")
