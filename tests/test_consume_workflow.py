import pytest
from contextlib import contextmanager
from apps.crawler.agents.consume_workflow import run_consume_workflow

@pytest.fixture
def mock_db(monkeypatch):
    @contextmanager
    def mock_db_session():
        class MockJob:
            def __init__(self):
                self.id = 1
                self.job_url = "http://example.com/job/1"
                self.title = "Unknown"
                self.detail_status = "pending"
                self.status = "active"
                self.location_standard = None
                self.salary_standard = None
        class MockQuery:
            def filter(self, *args, **kwargs):
                return self
            def first(self):
                return MockJob()
        class MockSession:
            def query(self, *args, **kwargs):
                return MockQuery()
            def flush(self):
                pass
            def add(self, *args, **kwargs):
                pass
            def commit(self):
                pass
            def rollback(self):
                pass
            def close(self):
                pass
        yield MockSession()

    monkeypatch.setattr("apps.crawler.agents.consume_workflow.get_db_session", mock_db_session)
    monkeypatch.setattr("apps.crawler.detail_consumer.get_db_session", mock_db_session)

def test_consume_workflow_404_blocking(mock_db, monkeypatch):
    """Test that 404 pages and expired pages are blocked early"""
    
    # 1. Mock the fetched HTML to be a 404 page
    monkeypatch.setattr(
        "apps.crawler.agents.consume_workflow.downloader.fetch_html",
        lambda url: "<html><head><title>404 - Page Not Found</title></head><body>This page does not exist. " + ("x" * 1000) + "</body></html>"
    )
    
    # 2. Execute
    result = run_consume_workflow(1, "http://example.com/job/1")
    
    # 3. Assert that the pre-validation correctly identifies the page as invalid, bypasses LLM extraction, and exits with a failed status
    assert result["is_valid_page"] is False
    assert result["page_type"] == "404"
    assert result["status"] == "failed"
    assert result["error_message"] == "Page returned 404 (Not Found)"


def test_consume_workflow_quality_gate_retry(mock_db, monkeypatch):
    """Test retry triggered by failing rational quality checks, and final failure marking"""
    attempts_called = 0

    # 1. Mock the page as valid
    monkeypatch.setattr(
        "apps.crawler.agents.consume_workflow.downloader.fetch_html",
        lambda url: "<html><body>Active Job Description context here... " + ("x" * 1000) + "</body></html>"
    )
    
    # 2. Mock the first extraction returning 'Unknown Position' as Title, triggering a second extraction attempt
    def mock_extract(html, url):
        nonlocal attempts_called
        attempts_called += 1
        if attempts_called == 1:
            return {"title": "Unknown Position", "description": "Too short"}
        else:
            return {"title": "Software Engineer", "description": "This description is long enough to pass the word count validation gate."}
            
    monkeypatch.setattr("apps.crawler.agents.consume_workflow.scraper.extract_job_details", mock_extract)
    
    # 3. Mock the local LLM's standardized JSON output to avoid actual LLM network calls
    class MockResponse:
        def __init__(self):
            self.content = """
            {
                "country": "USA",
                "city": "Atlanta",
                "state": "GA",
                "is_remote": false,
                "min_amount": 90000,
                "max_amount": 110000,
                "currency": "USD",
                "period": "yearly"
            }
            """
    
    class MockLLM:
        def invoke(self, prompt):
            return MockResponse()
            
    monkeypatch.setattr("apps.crawler.agents.consume_workflow.get_llm", lambda: MockLLM())

    # Execute
    result = run_consume_workflow(1, "http://example.com/job/1")
    
    # Assert that it went through a retry and successfully passed the quality gate on the second attempt
    assert attempts_called == 2
    assert result["is_extraction_valid"] is True
    assert result["status"] == "completed"


def test_consume_workflow_normalization(mock_db, monkeypatch):
    """Test that the normalization node correctly converts Location (including Remote='Unknown') and Salary"""
    
    # 1. Mock page fetch and extraction
    monkeypatch.setattr(
        "apps.crawler.agents.consume_workflow.downloader.fetch_html",
        lambda url: "<html><body>Valid page content... " + ("x" * 1000) + "</body></html>"
    )
    monkeypatch.setattr(
        "apps.crawler.agents.consume_workflow.scraper.extract_job_details",
        lambda html, url: {"title": "Product Manager", "location": "Shanghai", "salary": "$50/hour", "description": "This is a valid PM position details and requirements text."}
    )
    
    # 2. Mock the local LLM's standardized JSON output
    class MockResponse:
        def __init__(self):
            # is_remote is Unknown
            self.content = """
            {
                "country": "China",
                "city": "Shanghai",
                "state": "Shanghai",
                "is_remote": "Unknown",
                "min_amount": 50,
                "max_amount": 50,
                "currency": "USD",
                "period": "hourly"
            }
            """
    
    class MockLLM:
        def invoke(self, prompt):
            return MockResponse()
            
    monkeypatch.setattr("apps.crawler.agents.consume_workflow.get_llm", lambda: MockLLM())

    # Execute
    result = run_consume_workflow(1, "http://example.com/job/1")
    
    # Assert that the standardized data structure is populated correctly
    standard = result["standardized_details"]
    assert standard["location"]["country"] == "China"
    assert standard["location"]["city"] == "Shanghai"
    assert standard["location"]["is_remote"] == "Unknown"
    assert standard["salary"]["min_amount"] == 50
    assert standard["salary"]["currency"] == "USD"
    assert standard["salary"]["period"] == "hourly"
    assert result["status"] == "completed"
