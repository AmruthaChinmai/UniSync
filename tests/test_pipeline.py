"""
test_pipeline.py - Comprehensive Unit & Integration Tests for UniSync.
Tests:
1. Scraper extraction using BeautifulSoup
2. Verifier rule-based checks
3. Agent 1 Discovery & structuring
4. Agent 2 Review & verdict auditing
5. Database CRUD & audit persistence
6. Flask web routes and APIs
"""
import unittest
from datetime import date, datetime, timedelta
from app.shared.models import ExtractedNotice, RecordDraft, Proposal
from app.scraper.extractor import scrape_html, get_mock_campus_sources
from app.verifier.verifier import validate_url, parse_date_safely, verify_raw_notice, verify_proposal
from app.ai.ai_agent import DiscoveryAgent, ReviewAgent, process_notice_pipeline
from app.db.db import init_db, SessionLocal, Resource, AuditLog, apply_proposal, get_active_resources
from app.web.app import create_app


class UniSyncPipelineTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.db = SessionLocal()
        cls.app = create_app()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        # Clean up any leftover test records before each test to guarantee idempotency
        test_titles = [
            "Unique Tech Competition 2026",
            "Duplicate Test Hackathon 2026",
            "Google Software Engineering Intern 2026",
            "Machine Learning Research Seminar",
            "Outdated Grievance Form",
        ]
        self.db.query(Resource).filter(Resource.title.in_(test_titles)).delete(synchronize_session=False)
        for t in test_titles:
            self.db.query(AuditLog).filter(AuditLog.draft_json.like(f"%{t}%")).delete(synchronize_session=False)
        self.db.commit()

    def tearDown(self):
        # Clean up after test as well
        self.setUp()

    # ------------------------------------------------------------------
    # 1. Scraper / Extractor Tests
    # ------------------------------------------------------------------
    def test_scraper_extracts_from_html(self):
        html = """
        <table>
            <tr>
                <td>2026-12-15</td>
                <td><a href="/notices/test-exam">Annual Semester Exam Circular</a></td>
                <td>Details regarding hall ticket download.</td>
            </tr>
        </table>
        """
        notices = scrape_html(html, base_url="https://hub.rgukt.ac.in", source_name="Test Source")
        self.assertGreaterEqual(len(notices), 1)
        self.assertIn("Annual Semester Exam", notices[0].title)
        self.assertEqual(notices[0].url, "https://hub.rgukt.ac.in/notices/test-exam")

    # ------------------------------------------------------------------
    # 2. Verifier Tests
    # ------------------------------------------------------------------
    def test_verifier_url_validation(self):
        self.assertTrue(validate_url("https://hub.rgukt.ac.in/notice"))
        self.assertFalse(validate_url("not-a-valid-url"))
        self.assertFalse(validate_url(""))

    def test_verifier_expiry_check(self):
        past_date = date.today() - timedelta(days=10)
        notice = ExtractedNotice(
            title="Old Past Notice",
            raw_date=past_date.isoformat(),
            url="https://rgukt.ac.in/old",
            description="Notice whose deadline has passed."
        )
        res = verify_raw_notice(notice)
        self.assertTrue(res.has_expired)
        self.assertTrue(any("past" in f.lower() for f in res.flags))

    def test_verifier_suspicious_filter(self):
        notice = ExtractedNotice(
            title="Earn Free Money",
            url="https://scam.example.com",
            description="Click here to claim free lottery job without interview."
        )
        res = verify_raw_notice(notice)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("suspicious" in f.lower() for f in res.flags))

    # ------------------------------------------------------------------
    # 3. Dual-Agent Interaction Tests (Agent 1 + Agent 2)
    # ------------------------------------------------------------------
    def test_agent1_structures_notice(self):
        notice = ExtractedNotice(
            title="Google Software Engineering Intern 2026",
            raw_date="2026-11-30",
            description="Summer internship opening for 3rd year B.Tech students. Stipend provided.",
            url="https://careers.google.com/jobs/intern-2026"
        )
        proposal, raw_log = DiscoveryAgent.run(notice, db=self.db)
        self.assertEqual(proposal.draft.category, "opportunity")
        self.assertEqual(proposal.draft.deadline, date(2026, 11, 30))
        self.assertEqual(proposal.action, "add_new")

    def test_agent2_reviews_and_accepts_clean_proposal(self):
        notice = ExtractedNotice(
            title="Machine Learning Research Seminar",
            raw_date="2026-12-05",
            description="Seminar on Transformers and Multi-Agent AI Systems.",
            url="https://rgukt.ac.in/seminars/ml-2026"
        )
        proposal, raw_log = DiscoveryAgent.run(notice, db=self.db)
        verification = verify_proposal(proposal, db=self.db)
        review = ReviewAgent.run(notice, proposal, verification, db=self.db)
        self.assertEqual(review.verdict, "accept")
        self.assertIn("verified", review.reason.lower())

    def test_agent2_flags_expired_or_dubious_proposal(self):
        past_date = date.today() - timedelta(days=30)
        notice = ExtractedNotice(
            title="Outdated Grievance Form",
            raw_date=past_date.isoformat(),
            description="Deadlines already closed last month.",
            url="https://hub.rgukt.ac.in/past"
        )
        proposal, raw_log = DiscoveryAgent.run(notice, db=self.db)
        # Force add_new proposal to test Agent 2 catching the contradiction
        proposal.action = "add_new"
        verification = verify_proposal(proposal, db=self.db)
        review = ReviewAgent.run(notice, proposal, verification, db=self.db)
        self.assertEqual(review.verdict, "flag")

    # ------------------------------------------------------------------
    # 4. Full Pipeline & DB Persistence Tests
    # ------------------------------------------------------------------
    def test_end_to_end_pipeline_execution(self):
        notice = ExtractedNotice(
            title="Unique Tech Competition 2026",
            raw_date="2026-12-25",
            description="Coding hackathon with certificate and cash prizes.",
            url="https://rgukt.ac.in/events/unique-comp-2026"
        )
        res = process_notice_pipeline(notice, self.db)
        self.assertIn("audit_id", res)
        self.assertEqual(res["agent2_verdict"], "accept")
        self.assertTrue(res["published"])

        # Check in DB
        saved = self.db.query(Resource).filter(Resource.title == "Unique Tech Competition 2026").first()
        self.assertIsNotNone(saved)
        self.assertEqual(saved.category, "opportunity")

    def test_duplicate_notice_is_rejected_by_agent2(self):
        """Verifies Slide 11: Re-running identical notice is detected as duplicate and rejected by Agent 2."""
        notice = ExtractedNotice(
            title="Duplicate Test Hackathon 2026",
            raw_date="2026-12-30",
            description="First submission.",
            url="https://rgukt.ac.in/events/dup-test"
        )
        # First submission -> Agent 2 accepts & publishes
        res1 = process_notice_pipeline(notice, self.db)
        self.assertEqual(res1["agent2_verdict"], "accept")
        self.assertTrue(res1["published"])

        # Second submission -> Agent 1 identifies duplicate, Agent 2 audits & rejects
        res2 = process_notice_pipeline(notice, self.db)
        self.assertEqual(res2["action"], "duplicate")
        self.assertEqual(res2["agent2_verdict"], "reject")
        self.assertIn("duplicate", res2["agent2_reason"].lower())

    # ------------------------------------------------------------------
    # 5. Web Layer Tests
    # ------------------------------------------------------------------
    def test_student_portal_route(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"UniSync", resp.data)

    def test_admin_portal_route(self):
        resp = self.client.get("/admin")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Admin Review", resp.data)

    def test_api_resources(self):
        resp = self.client.get("/api/resources")
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertEqual(json_data["status"], "success")
        self.assertGreater(json_data["count"], 0)


if __name__ == "__main__":
    unittest.main()
