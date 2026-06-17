import pytest
from apps.crawler.strategies import (
    clean_url_template,
    CrawlerStrategyFactory,
    LLMCrawlerStrategy,
    SinglePagePagination,
    UrlTemplatePagination,
    PlaywrightClickPagination,
    LLMJobUrlExtractor,
    RuleBasedJobUrlExtractor
)

def test_clean_url_template():
    assert clean_url_template(None, "http://example.com") is None
    assert clean_url_template("http://other.com/jobs", "http://example.com") == "http://other.com/jobs"
    assert clean_url_template(".../jobs?page={page}", "http://example.com") == "http://example.com/jobs?page={page}"
    assert clean_url_template("/jobs?page={page}", "http://example.com") == "http://example.com/jobs?page={page}"


def test_strategy_factory():
    strategy = CrawlerStrategyFactory.get_strategy("Some Random Company")
    assert isinstance(strategy, LLMCrawlerStrategy)


def test_job_extractors_instantiation():
    llm_extractor = LLMJobUrlExtractor()
    assert hasattr(llm_extractor, "extract")
    
    rule_extractor = RuleBasedJobUrlExtractor(selector="a.job-link")
    assert rule_extractor.selector == "a.job-link"
    assert hasattr(rule_extractor, "extract")


def test_pagination_strategies_instantiation():
    single = SinglePagePagination("<html></html>")
    assert single.homepage_html == "<html></html>"
    assert hasattr(single, "fetch")
    
    tmpl = UrlTemplatePagination("<html></html>")
    assert tmpl.homepage_html == "<html></html>"
    assert hasattr(tmpl, "fetch")
    
    click = PlaywrightClickPagination("<html></html>")
    assert click.homepage_html == "<html></html>"
    assert hasattr(click, "fetch")


def test_url_recovery_via_mock_llm(monkeypatch):
    from apps.crawler.scraper import scraper
    from scrapegraphai.graphs import SmartScraperGraph

    # 1. Construct mock HTML containing jobs with correct href values
    mock_html = """
    <html>
        <body>
            <a href="/job/23465485/senior-brand-manager-netherlands-rotterdam-nl/">Brand Manager</a>
            <a href="/job/12345/director-operations/">Director</a>
        </body>
    </html>
    """

    # 2. Simulate LLM extracting only partial URL lists missing the /job/ID part
    mock_llm_result = {
        "job_urls": [
            "https://careers.beveragecorp.example.com/senior-brand-manager-netherlands-rotterdam-nl/",
            "https://careers.beveragecorp.example.com/director-operations/"
        ]
    }

    # 3. Mock SmartScraperGraph.run to return the partial data
    monkeypatch.setattr(SmartScraperGraph, "run", lambda self: mock_llm_result)
    # Also mock _is_llm_configured to prevent test failure due to missing API key
    monkeypatch.setattr(scraper, "_is_llm_configured", lambda: True)

    # 4. Perform URL extraction and recovery
    base_url = "https://careers.beveragecorp.example.com/"
    recovered_urls = scraper.extract_job_urls(mock_html, base_url=base_url)

    # 5. Assert all extracted URLs are correctly recovered with /job/ID formats
    assert "https://careers.beveragecorp.example.com/job/23465485/senior-brand-manager-netherlands-rotterdam-nl/" in recovered_urls
    assert "https://careers.beveragecorp.example.com/job/12345/director-operations/" in recovered_urls
    assert len(recovered_urls) == 2


def test_fruitsystems_details_url_heuristic_extraction():
    from apps.crawler.scraper import scraper

    # 1. Construct mock HTML containing typical FruitSystems /details/ job paths
    mock_html = """
    <html>
        <body>
            <a href="https://jobs.fruitsystems.example.com/en-sg/details/200596262-3278/site-reliability-engineer?team=CORSV">SRE</a>
            <a href="/en-sg/details/200338277-3278/channel-fulfillment-analyst-12-months-contract?team=OPMFG">Analyst</a>
            <a href="https://jobs.fruitsystems.example.com/en-sg/details/111111111-3278/some-job">Other Job</a>
        </body>
    </html>
    """

    # 2. Perform URL extraction; it should hit the heuristic matcher directly (>= 3 matching URLs), bypassing LLM operations
    base_url = "https://jobs.fruitsystems.example.com/"
    extracted_urls = scraper.extract_job_urls(mock_html, base_url=base_url)

    # 3. Verify that the extracted links are the actual absolute addresses and not LLM-hallucinated as /job/12345/
    assert "https://jobs.fruitsystems.example.com/en-sg/details/200596262-3278/site-reliability-engineer?team=CORSV" in extracted_urls
    assert "https://jobs.fruitsystems.example.com/en-sg/details/200338277-3278/channel-fulfillment-analyst-12-months-contract?team=OPMFG" in extracted_urls
    assert "https://jobs.fruitsystems.example.com/en-sg/details/111111111-3278/some-job" in extracted_urls
    assert len(extracted_urls) == 3
