# UniSync Data & Multi-Agent Interface Contract

This document defines the strict contracts between modules in the UniSync platform.

---

## 1. Domain Entities & Database Enums

### Record Status (`RECORD_STATUS`)
- `"current"`: Active, verified listing visible to students.
- `"expired"`: Deadline has passed; archived automatically.
- `"archived"`: Explicitly archived or superseded.
- `"flagged"`: Suspicious, pending human admin review.

### Proposal Action (`PROPOSAL_ACTION`)
- `"add_new"`: Brand new resource discovered from sources.
- `"update"`: Update to an existing resource (e.g. deadline extended, description modified).
- `"expire"`: Resource reached expiry or was rescinded.
- `"duplicate"`: Identified as duplicate of an existing record.

### Review Verdict (`REVIEW_VERDICT`)
- `"accept"`: Agent 2 or human confirms proposal is accurate. Automatically updates/inserts into `records`.
- `"reject"`: Proposal is noise, hallucinated, or incorrect. Discarded with logged reasoning.
- `"flag"`: Ambiguous, conflicting, or high-risk. Sent to Admin Review Queue.

---

## 2. Multi-Agent Pipeline Architecture

```
Raw Notice/Page -> [extractor.py] -> ExtractedNotice
                         │
                         ▼
           [Agent 1: Discovery Agent] 
                         │ (Draft + Proposed Action)
                         ▼
              [verifier.py: Rule Checks]
                         │ (Syntax, Expiry, URL flags)
                         ▼
           [Agent 2: Review / Audit Agent]
                         │ (Audits Agent 1 output)
                         ▼
        ┌────────────────┴────────────────┐
        ▼                                 ▼
   [ACCEPT]                        [FLAG / REJECT]
Written to `records`             Written to `proposals`
Visible to Students               Admin Review Queue
```

### Agent 1: Discovery Agent
- **Input:** `ExtractedNotice` (raw title, raw date string, raw description, source URL).
- **Task:** Formats messy date to ISO `YYYY-MM-DD`, categorizes into `academic | opportunity | campus`, queries DB for existing record matches, proposes `add_new`, `update`, `expire`, or `duplicate`.
- **Output:** `Proposal` (containing `RecordDraft` + proposed action + reason).

### Verifier: Rule-based Filter
- **Input:** `Proposal`.
- **Task:** Deterministic validations (regex check on URL, valid date parsing, past deadline detection, string similarity duplicate threshold).
- **Output:** `VerificationReport` with list of warning/info flags.

### Agent 2: Review Agent (The Assisting / Supervising Agent)
- **Input:** Raw source text + Agent 1's Proposal + Existing DB record (if match found) + Verifier flags.
- **Task:** 
  - Cross-references Agent 1's claims against raw text (catches hallucinations).
  - Confirms whether an update is genuine or duplicate.
  - Returns `ReviewResult` with `verdict: "accept" | "reject" | "flag"` and `reason`.
