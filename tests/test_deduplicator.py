import os
import pytest

# Set environment variable to make config load in-memory SQLite database for testing without affecting real data
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from shared.database import Base, engine, get_db_session
from shared.models import Company, Job, CrawlLog
from shared.deduplicator import deduplicator

@pytest.fixture(autouse=True)
def setup_database():
    """Initialize table schema before each test case and clean up afterwards"""
    # Force bind engine to in-memory SQLite and create tables
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_calculate_text_hash():
    # Test text hash calculation of ordinary HTML after stripping script and style tags
    html_with_noise = """
    <html>
        <head>
            <style>body { color: red; }</style>
            <script>console.log("hello");</script>
        </head>
        <body>
            <h1>Python Developer</h1>
            <p>We are hiring!</p>
        </body>
    </html>
    """
    
    html_without_noise = """
    <html>
        <body>
            <h1>Python Developer</h1>
            <p>We are hiring!</p>
        </body>
    </html>
    """
    
    hash1 = deduplicator.calculate_text_hash(html_with_noise)
    hash2 = deduplicator.calculate_text_hash(html_without_noise)
    
    # The text content of both HTML files is identical, so the calculated hashes should be the same
    assert hash1 != ""
    assert hash1 == hash2

def test_is_list_page_unchanged():
    url = "https://example.com/jobs"
    html_v1 = "<div>Job List 1</div>"
    html_v2 = "<div>Job List 2</div>"
    
    # Initially no crawl records exist, should determine as False (changed or no record)
    assert deduplicator.is_list_page_unchanged(url, html_v1) is False
    
    # Record a successful crawl log
    deduplicator.log_crawl(url, html_v1, "success")
    
    # Compare with identical HTML again, should return True (not updated, skip)
    assert deduplicator.is_list_page_unchanged(url, html_v1) is True
    
    # Compare with new HTML, should return False (updated)
    assert deduplicator.is_list_page_unchanged(url, html_v2) is False

def test_is_job_url_exists():
    job_url = "https://example.com/jobs/123"
    
    # Database is empty, should return False
    assert deduplicator.is_job_url_exists(job_url) is False
    
    # Write a job posting to the database
    with get_db_session() as session:
        # Requires a company record first because Job depends on Company
        company = Company(name="TestCompany", homepage_url="https://example.com")
        session.add(company)
        session.flush()
        
        job = Job(
            company_id=company.id,
            title="Software Engineer",
            location="Beijing",
            job_url=job_url,
            status="active"
        )
        session.add(job)
    
    # Now the job link should be determined as existing, returning True
    assert deduplicator.is_job_url_exists(job_url) is True
