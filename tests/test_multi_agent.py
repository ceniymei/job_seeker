import pytest
from contextlib import contextmanager
from apps.crawler.agents.workflow import run_multi_agent_crawler

@pytest.fixture
def mock_db(monkeypatch):
    @contextmanager
    def mock_db_session():
        class MockCompany:
            def __init__(self):
                self.crawl_config = None
        class MockQuery:
            def filter(self, *args, **kwargs):
                return self
            def first(self):
                return None
        class MockSession:
            def query(self, *args, **kwargs):
                return MockQuery()
            def flush(self):
                pass
        yield MockSession()

    monkeypatch.setattr("apps.crawler.agents.workflow.get_db_session", mock_db_session)

def test_workflow_api_routing(mock_db, monkeypatch):
    # 1. Mock traffic interception and LLM routing decision node, deciding to call API Agent
    def mock_sniff(state):
        return {
            "homepage_html": "<html></html>",
            "crawl_config": {
                "is_paginated": True,
                "pagination_type": "api_direct",
                "url_template": "http://example.com/api/jobs?page={page}",
                "next_page_selector": None,
                "cookie_accept_selector": None
            },
            "assigned_agent": "api",
            "is_successful": False
        }
    monkeypatch.setattr("apps.crawler.agents.workflow.sniff_traffic_and_decision", mock_sniff)

    # 2. Mock API Agent logic, returning mock web pages
    def mock_run_api(state):
        return {
            "raw_urls": ["http://example.com/job/1", "http://example.com/job/2"],
            "is_successful": True,
            "history_record": {
                "agent": "api",
                "success": True,
                "pages_fetched": 1,
                "urls_collected": 2
            }
        }
    monkeypatch.setattr("apps.crawler.agents.workflow.run_api_agent", mock_run_api)

    # 3. Mock URL Recovery and physical recovery logic
    def mock_validate(state):
        # Final output of physical recovery
        return {
            "final_urls": ["http://example.com/job/1", "http://example.com/job/2"],
            "is_successful": True,
            "error_message": None
        }
    monkeypatch.setattr("apps.crawler.agents.workflow.validate_and_recover_urls", mock_validate)

    # Execute
    urls = run_multi_agent_crawler("MockCompany", "http://example.com", {})
    
    assert urls == ["http://example.com/job/1", "http://example.com/job/2"]


def test_workflow_playwright_routing(mock_db, monkeypatch):
    # 1. Mock traffic interception, deciding to call Playwright Agent
    def mock_sniff(state):
        return {
            "homepage_html": "<html></html>",
            "crawl_config": {
                "is_paginated": True,
                "pagination_type": "next_button",
                "url_template": None,
                "next_page_selector": "a.go-to-next",
                "cookie_accept_selector": None
            },
            "assigned_agent": "playwright",
            "is_successful": False
        }
    monkeypatch.setattr("apps.crawler.agents.workflow.sniff_traffic_and_decision", mock_sniff)

    # 2. Mock Playwright Agent logic
    def mock_run_playwright(state):
        return {
            "raw_urls": ["http://example.com/job/3", "http://example.com/job/4"],
            "is_successful": True,
            "history_record": {
                "agent": "playwright",
                "success": True,
                "pages_fetched": 2,
                "urls_collected": 2
            }
        }
    monkeypatch.setattr("apps.crawler.agents.workflow.run_playwright_agent", mock_run_playwright)

    # 3. Mock URL Recovery and physical recovery logic
    def mock_validate(state):
        return {
            "final_urls": ["http://example.com/job/3", "http://example.com/job/4"],
            "is_successful": True,
            "error_message": None
        }
    monkeypatch.setattr("apps.crawler.agents.workflow.validate_and_recover_urls", mock_validate)

    # Execute
    urls = run_multi_agent_crawler("MockCompany", "http://example.com", {})
    
    assert urls == ["http://example.com/job/3", "http://example.com/job/4"]


def test_workflow_self_healing_retry(mock_db, monkeypatch):
    """Test whether self-healing route rolls back and retries when the first validation fails, and returns the final result if successful on retry"""
    attempt_count = 0

    # 1. Mock traffic interception
    def mock_sniff(state):
        return {
            "homepage_html": "<html></html>",
            "crawl_config": {
                "is_paginated": True,
                "pagination_type": "api_direct",
                "url_template": "http://example.com/api/jobs",
                "next_page_selector": None,
                "cookie_accept_selector": None
            },
            "assigned_agent": "api",
            "is_successful": False
        }
    monkeypatch.setattr("apps.crawler.agents.workflow.sniff_traffic_and_decision", mock_sniff)

    # 2. Mock API Agent
    def mock_run_api(state):
        return {
            "raw_urls": ["http://example.com/job/5"],
            "is_successful": True
        }
    monkeypatch.setattr("apps.crawler.agents.workflow.run_api_agent", mock_run_api)

    # 3. Mock physical validation, returning failure on the first run to trigger Self-Healing, and success on the second run
    def mock_validate(state):
        nonlocal attempt_count
        if attempt_count == 0:
            attempt_count += 1
            return {
                "final_urls": ["http://example.com/job/5"],
                "is_successful": False,
                "error_message": "Low URL count"
            }
        else:
            return {
                "final_urls": ["http://example.com/job/5", "http://example.com/job/6"],
                "is_successful": True,
                "error_message": None
            }
    monkeypatch.setattr("apps.crawler.agents.workflow.validate_and_recover_urls", mock_validate)

    # Execute
    urls = run_multi_agent_crawler("MockCompanyRetry", "http://example.com", {})
    
    assert urls == ["http://example.com/job/5", "http://example.com/job/6"]
    assert attempt_count == 1
