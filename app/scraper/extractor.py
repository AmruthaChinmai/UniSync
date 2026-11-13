"""
extractor.py - Extracts notice, resource, and opportunity details from web pages using BeautifulSoup.
Supports live URLs, raw HTML, and mock campus notice board simulators.
"""
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from app.shared.models import ExtractedNotice

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) UniSync-Bot/1.0 (+https://unisync.rgukt.ac.in)"
}


def scrape_html(html_content: str, base_url: str = "https://hub.rgukt.ac.in", source_name: str = "Web Page") -> List[ExtractedNotice]:
    """
    Parses HTML content using BeautifulSoup and extracts notices, opportunities, or circulars.
    Looks for table rows, list items, or article/notice containers.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    notices: List[ExtractedNotice] = []

    # 1. Check for table rows (common for college notice boards)
    rows = soup.find_all("tr")
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            link = row.find("a")
            text = row.get_text(separator=" ", strip=True)
            if link and len(text) > 10:
                title = link.get_text(strip=True) or text[:80]
                href = link.get("href", "")
                full_url = urljoin(base_url, href) if href else base_url
                
                # Try to extract date from the row
                date_match = re.search(r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})|([A-Za-z]+\s+\d{1,2},\s*\d{4})", text)
                raw_date = date_match.group(0) if date_match else None

                notices.append(ExtractedNotice(
                    title=title,
                    raw_date=raw_date,
                    description=text,
                    url=full_url,
                    source=source_name
                ))

    # 2. Check for notice-card or list-item containers
    containers = soup.find_all(class_=re.compile(r"(notice|circular|card|item|post|opportunity)", re.I))
    for c in containers:
        link = c.find("a")
        title_tag = c.find(["h2", "h3", "h4", "h5", "strong"]) or link
        if title_tag:
            title = title_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            href = link.get("href", "") if link else ""
            full_url = urljoin(base_url, href) if href else base_url
            desc = c.get_text(separator=" ", strip=True)
            date_match = re.search(r"(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})|([A-Za-z]+\s+\d{1,2},\s*\d{4})|(\d{4}-\d{2}-\d{2})", desc)
            raw_date = date_match.group(0) if date_match else None

            notices.append(ExtractedNotice(
                title=title,
                raw_date=raw_date,
                description=desc[:500],
                url=full_url,
                source=source_name
            ))

    # If generic parsing didn't catch structured blocks, look for all anchor links with substantive text
    if not notices:
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if len(text) > 15:
                full_url = urljoin(base_url, a["href"])
                notices.append(ExtractedNotice(
                    title=text,
                    raw_date=None,
                    description=text,
                    url=full_url,
                    source=source_name
                ))

    # De-duplicate by title
    seen = set()
    deduped = []
    for n in notices:
        if n.title.lower() not in seen:
            seen.add(n.title.lower())
            deduped.append(n)

    return deduped


def scrape_url(url: str, source_name: Optional[str] = None) -> List[ExtractedNotice]:
    """
    Fetches a live URL over HTTP and parses notices using BeautifulSoup.
    """
    source_label = source_name or url
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return scrape_html(resp.text, base_url=url, source_name=source_label)
    except Exception as exc:
        print(f"⚠️ [extractor] Failed to scrape {url}: {exc}")
        return []


def get_mock_campus_sources() -> List[Dict[str, Any]]:
    """
    Pre-configured mock pages representing typical campus portals:
    1. RGUKT Basar Examination & Academic Portal
    2. Training & Placement Cell Drive Announcements
    3. Tech Fest & Hackathon Hub
    """
    return [
        {
            "name": "RGUKT Examination Branch",
            "url": "https://hub.rgukt.ac.in/academic-notices",
            "html": """
            <html>
                <body>
                    <h2>RGUKT Basar - Official Academic Notices</h2>
                    <table class="notice-table">
                        <tr>
                            <td>12-11-2026</td>
                            <td><a href="/notices/remedial-exam-registration-2026">B.Tech Remedial Examination Registration & Fee Payment Schedule</a></td>
                            <td>Last date for registration without fine: 28-11-2026. Hall tickets available on Hub.</td>
                        </tr>
                        <tr>
                            <td>10-11-2026</td>
                            <td><a href="/notices/ai-ml-workshop-registration">3-Day Hands-on Workshop on Generative AI & Deep Learning</a></td>
                            <td>Conducted by CSE Dept. Deadline for registration: 24-11-2026. Limited to 120 seats.</td>
                        </tr>
                    </table>
                </body>
            </html>
            """
        },
        {
            "name": "RGUKT Training & Placement Cell",
            "url": "https://rgukt.ac.in/placements",
            "html": """
            <html>
                <body>
                    <div class="opportunity-card">
                        <h3><a href="https://careers.microsoft.com/students/2026-intern">Microsoft Software Engineering Summer Internship 2027</a></h3>
                        <p class="deadline">Application deadline: 2026-12-01</p>
                        <p>Eligibility: B.Tech 3rd year CSE/ECE. Stipend: 1,00,000 INR/month. Location: Hyderabad/Bangalore.</p>
                    </div>
                    <div class="opportunity-card">
                        <h3><a href="https://internshala.com/internship/web-dev-rgukt">Front-End Developer Internship at TechWave Labs</a></h3>
                        <p class="deadline">Deadline: 2026-11-22</p>
                        <p>Remote internship. Requires React, HTML, and CSS skills. 20,000 INR/month stipend.</p>
                    </div>
                </body>
            </html>
            """
        },
        {
            "name": "Hackathons & Opportunities Hub",
            "url": "https://hackathons.dev/rgukt",
            "html": """
            <html>
                <body>
                    <div class="notice-card">
                        <h4><a href="https://devpost.com/hackathons/basar-hack-2026">RGUKT Annual BasarHack 2026 - National Collegiate Hackathon</a></h4>
                        <p>Prize pool: 2,50,000 INR. Themes: EdTech, Rural Healthcare, Green Energy. Submission closes on 2026-12-15.</p>
                    </div>
                </body>
            </html>
            """
        }
    ]


def extract_all_sources(custom_sources: Optional[List[Dict[str, Any]]] = None) -> List[ExtractedNotice]:
    """
    Runs extraction over the provided or mock campus sources.
    """
    sources = custom_sources or get_mock_campus_sources()
    extracted_all: List[ExtractedNotice] = []

    for src in sources:
        if "html" in src:
            notices = scrape_html(src["html"], base_url=src.get("url", ""), source_name=src.get("name", "Mock Source"))
        elif "url" in src:
            notices = scrape_url(src["url"], source_name=src.get("name", src["url"]))
        else:
            continue
        extracted_all.extend(notices)

    return extracted_all
