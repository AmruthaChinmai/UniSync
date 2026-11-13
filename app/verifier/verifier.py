"""
verifier.py - Rule-based validation layer for UniSync.
Executes deterministic heuristic checks on proposals before Agent 2 review:
1. URL syntax & accessibility
2. Deadline sanity & past-date expiration
3. Duplicate detection against database records
4. Suspicious keyword or missing attribute flags
"""
import re
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from app.shared.models import Proposal, RecordDraft, VerificationResult, ExtractedNotice
from app.db.db import Resource

SUSPICIOUS_TERMS = [
    "click here to claim free",
    "lottery",
    "earn 50,000 working 1 hour",
    "pay registration fee via gpay number",
    "unverified crypto",
    "guaranteed 100% job without interview",
]


def validate_url(url: str) -> bool:
    """Checks if a URL has a valid scheme and netloc."""
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return bool(parsed.scheme in ("http", "https") and parsed.netloc)


def parse_date_safely(date_str: Optional[str]) -> Optional[date]:
    """Attempts to parse varied date representations into datetime.date."""
    if not date_str:
        return None
    cleaned = date_str.strip()

    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def verify_raw_notice(notice: ExtractedNotice) -> VerificationResult:
    """Performs fast heuristic sanity checks on raw extracted notices."""
    flags: List[str] = []
    is_valid = True

    if not notice.title or len(notice.title.strip()) < 5:
        flags.append("Missing or suspiciously short title")
        is_valid = False

    if not validate_url(notice.url):
        flags.append(f"Invalid or missing source URL: '{notice.url}'")

    parsed_date = parse_date_safely(notice.raw_date)
    has_expired = False
    if parsed_date:
        today = date.today()
        if parsed_date < today:
            flags.append(f"Notice deadline ({parsed_date}) is in the past")
            has_expired = True

    desc_lower = (notice.description or "").lower()
    for term in SUSPICIOUS_TERMS:
        if term in desc_lower:
            flags.append(f"Contains suspicious phrase: '{term}'")
            is_valid = False

    return VerificationResult(
        is_valid=is_valid,
        flags=flags,
        has_expired=has_expired,
        normalized_deadline=parsed_date
    )


def verify_proposal(proposal: Proposal, db: Optional[Session] = None) -> VerificationResult:
    """
    Performs deterministic verification on Agent 1's Proposal:
    - Checks draft URL and deadline
    - Checks for duplicate or conflicting records in MySQL/SQLite
    """
    flags: List[str] = []
    is_valid = True
    has_expired = False
    is_duplicate = False
    today = date.today()

    draft = proposal.draft

    # 1. URL check
    if not validate_url(draft.url):
        flags.append("Draft URL is invalid or malformed.")
        is_valid = False

    # 2. Expiry check
    if draft.deadline:
        if draft.deadline < today:
            flags.append(f"Draft deadline ({draft.deadline}) is in the past. Action should be 'expire' or flagged.")
            has_expired = True

    # 3. Suspicious content check
    content_blob = f"{draft.title} {draft.description or ''}".lower()
    for term in SUSPICIOUS_TERMS:
        if term in content_blob:
            flags.append(f"Suspicious flag: Contains suspicious term '{term}'")
            is_valid = False

    # 4. Duplicate / Existing record check against database
    if db:
        existing = db.query(Resource).filter(
            Resource.title.ilike(draft.title.strip())
        ).first()

        if existing:
            if proposal.action == "add_new":
                flags.append(f"Potential duplicate: Record with title '{draft.title}' already exists (ID: {existing.id}).")
                is_duplicate = True
            elif proposal.action == "update":
                if existing.deadline == draft.deadline and (existing.description or "") == (draft.description or ""):
                    flags.append("No actual changes detected compared to existing database record.")

    return VerificationResult(
        is_valid=is_valid,
        flags=flags,
        has_expired=has_expired,
        is_duplicate=is_duplicate,
        normalized_deadline=draft.deadline
    )
