import time
import logging
import atexit
import threading
from playwright.sync_api import sync_playwright
from tenacity import retry, stop_after_attempt, wait_exponential
from shared.config import config

logger = logging.getLogger(__name__)

class PlaywrightDownloader:
    """Playwright-based web rendering downloader (supports persistent connection / singleton browser reuse)"""

    def __init__(self, headless: bool = True, timeout: int = None):
        self.headless = headless
        self.timeout = timeout if timeout is not None else config.timeout
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self._thread_local = threading.local()
        
        # Register exit hook to ensure that the browser process is correctly killed when the Python process exits, preventing orphan processes
        atexit.register(self.close)

    def _get_browser(self):
        """Get or launch a reused Playwright browser instance (self-healing / persistent connection)"""
        if not hasattr(self._thread_local, "playwright"):
            self._thread_local.playwright = None
        if not hasattr(self._thread_local, "browser"):
            self._thread_local.browser = None

        if self._thread_local.browser is None or not self._thread_local.browser.is_connected():
            logger.info("Initializing a new long-lived Playwright browser instance for current thread...")
            if self._thread_local.playwright is not None:
                try:
                    self._thread_local.playwright.stop()
                except Exception:
                    pass
            self._thread_local.playwright = sync_playwright().start()
            self._thread_local.browser = self._thread_local.playwright.chromium.launch(headless=self.headless)
        return self._thread_local.browser

    def close(self):
        """Release the browser and Playwright driver resources for the current thread"""
        playwright = getattr(self._thread_local, "playwright", None)
        browser = getattr(self._thread_local, "browser", None)
        if browser is not None:
            try:
                logger.info("Closing long-lived Playwright browser for current thread...")
                browser.close()
            except Exception as e:
                logger.debug(f"Error closing browser: {str(e)}")
            self._thread_local.browser = None
        if playwright is not None:
            try:
                playwright.stop()
            except Exception as e:
                logger.debug(f"Error stopping Playwright: {str(e)}")
            self._thread_local.playwright = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def fetch_html(
        self,
        url: str,
        wait_selector: str = None,
        scroll_count: int = 0,
        scroll_delay: int = 1500,
        load_more_selector: str = None,
        load_more_limit: int = 0
    ) -> str:
        logger.info(f"Navigating to {url} using Playwright (reusing browser)...")
        
        browser = self._get_browser()
        # Create separate Context to ensure session isolation during concurrent scrapes
        context = browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.set_default_timeout(self.timeout)
        
        try:
            response = page.goto(url, wait_until="domcontentloaded")
            
            if not response:
                raise Exception(f"Failed to load page: No response received from {url}")
            
            if response.status >= 400:
                raise Exception(f"Failed to load page: HTTP {response.status} from {url}")
            
            if wait_selector:
                logger.debug(f"Waiting for selector: {wait_selector}")
                page.wait_for_selector(wait_selector, timeout=10000)
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    logger.debug("Network did not go idle within 5 seconds, proceeding anyway.")
            
            # --- 1. Click 'load more' button to load paginated data ---
            if load_more_selector and load_more_limit > 0:
                logger.info(f"Triggering 'load more' click loop (up to {load_more_limit} times) for: {load_more_selector}")
                for click_idx in range(load_more_limit):
                    try:
                        btn = page.query_selector(load_more_selector)
                        if btn and btn.is_visible() and btn.is_enabled():
                            logger.info(f"Clicking load more button ({click_idx + 1}/{load_more_limit})")
                            btn.click()
                            page.wait_for_timeout(2000)  # Wait for loading
                        else:
                            logger.debug("Load more button is no longer clickable or visible. Ending click loop.")
                            break
                    except Exception as click_err:
                        logger.debug(f"Load more click interrupted: {str(click_err)}")
                        break

            # --- 2. Scroll down page to trigger lazy loading / paginated data ---
            if scroll_count > 0:
                logger.info(f"Triggering scroll loop ({scroll_count} times, delay={scroll_delay}ms)")
                for scroll_idx in range(scroll_count):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(scroll_delay)
                    logger.debug(f"Scrolled to bottom ({scroll_idx + 1}/{scroll_count})")
            
            time.sleep(1.5)
            html_content = page.content()
            logger.info(f"Successfully fetched {len(html_content)} bytes of HTML from {url}")
            return html_content
            
        except Exception as e:
            logger.error(f"Error fetching URL {url}: {str(e)}")
            raise e
        finally:
            # Only close page and context, do not close the reused browser
            context.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def fetch_pages_html(
        self,
        url: str,
        next_page_selector: str,
        max_pages: int = 5,
        page_delay: int = 2000,
        cookie_accept_selector: str = None,
        scroll_count: int = 0,
        scroll_delay: int = 1500
    ) -> list[str]:
        """
        Load initial page and simulate clicking 'Next' button in the browser to crawl multiple pages of HTML.
        Returns a list containing HTML strings for each page.
        """
        logger.info(f"Navigating to {url} using Playwright for multi-page extraction (reusing browser)...")
        pages_content = []
        
        browser = self._get_browser()
        context = browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.set_default_timeout(self.timeout)
        
        try:
            response = page.goto(url, wait_until="domcontentloaded")
            if not response:
                raise Exception(f"Failed to load page: No response received from {url}")
            if response.status >= 400:
                raise Exception(f"Failed to load page: HTTP {response.status} from {url}")
            
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            
            # --- 1. Handle Cookie consent popups to prevent blocking pagination ---
            if cookie_accept_selector:
                try:
                    cookie_btn = page.query_selector(cookie_accept_selector)
                    if cookie_btn and cookie_btn.is_visible() and cookie_btn.is_enabled():
                        logger.info(f"Clicking Cookie consent button: {cookie_accept_selector}")
                        cookie_btn.click()
                        page.wait_for_timeout(3000)  # Wait for popup to disappear and render (increased to 3s)
                except Exception as cookie_err:
                    logger.debug(f"Failed to process Cookie consent: {str(cookie_err)}")

            # --- 2. Lazy load scrolling of the initial page ---
            if scroll_count > 0:
                logger.debug(f"Scrolling initial page ({scroll_count} times)")
                for scroll_idx in range(scroll_count):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(scroll_delay)
            
            # Record the first page HTML
            first_html = page.content()
            pages_content.append(first_html)
            logger.info(f"Page 1 fetched: {len(first_html)} bytes.")
            
            # --- 3. Loop pagination click ---
            for p_idx in range(1, max_pages):
                logger.info(f"Attempting to navigate to page {p_idx + 1}/{max_pages}...")
                
                next_btn = None
                selectors = [
                    next_page_selector,
                    "button[aria-label*='Next' i]",
                    "button[aria-label*='next' i]",
                    "[aria-label*='Next page' i]",
                    "[aria-label*='Next' i]",
                    "ul.pagination-ul a:has-text(\">\")",
                    "ul.pagination-ul a:has-text(\"Next\")",
                    "a.go-to-next",
                    "a:has-text(\"Next\")",
                    "a:has-text(\">\")",
                    "button:has-text(\"Next\")",
                    "button.right"
                ]
                for sel in selectors:
                    if not sel:
                        continue
                    try:
                        # Match as long as it is attached to the DOM, to prevent visibility detection failures caused by zero-sized buttons or hidden icons
                        btn = page.wait_for_selector(sel, state="attached", timeout=2000)
                        if btn and btn.is_enabled():
                            # Add visibility check: if the matched button is not visible, skip it to try other candidate selectors
                            if not btn.is_visible():
                                logger.debug(f"Selector '{sel}' found but is not visible. Skipping to next candidate.")
                                continue
                            next_btn = btn
                            logger.info(f"Found next page button via selector: {sel}")
                            break
                    except Exception:
                        pass
                        
                if not next_btn:
                    logger.info("Next page button not found in DOM or is not visible via any selector. Stopping pagination.")
                    break
                
                if not next_btn.is_enabled():
                    logger.info("Next page button is disabled. Stopping pagination.")
                    break
                    
                aria_disabled = next_btn.get_attribute("aria-disabled")
                if aria_disabled == "true":
                    logger.info("Next page button has aria-disabled='true'. Stopping pagination.")
                    break
                
                # Extract the page link signature before clicking, as a baseline for comparing if the new page has loaded
                def get_page_signatures(p):
                    try:
                        hrefs = p.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.href)")
                        return set([h.strip() for h in hrefs if h and not h.startswith("#") and not h.startswith("javascript:")])
                    except Exception:
                        return set()

                old_signatures = get_page_signatures(page)
                
                # Get the plain text hash of the page HTML before clicking as the second decision metric
                from shared.deduplicator import deduplicator
                old_html_hash = deduplicator.calculate_text_hash(page.content())
                
                logger.debug(f"Current page signatures count: {len(old_signatures)}")
                
                try:
                    logger.debug("Clicking Next page button (enforcing click)...")
                    next_btn.click(force=True)
                except Exception as click_err:
                    logger.warning(f"Failed to click next page button: {str(click_err)}. Stopping pagination and returning fetched pages.")
                    break
                
                # Smart self-healing wait for new data rendering: check every 500ms, up to 10s
                load_success = False
                for check_idx in range(20):
                    page.wait_for_timeout(500)
                    
                    if scroll_count > 0 and check_idx == 0:
                        for scroll_idx in range(scroll_count):
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            page.wait_for_timeout(scroll_delay)
                            
                    current_signatures = get_page_signatures(page)
                    new_sigs = current_signatures - old_signatures
                    
                    current_html_hash = deduplicator.calculate_text_hash(page.content())
                    
                    # Double check: new links generated, or the page HTML fingerprint changed (e.g. active page state changed)
                    if new_sigs or current_html_hash != old_html_hash:
                        if new_sigs:
                            logger.info(f"Page {p_idx + 1} load detected via new links. Found {len(new_sigs)} new links.")
                        else:
                            logger.info(f"Page {p_idx + 1} load detected via page content signature change.")
                        load_success = True
                        break
                        
                if not load_success:
                    logger.warning("Timeout waiting for page content to change after click. Pagination loop stopped.")
                    break
                    
                current_html = page.content()
                pages_content.append(current_html)
                logger.info(f"Page {p_idx + 1} fetched: {len(current_html)} bytes.")
                
            return pages_content
            
        except Exception as e:
            logger.error(f"Error fetching multi-page HTML from {url}: {str(e)}")
            raise e
        finally:
            # Only close page and context, do not close the reused browser
            context.close()

downloader = PlaywrightDownloader()
