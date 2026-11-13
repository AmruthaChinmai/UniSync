"""
Shared domain constants and Enums for UniSync.
"""

RECORD_STATUS = ("current", "expired", "archived", "flagged")
PROPOSAL_ACTION = ("add_new", "update", "expire", "duplicate")
REVIEW_VERDICT = ("accept", "reject", "flag")
CATEGORIES = ("academic", "opportunity", "campus")

# UI Category mapping with display labels
CATEGORY_LABELS = {
    "academic": "Academics & Study Resources",
    "opportunity": "Opportunities (Jobs/Internships/Hackathons)",
    "campus": "Campus Updates & Notices",
}
