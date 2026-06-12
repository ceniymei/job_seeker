import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from sqlalchemy.orm import Session

from shared.config import config
from shared.downloader import downloader
from shared.models import Company
from apps.crawler.scraper import scraper

logger = logging.getLogger("job_seeker_crawler.strategies")

# Helper function to clean URL template
def clean_url_template(template: str, base_url: str) -> Optional[str]:
    if not template:
        return None
    template = template.strip()
    if template.startswith("..."):
        template = template.lstrip(".").lstrip("/")
    if template.startswith("http://") or template.startswith("https://"):
        return template
    return urljoin(base_url, template)


# ==========================================
# 1. Job URL Extractor Strategy Standard
# ==========================================

class BaseJobUrlExtractor(ABC):
    """Strategy interface for extracting job details URLs"""

    @abstractmethod
    def extract(self, html_content: str, base_url: str = None) -> List[str]:
        """Parse all job details URLs from given HTML content"""
        pass


class LLMJobUrlExtractor(BaseJobUrlExtractor):
    """Intelligent extraction strategy based on ScrapegraphAI LLM"""

    def extract(self, html_content: str, base_url: str = None) -> List[str]:
        return scraper.extract_job_urls(html_content, base_url=base_url)


class RuleBasedJobUrlExtractor(BaseJobUrlExtractor):
    """Rule-based matching extraction strategy using CSS selectors or regex (left for future extension)"""

    def __init__(self, selector: str):
        self.selector = selector

    def extract(self, html_content: str, base_url: str = None) -> List[str]:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")
            elements = soup.select(self.selector)
            urls = []
            for el in elements:
                href = el.get("href")
                if href:
                    urls.append(href)
            return urls
        except Exception as e:
            logger.error(f"RuleBasedJobUrlExtractor failed: {str(e)}")
            return []


# ==========================================
# 2. Pagination Strategy Standard
# ==========================================

class BasePaginationStrategy(ABC):
    """Multi-page list crawling strategy interface"""

    @abstractmethod
    def fetch(self, homepage_url: str, crawl_config: Dict[str, Any], company_config: Dict[str, Any]) -> List[str]:
        """Crawl and return a list of multi-page HTML contents"""
        pass


class SinglePagePagination(BasePaginationStrategy):
    """Single page / no-pagination list crawling"""

    def __init__(self, homepage_html: str):
        self.homepage_html = homepage_html

    def fetch(self, homepage_url: str, crawl_config: Dict[str, Any], company_config: Dict[str, Any]) -> List[str]:
        logger.info("Processing as single page.")
        return [self.homepage_html]


class UrlTemplatePagination(BasePaginationStrategy):
    """Url-template-based parameter pagination crawling"""

    def __init__(self, homepage_html: str):
        self.homepage_html = homepage_html

    def fetch(self, homepage_url: str, crawl_config: Dict[str, Any], company_config: Dict[str, Any]) -> List[str]:
        url_tmpl = crawl_config.get("url_template")
        if not url_tmpl:
            logger.warning("No URL template available. Falling back to single page.")
            return [self.homepage_html]

        downloader_cfg = company_config.get("downloader", {})
        max_pages = int(downloader_cfg.get("max_pages", 5))
        scroll_count = int(downloader_cfg.get("scroll_count", 0))
        scroll_delay = int(downloader_cfg.get("scroll_delay", 1500))

        logger.info(f"Using URL template pagination: {url_tmpl} (max_pages={max_pages})")
        htmls = [self.homepage_html]
        
        for page_idx in range(2, max_pages + 1):
            try:
                page_url = url_tmpl.format(page=page_idx)
            except Exception:
                page_url = url_tmpl.replace("{page}", str(page_idx))
                
            logger.info(f"Fetching URL template page {page_idx}: {page_url}")
            try:
                p_html = downloader.fetch_html(
                    page_url,
                    scroll_count=scroll_count,
                    scroll_delay=scroll_delay
                )
                htmls.append(p_html)
            except Exception as pe:
                logger.warning(f"Failed to fetch template page {page_idx}: {str(pe)}. Stopping pagination loop.")
                break
        return htmls


class PlaywrightClickPagination(BasePaginationStrategy):
    """Dynamic pagination crawling based on Playwright clicks (next page or load more)"""

    def __init__(self, homepage_html: str):
        self.homepage_html = homepage_html

    def fetch(self, homepage_url: str, crawl_config: Dict[str, Any], company_config: Dict[str, Any]) -> List[str]:
        next_sel = crawl_config.get("next_page_selector")
        cookie_sel = crawl_config.get("cookie_accept_selector")
        
        if not next_sel:
            logger.warning("No next page selector available. Falling back to single page.")
            return [self.homepage_html]

        downloader_cfg = company_config.get("downloader", {})
        max_pages = int(downloader_cfg.get("max_pages", 5))
        page_delay = int(downloader_cfg.get("page_delay", 2000))
        scroll_count = int(downloader_cfg.get("scroll_count", 0))
        scroll_delay = int(downloader_cfg.get("scroll_delay", 1500))

        logger.info(f"Using Playwright click pagination with selector: {next_sel} (max_pages={max_pages})")
        try:
            htmls = downloader.fetch_pages_html(
                homepage_url,
                next_page_selector=next_sel,
                max_pages=max_pages,
                page_delay=page_delay,
                cookie_accept_selector=cookie_sel,
                scroll_count=scroll_count,
                scroll_delay=scroll_delay
            )
            return htmls
        except Exception as pe:
            logger.error(f"Playwright multi-page pagination failed: {str(pe)}. Falling back to single page.")
            return [self.homepage_html]


# ==========================================
# 3. Crawler Strategy Standard
# ==========================================

class BaseCrawlerStrategy(ABC):
    """Overall standard interface for crawling and parsing job postings from websites"""

    @abstractmethod
    def fetch_homepage(self, url: str) -> str:
        """Crawl and return recruitment homepage HTML"""
        pass

    @abstractmethod
    def resolve_config(self, session: Session, company: Company, homepage_html: str, homepage_url: str) -> Dict[str, Any]:
        """Resolve, validate and update pagination/Cookie configuration, supporting cache validation and self-healing"""
        pass

    @abstractmethod
    def fetch_pages(self, homepage_url: str, resolved_config: Dict[str, Any], homepage_html: str, company_config: Dict[str, Any]) -> List[str]:
        """Perform multi-page crawl and return a list of multi-page HTML"""
        pass

    @abstractmethod
    def extract_job_urls(self, pages_html: List[str], base_url: str = None) -> List[str]:
        """Extract all job links from the fetched multi-page HTML list and recover physical URLs"""
        pass


class LLMCrawlerStrategy(BaseCrawlerStrategy):
    """Universal LLM-driven intelligent adaptive crawler strategy"""

    def fetch_homepage(self, url: str) -> str:
        # Use universal downloader to fetch homepage HTML
        return downloader.fetch_html(url)

    def resolve_config(self, session: Session, company: Company, homepage_html: str, homepage_url: str) -> Dict[str, Any]:
        saved_cfg = company.crawl_config or {}
        logger.info(f"Loaded cached crawl config for {company.name}: {saved_cfg}")
        
        need_sniff = False
        if not saved_cfg:
            need_sniff = True
            
        # --- Bad cache auto-error correction check ---
        if not need_sniff and saved_cfg and not saved_cfg.get("is_paginated", False):
            clue_words = ["pagination", "go-to-next", "page-numbers", "next-page", "load-more-btn"]
            has_clues = any(w in homepage_html.lower() for w in clue_words)
            if has_clues:
                logger.info(f"Cached config for {company.name} shows no pagination, but page HTML contains pagination clues. Force re-sniffing...")
                need_sniff = True
                
        if not need_sniff and saved_cfg and saved_cfg.get("url_template"):
            cached_tmpl = saved_cfg.get("url_template", "")
            if "..." in cached_tmpl:
                logger.info(f"Cached config for {company.name} has an invalid template URL '{cached_tmpl}' containing ellipsis. Force re-sniffing...")
                need_sniff = True

        # --- Bad selector auto-correction check: if the cached selector points to a numeric page button ---
        if not need_sniff and saved_cfg and saved_cfg.get("next_page_selector"):
            cached_sel = saved_cfg.get("next_page_selector")
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(homepage_html, "html.parser")
                elements = soup.select(cached_sel) if cached_sel else []
                if elements:
                    first_el = elements[0]
                    el_text = first_el.get_text(strip=True)
                    el_aria = first_el.get("aria-label") or ""
                    is_digit = el_text.isdigit()
                    is_numeric_aria = "page" in el_aria.lower() and any(c.isdigit() for c in el_aria) and "next" not in el_aria.lower()
                    if is_digit or is_numeric_aria:
                        logger.info(f"Cached next_page_selector '{cached_sel}' targets a numeric page button instead of 'Next' button. Force re-sniffing...")
                        need_sniff = True
            except Exception as e:
                logger.warning(f"Error checking cached selector '{cached_sel}': {str(e)}")

        sniffer_cfg = {}
        if need_sniff:
            logger.info(f"Sniffing pagination and cookie configurations for {company.name} careers site...")
            sniffer_cfg = scraper.detect_pagination_and_cookie(homepage_html, homepage_url)
            logger.info(f"Sniffed configurations: {sniffer_cfg}")
            
            # Only write to the DB when LLM sniffing is successful to prevent caching failed fallback configs
            if sniffer_cfg.get("success", True):
                db_cfg = {k: v for k, v in sniffer_cfg.items() if k != "success"}
                company.crawl_config = db_cfg
                session.flush()
        else:
            sniffer_cfg = saved_cfg

        # Assemble the complete final runtime configuration
        url_template = sniffer_cfg.get("url_template")
        if url_template:
            url_template = clean_url_template(url_template, homepage_url)
            if not url_template.startswith("http://") and not url_template.startswith("https://"):
                logger.warning(f"URL template '{url_template}' is invalid. Disabling URL pagination.")
                url_template = None

        next_page_selector = sniffer_cfg.get("next_page_selector")
        cookie_accept_selector = sniffer_cfg.get("cookie_accept_selector")
        pagination_type = sniffer_cfg.get("pagination_type", "none")

        # Logic auto-correction
        if next_page_selector and not url_template and pagination_type == "url_template":
            logger.info("Correction: detected next_page_selector but no url_template. Changing pagination_type to 'next_button'.")
            pagination_type = "next_button"
        elif url_template and not next_page_selector and pagination_type in ["next_button", "load_more"]:
            logger.info("Correction: detected url_template but no next_page_selector. Changing pagination_type to 'url_template'.")
            pagination_type = "url_template"

        is_paginated = sniffer_cfg.get("is_paginated", False) or bool(next_page_selector) or bool(url_template)

        return {
            "is_paginated": is_paginated,
            "pagination_type": pagination_type,
            "url_template": url_template,
            "next_page_selector": next_page_selector,
            "cookie_accept_selector": cookie_accept_selector
        }

    def fetch_pages(self, homepage_url: str, resolved_config: Dict[str, Any], homepage_html: str, company_config: Dict[str, Any]) -> List[str]:
        # Allow manual override of selector/url_template in config to bypass auto-resolved config
        downloader_cfg = company_config.get("downloader", {})
        user_next_page_selector = downloader_cfg.get("next_page_selector")
        user_cookie_selector = downloader_cfg.get("cookie_accept_selector")
        user_url_template = downloader_cfg.get("url_template")

        # Assemble final low-level running parameters
        run_config = {
            "is_paginated": resolved_config.get("is_paginated", False),
            "pagination_type": resolved_config.get("pagination_type", "none"),
            "url_template": user_url_template or resolved_config.get("url_template"),
            "next_page_selector": user_next_page_selector or resolved_config.get("next_page_selector"),
            "cookie_accept_selector": user_cookie_selector or resolved_config.get("cookie_accept_selector")
        }

        # Clean up user-specified url_template
        if user_url_template:
            run_config["url_template"] = clean_url_template(user_url_template, homepage_url)
            run_config["pagination_type"] = "url_template"
            run_config["is_paginated"] = True
        elif user_next_page_selector:
            run_config["pagination_type"] = "next_button"
            run_config["is_paginated"] = True

        # Route and instantiate corresponding pagination strategy based on configuration
        pag_strategy = self._get_pagination_strategy(run_config, homepage_html)
        pages_html = pag_strategy.fetch(homepage_url, run_config, company_config)

        # --- Intelligent self-healing and layout change detection mechanism ---
        # If configured to page via click pagination, but only 1 page of data was fetched, it indicates a potential site layout change. Force self-healing re-sniffing.
        is_paginated = run_config["is_paginated"]
        pagination_type = run_config["pagination_type"]
        next_page_selector = run_config["next_page_selector"]
        
        has_user_override = bool(user_next_page_selector or user_url_template)

        if is_paginated and pagination_type in ["next_button", "load_more"] and next_page_selector and len(pages_html) == 1 and not has_user_override:
            logger.warning(f"Crawl config indicates pagination, but click-based paging failed. career site might have changed. Re-sniffing configurations...")
            # Force clear cache and re-sniff
            new_sniffer_cfg = scraper.detect_pagination_and_cookie(homepage_html, homepage_url)
            logger.info(f"Re-sniffed configurations: {new_sniffer_cfg}")
            
            # If configurations change, update in-memory config and database
            if new_sniffer_cfg and new_sniffer_cfg.get("success", True):
                db_cfg = {k: v for k, v in new_sniffer_cfg.items() if k != "success"}
                
                # Write back to the database
                from shared.database import get_db_session
                with get_db_session() as session:
                    db_company = session.query(Company).filter(Company.name == company_config["name"]).first()
                    if db_company:
                        db_company.crawl_config = db_cfg
                        session.flush()
                
                # Rebuild retry configuration and fetch
                run_config = {
                    "is_paginated": new_sniffer_cfg.get("is_paginated", False),
                    "pagination_type": new_sniffer_cfg.get("pagination_type", "none"),
                    "url_template": clean_url_template(new_sniffer_cfg.get("url_template"), homepage_url),
                    "next_page_selector": new_sniffer_cfg.get("next_page_selector"),
                    "cookie_accept_selector": new_sniffer_cfg.get("cookie_accept_selector")
                }
                logger.info("Retrying fetch with newly sniffed configurations...")
                pag_strategy = self._get_pagination_strategy(run_config, homepage_html)
                pages_html = pag_strategy.fetch(homepage_url, run_config, company_config)

        return pages_html

    def extract_job_urls(self, pages_html: List[str], base_url: str = None) -> List[str]:
        extractor = LLMJobUrlExtractor()
        raw_urls = []
        
        for idx, p_html in enumerate(pages_html):
            logger.info(f"Extracting job URLs from page {idx + 1}/{len(pages_html)}...")
            p_urls = extractor.extract(p_html, base_url=base_url)
            logger.info(f"Extracted {len(p_urls)} job URLs from page {idx + 1}.")
            
            # Incremental safe exit: if a page yields no job URLs but previous pages did, it usually means pagination has ended or got blocked; stop immediately.
            if not p_urls and raw_urls:
                logger.info("No more job URLs extracted from this page. Stopping URL extraction.")
                break
                
            raw_urls.extend(p_urls)

        # Keep extracted URLs unique and deduplicated
        return list(dict.fromkeys(raw_urls))

    def _get_pagination_strategy(self, run_config: Dict[str, Any], homepage_html: str) -> BasePaginationStrategy:
        is_paginated = run_config.get("is_paginated", False)
        pag_type = run_config.get("pagination_type", "none")

        if is_paginated and pag_type == "url_template" and run_config.get("url_template"):
            return UrlTemplatePagination(homepage_html)
        elif is_paginated and pag_type in ["next_button", "load_more"] and run_config.get("next_page_selector"):
            return PlaywrightClickPagination(homepage_html)
        return SinglePagePagination(homepage_html)


# 4. Crawler Strategy Factory
# ==========================================

class CrawlerStrategyFactory:
    """Strategy factory class to obtain crawler strategy instance based on company configuration"""

    @staticmethod
    def get_strategy(company_name: str) -> BaseCrawlerStrategy:
        """
        Get the corresponding crawler strategy based on the company name.
        Defaults to returning LLMCrawlerStrategy. If a company requires custom crawling logic later,
        a specific CrawlerStrategy instance can be returned here.
        """
        # Can perform matching mapping based on company_name; defaults to returning universal intelligent LLMCrawlerStrategy
        return LLMCrawlerStrategy()
