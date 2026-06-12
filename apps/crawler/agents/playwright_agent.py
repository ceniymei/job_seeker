import logging
from typing import Dict, Any, List
from shared.downloader import downloader
from apps.crawler.scraper import scraper

logger = logging.getLogger("job_seeker_crawler.agents.playwright_agent")

def run_playwright_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """Browser simulation Sub-Agent logic, focusing on utilizing Playwright for dynamic pagination click and crawl"""
    logger.info(f"PlaywrightInteractiveAgent started for: {state['company_name']}")
    
    crawl_config = state.get("crawl_config") or {}
    homepage_url = state.get("homepage_url")
    company_config = state.get("company_config") or {}
    
    next_sel = crawl_config.get("next_page_selector")
    cookie_sel = crawl_config.get("cookie_accept_selector")
    
    if not next_sel:
        return {
            "error_message": "No next page selector found in crawl config.",
            "is_successful": False
        }
        
    downloader_cfg = company_config.get("downloader", {})
    max_pages = int(downloader_cfg.get("max_pages", 5))
    page_delay = int(downloader_cfg.get("page_delay", 2000))
    scroll_count = int(downloader_cfg.get("scroll_count", 0))
    scroll_delay = int(downloader_cfg.get("scroll_delay", 1500))
    
    try:
        logger.info(f"PlaywrightInteractiveAgent calling downloader.fetch_pages_html (max_pages={max_pages})")
        pages_html = downloader.fetch_pages_html(
            homepage_url,
            next_page_selector=next_sel,
            max_pages=max_pages,
            page_delay=page_delay,
            cookie_accept_selector=cookie_sel,
            scroll_count=scroll_count,
            scroll_delay=scroll_delay
        )
        
        if not pages_html:
            return {
                "error_message": "Fetched pages list is empty.",
                "is_successful": False
            }
            
        logger.info(f"PlaywrightInteractiveAgent successfully fetched {len(pages_html)} pages HTML.")
        
        raw_urls = []
        for idx, p_html in enumerate(pages_html):
            logger.info(f"PlaywrightInteractiveAgent extracting job URLs from page {idx + 1}/{len(pages_html)}...")
            p_urls = scraper.extract_job_urls(
                p_html,
                base_url=homepage_url,
                job_url_keywords=crawl_config.get("job_url_keywords"),
                job_url_pattern=crawl_config.get("job_url_pattern")
            )
            logger.info(f"Extracted {len(p_urls)} job URLs from page {idx + 1}.")
            
            if not p_urls and raw_urls:
                logger.info("No more job URLs extracted from this page. Stopping.")
                break
                
            raw_urls.extend(p_urls)
            
        unique_urls = list(dict.fromkeys(raw_urls))
        logger.info(f"PlaywrightInteractiveAgent successfully completed. Collected {len(unique_urls)} unique URLs.")
        
        return {
            "raw_urls": unique_urls,
            "is_successful": True,
            "history_record": {
                "agent": "playwright",
                "success": True,
                "pages_fetched": len(pages_html),
                "urls_collected": len(unique_urls)
            }
        }
        
    except Exception as e:
        logger.error(f"PlaywrightInteractiveAgent failed: {str(e)}")
        return {
            "error_message": f"Playwright crawling failed: {str(e)}",
            "is_successful": False
        }
