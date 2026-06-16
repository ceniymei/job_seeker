import logging
from typing import Dict, Any, List
from shared.downloader import downloader
from apps.crawler.scraper import scraper

logger = logging.getLogger("job_seeker_crawler.agents.traditional_agent")

def run_traditional_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """Traditional URL template Sub-Agent logic, focusing on iterating over URL templates to extract job URLs"""
    logger.info(f"TraditionalHtmlAgent started for: {state['company_name']}")
    
    crawl_config = state.get("crawl_config") or {}
    homepage_url = state.get("homepage_url")
    company_config = state.get("company_config") or {}
    
    url_template = crawl_config.get("url_template")
    downloader_cfg = company_config.get("downloader", {})
    
    if not url_template:
        url_template = homepage_url
        max_pages = 1
        logger.info(f"TraditionalHtmlAgent: No URL template found in crawl config. Falling back to single-page crawl of homepage: {homepage_url}")
    else:
        max_pages = int(downloader_cfg.get("max_pages", 5))
    scroll_count = int(downloader_cfg.get("scroll_count", 0))
    scroll_delay = int(downloader_cfg.get("scroll_delay", 1500))
    
    raw_urls = []
    success_pages = 0
    
    for page_idx in range(1, max_pages + 1):
        try:
            page_url = url_template.replace("{page}", str(page_idx))
        except Exception:
            page_url = url_template
            
        logger.info(f"TraditionalHtmlAgent fetching page {page_idx}: {page_url}")
        
        try:
            p_html = downloader.fetch_html(
                page_url,
                scroll_count=scroll_count,
                scroll_delay=scroll_delay
            )
            
            if not p_html:
                logger.warning(f"TraditionalHtmlAgent got empty HTML for page {page_idx}. Stopping.")
                break
                
            logger.info(f"TraditionalHtmlAgent extracting job URLs from page {page_idx}...")
            p_urls = scraper.extract_job_urls(
                p_html,
                base_url=homepage_url,
                job_url_keywords=crawl_config.get("job_url_keywords"),
                job_url_pattern=crawl_config.get("job_url_pattern")
            )
            logger.info(f"Extracted {len(p_urls)} job URLs from page {page_idx}.")
            
            if not p_urls and raw_urls:
                logger.info("No more job URLs extracted from this page. Stopping.")
                break
                
            raw_urls.extend(p_urls)
            success_pages += 1
            
        except Exception as e:
            logger.error(f"TraditionalHtmlAgent failed on page {page_idx}: {str(e)}")
            return {
                "error_message": f"Traditional HTML request failed on page {page_idx}: {str(e)}",
                "is_successful": False
            }
            
    if success_pages == 0:
        return {
            "error_message": "Failed to fetch any template pages.",
            "is_successful": False
        }
        
    unique_urls = list(dict.fromkeys(raw_urls))
    logger.info(f"TraditionalHtmlAgent successfully completed. Collected {len(unique_urls)} unique URLs.")
    
    return {
        "raw_urls": unique_urls,
        "is_successful": True,
        "history_record": {
            "agent": "traditional",
            "success": True,
            "pages_fetched": success_pages,
            "urls_collected": len(unique_urls)
        }
    }
