"""
Scraper package initialization.
"""
from .extractor import (
    scrape_html,
    scrape_url,
    get_mock_campus_sources,
    extract_all_sources,
)

__all__ = [
    "scrape_html",
    "scrape_url",
    "get_mock_campus_sources",
    "extract_all_sources",
]
