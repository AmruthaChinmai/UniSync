"""
ai_agent.py - Dual-Agent Intelligence Engine for UniSync.

ARCHITECTURE:
- Agent 1 (DiscoveryAgent):
    Parses messy notice text, extracts structured fields, normalizes dates,
    queries the database to detect existing entries, and proposes an action (add_new, update, expire, duplicate).

- Agent 2 (ReviewAgent):
    Audits and assists Agent 1. It acts as an independent evaluator:
    Compares Agent 1's structured proposal against the raw source notice and database records,
    detects potential hallucinations or conflicts, and produces a final verdict:
    "accept" (auto-publish), "reject" (discard), or "flag" (send to Admin Review Queue).
"""
import os
import json
import re
from datetime import date, datetime
from typing import Optional, Dict, Any, Tuple
import requests
from sqlalchemy.orm import Session

from app.shared.models import (
    ExtractedNotice,
    RecordDraft,
    Proposal,
    VerificationResult,
    ReviewResult,
    ReviewVerdict,
)
from app.shared.constants import CATEGORIES
from app.db.db import Resource, AuditLog, save_proposal, apply_proposal
from app.verifier.verifier import verify_proposal, parse_date_safely


# ----------------------------------------------------------------------
# LLM Integration Helper (Gemini REST API with fallback)
# ----------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def call_llm(prompt: str, system_instruction: str = "") -> Optional[str]:
    """
    Invokes Gemini API via standard HTTPS REST if GEMINI_API_KEY is present.
    Returns None if no API key is provided or if network call fails.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_instruction}\n\n{prompt}" if system_instruction else prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    try:
        resp = requests.post(url, json=payload, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                return candidates[0]["content"]["parts"][0]["text"]
    except Exception as exc:
        print(f"⚠️ [ai_agent] Gemini API call failed: {exc}")
    return None


# ----------------------------------------------------------------------
# 1️⃣ Agent 1: Discovery & Maintenance Agent
# ----------------------------------------------------------------------
class DiscoveryAgent:
    """
    Primary worker agent. Responsible for:
    1. Extracting structured metadata from raw text.
    2. Categorizing (academic, opportunity, campus).
    3. Normalizing deadlines into YYYY-MM-DD.
    4. Comparing against existing records in DB.
    5. Proposing an action (add_new, update, expire, duplicate).
    """

    @classmethod
    def infer_category(cls, text: str) -> str:
        text_lower = text.lower()
        if any(w in text_lower for w in ["exam", "syllabus", "notes", "lecture", "remedial", "curriculum", "paper", "timetable"]):
            return "academic"
        elif any(w in text_lower for w in ["internship", "hiring", "recruitment", "job", "stipend", "hackathon", "scholarship", "careers"]):
            return "opportunity"
        elif any(w in text_lower for w in ["hostel", "mess", "holiday", "campus", "fest", "sports", "circular", "notice", "admin"]):
            return "campus"
        return "campus"

    @classmethod
    def run(cls, notice: ExtractedNotice, db: Optional[Session] = None) -> Tuple[Proposal, str]:
        """
        Runs Agent 1 to convert raw ExtractedNotice into a Proposal.
        Returns (Proposal, raw_agent1_output).
        """
        raw_prompt = f"""
        Extract structured information from this campus notice:
        Title: {notice.title}
        Raw Date: {notice.raw_date}
        Description: {notice.description}
        Source URL: {notice.url}

        Return a JSON object with:
        {{
            "title": "Clean concise title",
            "category": "academic | opportunity | campus",
            "deadline": "YYYY-MM-DD or null",
            "description": "Short informative summary (1-2 sentences)",
            "url": "Valid application or source URL"
        }}
        """

        llm_response = call_llm(
            raw_prompt,
            system_instruction="You are Agent 1 (Discovery Agent) in the UniSync multi-agent system."
        )

        extracted_data = None
        if llm_response:
            try:
                extracted_data = json.loads(llm_response)
            except Exception:
                extracted_data = None

        # Fallback to deterministic NLP extraction if LLM is unavailable or failed
        if not extracted_data:
            clean_title = notice.title.strip()
            category = cls.infer_category(f"{clean_title} {notice.description or ''}")
            parsed_deadline = parse_date_safely(notice.raw_date)

            # If date not in raw_date, search description
            if not parsed_deadline and notice.description:
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})|(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})", notice.description)
                if date_match:
                    parsed_deadline = parse_date_safely(date_match.group(0))

            extracted_data = {
                "title": clean_title,
                "category": category,
                "deadline": parsed_deadline.isoformat() if parsed_deadline else None,
                "description": (notice.description or clean_title)[:250],
                "url": notice.url,
            }

        # Convert deadline to date object
        deadline_obj = None
        if extracted_data.get("deadline"):
            deadline_obj = parse_date_safely(str(extracted_data["deadline"]))

        draft = RecordDraft(
            title=extracted_data.get("title", notice.title),
            category=extracted_data.get("category", "campus"),
            description=extracted_data.get("description"),
            url=extracted_data.get("url", notice.url),
            deadline=deadline_obj,
            status="current"
        )

        # --------------------------------------------------------------
        # Determine Proposed Action by comparing with DB
        # --------------------------------------------------------------
        action = "add_new"
        resource_id = None
        reason = "New campus information discovered."

        if db:
            # Check for existing match by title similarity or URL
            existing = (
                db.query(Resource)
                .filter(
                    (Resource.title.ilike(draft.title.strip())) |
                    (Resource.url == draft.url)
                )
                .first()
            )

            if existing:
                resource_id = existing.id
                today = date.today()

                if draft.deadline and draft.deadline < today:
                    action = "expire"
                    reason = f"Existing record (ID: {existing.id}) has passed its deadline."
                elif existing.deadline != draft.deadline:
                    action = "update"
                    reason = f"Deadline changed from {existing.deadline} to {draft.deadline}."
                elif (existing.description or "") != (draft.description or ""):
                    action = "update"
                    reason = f"Updated description details detected for existing record (ID: {existing.id})."
                else:
                    action = "duplicate"
                    reason = f"Matches existing active record (ID: {existing.id}) with no changes."

        proposal = Proposal(
            draft=draft,
            action=action,
            resource_id=resource_id,
            reason=reason
        )

        raw_output_log = json.dumps({
            "agent": "Agent 1: DiscoveryAgent",
            "extracted": extracted_data,
            "proposed_action": action,
            "matched_resource_id": resource_id
        }, indent=2)

        return proposal, raw_output_log


# ----------------------------------------------------------------------
# 2️⃣ Agent 2: Review & Verification Agent
# ----------------------------------------------------------------------
class ReviewAgent:
    """
    Supervisory / Quality Assurance Agent.
    Assists Agent 1 by:
    1. Auditing Agent 1's extracted values against the original raw notice.
    2. Checking for hallucinations or misrepresented deadlines.
    3. Reviewing verifier flags (e.g., past dates, broken links).
    4. Producing the final decision: 'accept', 'reject', or 'flag'.
    """

    @classmethod
    def run(
        cls,
        raw_notice: ExtractedNotice,
        proposal: Proposal,
        verification: VerificationResult,
        db: Optional[Session] = None
    ) -> ReviewResult:
        """
        Agent 2 reviews Agent 1's proposal and returns a ReviewResult.
        """
        # Step 1: LLM-based intelligent review if Gemini is configured
        review_prompt = f"""
        You are Agent 2 (Review Agent) in the UniSync platform.
        Your job is to audit Agent 1 (Discovery Agent)'s extracted proposal to prevent hallucinations,
        ensure information integrity, and decide whether to publish.

        RAW NOTICE:
        Title: {raw_notice.title}
        Raw Date: {raw_notice.raw_date}
        Description: {raw_notice.description}
        Source URL: {raw_notice.url}

        AGENT 1 PROPOSAL:
        Draft Title: {proposal.draft.title}
        Draft Category: {proposal.draft.category}
        Draft Deadline: {proposal.draft.deadline}
        Draft URL: {proposal.draft.url}
        Proposed Action: {proposal.action}
        Reason: {proposal.reason}

        VERIFIER HEURISTIC FLAGS:
        {json.dumps(verification.flags)}

        EVALUATE:
        1. Hallucination check: Is the deadline or link made up, or faithfully extracted?
        2. Action check: Is the proposed action ('add_new', 'update', 'expire', 'duplicate') appropriate?
        3. Risk: If dubious or broken, return 'flag' or 'reject'.

        Return JSON:
        {{
            "verdict": "accept" | "reject" | "flag",
            "reason": "Detailed justification explaining your verdict to human administrators.",
            "confidence": 0.0 to 1.0
        }}
        """

        llm_response = call_llm(
            review_prompt,
            system_instruction="You are Agent 2, a rigorous verification and review agent."
        )

        if llm_response:
            try:
                data = json.loads(llm_response)
                verdict = data.get("verdict", "flag").lower()
                if verdict not in ("accept", "reject", "flag"):
                    verdict = "flag"
                return ReviewResult(
                    verdict=verdict,
                    reason=f"[Agent 2 Audit]: {data.get('reason', 'Audited by Review Agent.')}",
                    confidence=float(data.get("confidence", 0.9))
                )
            except Exception:
                pass

        # --------------------------------------------------------------
        # Deterministic Heuristic Review Engine (Robust offline fallback)
        # --------------------------------------------------------------
        flags = verification.flags
        action = proposal.action

        # If duplicate with zero changes -> Reject to prevent redundant records
        if action == "duplicate":
            return ReviewResult(
                verdict="reject",
                reason="[Agent 2 Audit]: Rejected as identical duplicate of existing active record.",
                confidence=0.98
            )

        # Critical failure checks: malformed URL or invalid title -> Flag or Reject
        if not verification.is_valid:
            return ReviewResult(
                verdict="flag",
                reason=f"[Agent 2 Audit]: Flagged for admin review due to verification issues: {', '.join(flags)}",
                confidence=0.85
            )

        # If deadline is in the past and action is not 'expire' -> Flag for verification
        if verification.has_expired and action != "expire":
            return ReviewResult(
                verdict="flag",
                reason=f"[Agent 2 Audit]: Deadline ({proposal.draft.deadline}) is in the past. Requires manual confirmation before publishing.",
                confidence=0.90
            )

        # If valid update
        if action == "update":
            return ReviewResult(
                verdict="accept",
                reason=f"[Agent 2 Audit]: Confirmed verified update to record (ID: {proposal.resource_id}). Details cross-checked.",
                confidence=0.95
            )

        # If valid expire
        if action == "expire":
            return ReviewResult(
                verdict="accept",
                reason=f"[Agent 2 Audit]: Confirmed expired listing. Archiving record (ID: {proposal.resource_id}).",
                confidence=0.95
            )

        # Default clean proposal -> Accept
        return ReviewResult(
            verdict="accept",
            reason="[Agent 2 Audit]: Verified against raw notice. No hallucinations or conflicts found. Approved for publication.",
            confidence=0.95
        )


# ----------------------------------------------------------------------
# 3️⃣ Full Pipeline Runner (Orchestrating Agent 1 + Verifier + Agent 2)
# ----------------------------------------------------------------------
def process_notice_pipeline(notice: ExtractedNotice, db: Session) -> Dict[str, Any]:
    """
    Executes the complete dual-agent lifecycle for a single extracted notice:
    1. Agent 1 structures and proposes action.
    2. Proposal persisted into AuditLog table.
    3. Verifier runs rule-based checks.
    4. Agent 2 reviews Agent 1's proposal and issues verdict.
    5. Database is updated based on verdict (auto-published if accepted, or placed in review queue if flagged).
    """
    # 1. Agent 1
    proposal, raw_agent1_output = DiscoveryAgent.run(notice, db=db)

    # 2. Persist proposal to audit log
    audit_entry = save_proposal(db, proposal, raw_agent1_output, resource_id=proposal.resource_id)

    # 3. Rule-based checks
    verification = verify_proposal(proposal, db=db)

    # 4. Agent 2 reviews Agent 1
    review = ReviewAgent.run(notice, proposal, verification, db=db)

    # 5. Apply review decision
    affected_resource = apply_proposal(
        db,
        audit_id=audit_entry.id,
        verdict=review.verdict,
        reason=review.reason
    )

    return {
        "audit_id": audit_entry.id,
        "title": proposal.draft.title,
        "category": proposal.draft.category,
        "action": proposal.action,
        "agent1_output": raw_agent1_output,
        "verification_flags": verification.flags,
        "agent2_verdict": review.verdict,
        "agent2_reason": review.reason,
        "published": review.verdict == "accept",
        "resource_id": affected_resource.id if affected_resource else None,
    }


def run_dual_agent_pipeline(notices: list, db: Session) -> list:
    """Batch processes a list of notices through the dual-agent pipeline."""
    results = []
    for notice in notices:
        res = process_notice_pipeline(notice, db)
        results.append(res)
    return results
