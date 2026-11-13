"""
Pydantic schemas used across Scraper, Agents, Verifier, Database, and Web layers.
Compatible with both Pydantic v1 and v2 methods.
"""
from datetime import date
from typing import Optional, List, Literal, Any, Dict
from pydantic import BaseModel, Field

ReviewVerdict = Literal["accept", "reject", "flag"]
ProposalAction = Literal["add_new", "update", "expire", "duplicate"]
RecordStatus = Literal["current", "expired", "archived", "flagged"]


class ExtractedNotice(BaseModel):
    """Raw scraped notice before AI structuring."""
    title: str
    raw_date: Optional[str] = None
    description: Optional[str] = None
    url: str
    source: str = "Web Scraper"


class RecordDraft(BaseModel):
    """Structured resource ready for persistence or comparison."""
    title: str
    category: str = "campus"
    description: Optional[str] = None
    url: str
    deadline: Optional[date] = None
    status: Optional[str] = "current"

    def json(self, *args, **kwargs) -> str:
        return self.model_dump_json(*args, **kwargs)

    def dict(self, *args, **kwargs) -> Dict[str, Any]:
        return self.model_dump(*args, **kwargs)


class Proposal(BaseModel):
    """Agent 1's structured proposal to add, update, or archive a record."""
    draft: RecordDraft
    action: str = "add_new"
    resource_id: Optional[int] = None
    reason: Optional[str] = None

    def json(self, *args, **kwargs) -> str:
        return self.model_dump_json(*args, **kwargs)

    def dict(self, *args, **kwargs) -> Dict[str, Any]:
        return self.model_dump(*args, **kwargs)

    @classmethod
    def parse_raw(cls, b: str, **kwargs) -> "Proposal":
        try:
            return cls.model_validate_json(b, **kwargs)
        except Exception:
            # If b was serialized from RecordDraft directly
            draft = RecordDraft.model_validate_json(b, **kwargs)
            return cls(draft=draft, action="add_new")


class VerificationResult(BaseModel):
    """Output of rule-based deterministic verifier."""
    is_valid: bool = True
    flags: List[str] = Field(default_factory=list)
    has_expired: bool = False
    is_duplicate: bool = False
    normalized_deadline: Optional[date] = None


class ReviewResult(BaseModel):
    """Verdict produced by Agent 2 (The Review Agent)."""
    verdict: ReviewVerdict = "accept"
    reason: Optional[str] = None
    confidence: float = 1.0
