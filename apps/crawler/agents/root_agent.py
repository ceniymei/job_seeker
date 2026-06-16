import logging
import json
import re
from typing import Dict, Any, List
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from shared.config import config
from shared.downloader import downloader

logger = logging.getLogger("job_seeker_crawler.agents.root_agent")

from shared.llm import get_llm

def simplify_html(html_content: str) -> str:
    """Extract HTML interaction elements, compressing them for LLM analysis"""
    soup = BeautifulSoup(html_content, "html.parser")
    interesting_tags = ["a", "button", "input", "select", "nav"]
    simplified = []
    
    for tag in soup.find_all(interesting_tags):
        href = tag.get("href")
        cls = tag.get("class")
        id_attr = tag.get("id")
        text = tag.get_text(strip=True)
        
        cls_str = " ".join(cls) if isinstance(cls, list) else str(cls or "")
        id_str = str(id_attr or "")
        href_str = str(href or "")
        
        combined = (text + " " + cls_str + " " + id_str + " " + href_str).lower()
        keywords = ["page", "pagination", "next", "prev", "load-more", "cookie", "consent", "accept", "allow", "agree"]
        
        if any(k in combined for k in keywords) or (text.isdigit() and len(text) < 4) or tag.name in ["select", "nav"]:
            attrs = []
            if id_attr: attrs.append(f'id="{id_attr}"')
            if cls: attrs.append(f'class="{" ".join(cls) if isinstance(cls, list) else cls}"')
            if href: attrs.append(f'href="{href}"')
            if tag.get("onclick"): attrs.append(f'onclick="{tag.get("onclick")}"')
            if tag.get("aria-current"): attrs.append(f'aria-current="{tag.get("aria-current")}"')
            if tag.get("aria-label"): attrs.append(f'aria-label="{tag.get("aria-label")}"')
            
            simplified.append(f"<{tag.name} {' '.join(attrs)}>{text}</{tag.name}>")
            
    return "\n".join(simplified)

def sniff_traffic_and_decision(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Root Agent core node logic:
    1. Fetch and listen to network traffic;
    2. Use LLM to analyze traffic and HTML to make adaptive routing configuration decisions.
    """
    logger.info(f"RootAgent: Starting traffic sniffing and decision for {state['company_name']}")
    url = state["homepage_url"]
    
    traffic = []
    homepage_html = ""
    
    # 1. Launch Playwright to intercept XHR/Fetch traffic
    from playwright.sync_api import sync_playwright
    logger.info(f"RootAgent: Launching sniffer browser for {url}...")
    
    # Get the reused browser instance inside downloader to avoid separate creation, keeping monorepo highly cohesive
    browser = downloader._get_browser()
    context = browser.new_context(
        user_agent=downloader.user_agent,
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    page.set_default_timeout(20000)
    
    import gzip
    
    def on_request(request):
        if request.resource_type in ["xhr", "fetch"]:
            post_data = None
            try:
                post_bytes = request.post_data_buffer
                if post_bytes:
                    # Check Gzip compression header (0x1f, 0x8b)
                    if post_bytes.startswith(b'\x1f\x8b'):
                        try:
                            post_bytes = gzip.decompress(post_bytes)
                        except Exception:
                            pass
                    post_data = post_bytes.decode('utf-8')
            except Exception:
                pass
            # Record JSON APIs potentially containing job listings
            traffic.append({
                "url": request.url,
                "method": request.method,
                "post_data": post_data
            })
            
    page.on("request", on_request)
    
    try:
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(2000) # Wait for AJAX to fully load and render
        
        # If Cookie Consent dialog exists
        cookie_accept_selector = "#accept-recommended-btn-handler" # Preset common ID to trigger load
        try:
            btn = page.query_selector(cookie_accept_selector)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass
            
        homepage_html = page.content()
    except Exception as e:
        logger.error(f"RootAgent sniffer load failed: {str(e)}")
        # Fallback: use only statically fetched HTML for analysis
        homepage_html = downloader.fetch_html(url)
    finally:
        context.close()
        
    # 2. Compress HTML and call LLM for pattern recognition
    simplified_elements = simplify_html(homepage_html)
    logger.info(f"RootAgent: Sniffed HTML size: {len(homepage_html)}, simplified: {len(simplified_elements)}")
    
    # Only provide the top 15 XHR requests matching JSON interface characteristics to avoid token explosion
    filtered_traffic = []
    for t in traffic:
        t_url = t["url"].lower()
        # Filter out static resources and analytics/tracking
        if any(w in t_url for w in [".js", ".css", ".png", ".jpg", "analytics", "telemetry", "tracking", "google-analytics"]):
            continue
        filtered_traffic.append(t)
        if len(filtered_traffic) >= 15:
            break
            
    logger.info(f"RootAgent: Filtered network requests count: {len(filtered_traffic)}")
    
    # Heuristically extract a few real job URL samples to feed to the LLM to prevent hallucinations
    sample_urls = []
    try:
        soup_temp = BeautifulSoup(homepage_html, "html.parser")
        base_url = url
        base_tag = soup_temp.find("base")
        if base_tag and base_tag.get("href"):
            base_url = urljoin(url, base_tag.get("href").strip())
            
        parsed_url = urlparse(url)
        for a in soup_temp.find_all("a"):
            href = a.get("href")
            if href:
                href = href.strip()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue
                abs_href = urljoin(base_url, href)
                abs_href_lower = abs_href.lower()
                
                parsed_href = urlparse(abs_href)
                # Filter out external links to prevent mixing in external platforms like LinkedIn
                if parsed_href.netloc and parsed_href.netloc != parsed_url.netloc:
                    continue
                    
                # Filter out obvious system/menu links like listings, recommendations, subscriptions, search, login, etc.
                path_segments = [s for s in parsed_href.path.split("/") if s]
                last_segment = path_segments[-1] if path_segments else ""
                if last_segment in ["results", "recommendations", "saved", "alerts", "search", "signin", "login", "signup"]:
                    continue
                
                # Match potential job path characteristics
                if any(p in abs_href_lower for p in ["/job/", "/jobs/", "/position/", "/detail/", "/details/", "/role/"]):
                    if abs_href not in sample_urls:
                        sample_urls.append(abs_href)
                        if len(sample_urls) >= 5:
                            break
    except Exception as sample_err:
        logger.warning(f"RootAgent failed to collect URL samples for LLM grounding: {str(sample_err)}")
        
    sample_section = ""
    if sample_urls:
        sample_section = f"Detected Potential Job Link Samples in HTML:\n{json.dumps(sample_urls, indent=2)}\n\n"
        
    prompt = (
        "You are an expert career scraping routing agent. Analyze the career list page elements and network requests to choose the best crawling mode.\n"
        f"Target Site: {url}\n\n"
        f"Simplified Interactive Elements in HTML:\n{simplified_elements}\n\n"
        f"{sample_section}"
        f"Intercepted XHR/Fetch network requests (JSON/APIs):\n{json.dumps(filtered_traffic, indent=2)}\n\n"
        "Return a strictly structured JSON without any markdown code block wrapper (no ```json code blocks), containing these keys:\n"
        "1. is_paginated (boolean): True if there is pagination or multiple pages of listings.\n"
        "2. pagination_type (string): One of 'api_direct' (if there is a clear background XHR API URL returning JSON listings that we can call directly with pages), 'next_button' (if we must click a Next page button on a browser), 'url_template' (if pages use standard URL parameters like ?page=2), or 'none'.\n"
        "3. url_template (string/null): If 'api_direct' or 'url_template', specify the absolute URL template replacing the page number with '{page}' (e.g. 'https://example.com/api/jobs?page={page}'). Must be absolute. If pagination_type is 'next_button', set to null. DO NOT hallucinate any nonexistent URL template.\n"
        "4. next_page_selector (string/null): CSS selector for clicking the 'Next' page button (e.g. 'a.go-to-next'), else null. DO NOT target a numeric page number button like 'a#pagination1'.\n"
        "5. cookie_accept_selector (string/null): CSS selector for Accept cookie button if present.\n"
        "6. job_url_keywords (array of strings): High-confidence URL path substrings uniquely identifying a job detail page (e.g. ['/details/', '/job/', '/jobs/', '/role/']). Choose the most specific path features matching the job detail links visible in the HTML.\n"
        "7. job_url_pattern (string/null): A wildcard template representing the format of job detail URLs on this site. If 'Detected Potential Job Link Samples' are provided, you MUST base this on those samples, replacing dynamic segments with placeholders like {id} for numeric IDs and {job-title} for the job title slug (e.g. '/en/jobs/{id}/{job-title}' or '/en-sg/details/{id}/{job-title}'). If no samples are provided, analyze the HTML to discern the pattern. If not discernable, set to null.\n"
    )
    
    try:
        llm = get_llm()
        logger.info("RootAgent: Calling LLM for routing decision...")
        response = llm.invoke(prompt)
        raw_result = response.content.strip()
        logger.info(f"RootAgent LLM raw decision: {raw_result}")
        
        # Strip non-JSON impurities
        if "{" in raw_result:
            raw_result = raw_result[raw_result.find("{"):raw_result.rfind("}")+1]
            
        decision = json.loads(raw_result)
    except Exception as e:
        logger.error(f"RootAgent LLM call/parse failed: {str(e)}. Using fallback default config.")
        # Fallback configuration
        decision = {
            "is_paginated": False,
            "pagination_type": "none",
            "url_template": None,
            "next_page_selector": None,
            "cookie_accept_selector": None,
            "job_url_keywords": [],
            "job_url_pattern": None
        }
        
    # 3. Validate and clean decision configurations, eliminating bad cache
    raw_next_page_selector = decision.get("next_page_selector")
    raw_cookie_accept_selector = decision.get("cookie_accept_selector")
    
    soup = BeautifulSoup(homepage_html, "html.parser")
    
    # Physically validate and clean numeric buttons and Cookie buttons
    next_page_selector = None
    if raw_next_page_selector:
        try:
            elements = soup.select(raw_next_page_selector)
            if elements:
                first_el = elements[0]
                el_text = first_el.get_text(strip=True)
                el_aria = first_el.get("aria-label") or ""
                
                is_digit = el_text.isdigit()
                is_numeric_aria = "page" in el_aria.lower() and any(c.isdigit() for c in el_aria) and "next" not in el_aria.lower()
                
                # Precisely identify Cookie consent buttons
                combined_selector = raw_next_page_selector.lower()
                el_id = first_el.get("id") or ""
                el_cls = " ".join(first_el.get("class") or [])
                combined_el_info = (el_text + " " + el_id + " " + el_cls).lower()
                is_cookie_btn = any(w in combined_selector or w in combined_el_info for w in ["cookie", "consent", "privacy", "banner", "accept-recommended", "ot-sdk"])
                
                if is_digit or is_numeric_aria or is_cookie_btn:
                    logger.warning(f"RootAgent: Rejected LLM selector '{raw_next_page_selector}' because it matches a numeric page button or cookie button.")
                else:
                    next_page_selector = raw_next_page_selector
        except Exception:
            pass
            
    # Heuristic fallback
    if not next_page_selector and decision.get("pagination_type") == "next_button":
        from apps.crawler.scraper import scraper
        fallback = scraper._extract_fallback_next_selector(soup)
        if fallback:
            logger.info(f"RootAgent: Heuristic extracted fallback next_page_selector: '{fallback}'")
            next_page_selector = fallback
            
    cookie_accept_selector = None
    if raw_cookie_accept_selector:
        try:
            elements = soup.select(raw_cookie_accept_selector)
            if elements:
                first_el = elements[0]
                el_text = first_el.get_text(strip=True).lower()
                el_tag = first_el.name.lower()
                el_id = (first_el.get("id") or "").lower()
                el_cls = " ".join(first_el.get("class") or []).lower()
                el_href = (first_el.get("href") or "").lower()
                
                # Exclude policy redirect links
                is_policy_link = el_tag == "a" and any(w in el_href or w in el_text for w in ["privacy", "policy", "notice", "cookie-policy"])
                # Exclude text links that are not active agreement (removing generic words like btn/button/handler)
                is_not_accept = not any(w in el_text or w in el_id or w in el_cls for w in ["accept", "agree", "allow", "consent", "yes", "ok", "all"])
                
                if is_policy_link or is_not_accept:
                    logger.warning(f"RootAgent: Rejected LLM cookie selector '{raw_cookie_accept_selector}' because it is a policy link or lacks accept semantics.")
                else:
                    cookie_accept_selector = raw_cookie_accept_selector
        except Exception:
            pass
            
    if not cookie_accept_selector:
        from apps.crawler.scraper import scraper
        fallback_cookie = scraper._extract_fallback_cookie_selector(soup)
        if fallback_cookie:
            cookie_accept_selector = fallback_cookie
            
    # Adaptive correction and final Agent decision
    pag_type = str(decision.get("pagination_type") or "none").lower()
    url_template = decision.get("url_template")
    
    # Pre-test API accessibility for 'api_direct' pagination type to prevent 401/403 auth or 404 errors
    if pag_type == "api_direct" and url_template:
        test_url = url_template.replace("{page}", "1")
        try:
            import httpx
            headers = {
                "User-Agent": downloader.user_agent,
                "Accept": "application/json"
            }
            with httpx.Client(headers=headers, timeout=5.0, follow_redirects=True) as client:
                res = client.get(test_url)
                if res.status_code >= 400:
                    logger.warning(f"RootAgent: Direct API '{test_url}' returned error status {res.status_code}. Correcting pagination_type to 'next_button'.")
                    pag_type = "next_button"
                    url_template = None
                    if not next_page_selector:
                        from apps.crawler.scraper import scraper
                        fallback = scraper._extract_fallback_next_selector(soup)
                        if fallback:
                            next_page_selector = fallback
        except Exception as api_err:
            logger.warning(f"RootAgent: Failed to pre-test API accessibility: {str(api_err)}")
            
    if pag_type == "api_direct" and url_template:
        assigned_agent = "api"
    elif pag_type == "url_template" and url_template:
        assigned_agent = "traditional"
    elif next_page_selector:
        assigned_agent = "playwright"
        pag_type = "next_button"
    else:
        assigned_agent = "traditional" # Fallback to single page fetch
        pag_type = "none"
        
    resolved_config = {
        "is_paginated": decision.get("is_paginated", False) or bool(next_page_selector) or bool(url_template),
        "pagination_type": pag_type,
        "url_template": url_template,
        "next_page_selector": next_page_selector,
        "cookie_accept_selector": cookie_accept_selector,
        "job_url_keywords": decision.get("job_url_keywords") or [],
        "job_url_pattern": decision.get("job_url_pattern")
    }
    
    logger.info(f"RootAgent decision routing complete. Config: {resolved_config}. Assigned Agent: {assigned_agent}")
    
    return {
        "homepage_html": homepage_html,
        "crawl_config": resolved_config,
        "assigned_agent": assigned_agent,
        "is_successful": False # Only completed identification decision, marked as not yet completed extraction
    }

def validate_and_recover_urls(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unified URL post-processing recovery and validation node:
    1. Recover links simplified or hallucinated by the LLM (e.g. missing /job/ID path);
    2. Evaluate link quality to decide whether to trigger self-healing retry.
    """
    raw_urls = state.get("raw_urls") or []
    homepage_html = state.get("homepage_html") or ""
    homepage_url = state.get("homepage_url")
    company_name = state["company_name"]
    
    logger.info(f"RootAgent: Validating and recovering {len(raw_urls)} URLs for {company_name}...")
    
    if not raw_urls:
        logger.warning("RootAgent validation: URL list is EMPTY.")
        return {
            "final_urls": [],
            "is_successful": False,
            "error_message": "Extracted URLs list is empty"
        }
        
    # --- URL Recovery Physical Correction Mechanism ---
    soup = BeautifulSoup(homepage_html, "html.parser")
    base_url = homepage_url
    base_tag = soup.find("base")
    if base_tag and base_tag.get("href"):
        base_url = urljoin(homepage_url, base_tag.get("href").strip())
        
    real_hrefs = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if href:
            href = href.strip()
            if href and not href.startswith("#") and not href.startswith("javascript:"):
                real_hrefs.append(urljoin(base_url, href))
                
    recovered = []
    for ext_url in raw_urls:
        abs_ext_url = urljoin(base_url, ext_url)
        if abs_ext_url in real_hrefs:
            recovered.append(abs_ext_url)
            continue
            
        parsed = urlparse(abs_ext_url)
        path = parsed.path.strip("/")
        if not path:
            recovered.append(abs_ext_url)
            continue
            
        segments = [s for s in path.split("/") if s]
        if not segments:
            recovered.append(abs_ext_url)
            continue
            
        target_segment = segments[-1]
        
        matched = None
        for real_href in real_hrefs:
            parsed_real = urlparse(real_href)
            real_path = parsed_real.path.lower()
            if target_segment.lower() in real_path:
                if "/job/" in real_path or "/details/" in real_path:
                    matched = real_href
                    break
                matched = real_href
                
        if matched:
            logger.info(f"RootAgent URL Recovery: Fixed malformed URL '{abs_ext_url}' -> '{matched}'")
            recovered.append(matched)
        else:
            recovered.append(abs_ext_url)
            
    final_urls = list(dict.fromkeys(recovered))
    logger.info(f"RootAgent validation complete. Final recovered URLs count: {len(final_urls)}")
    
    # Completeness self-healing decision: for large sites, if less than 5 links are fetched when there are multiple pages, mark as invalid to trigger re-sniffing.
    is_valid = True
    error_msg = None
    
    if len(final_urls) < 5 and state.get("assigned_agent") in ["api", "playwright"]:
        is_valid = False
        error_msg = f"URL count too low ({len(final_urls)}), likely pagination click/API fetch failed."
        logger.warning(f"RootAgent: Validation failed: {error_msg}. Will trigger Self-Healing.")
        
    return {
        "final_urls": final_urls,
        "is_successful": is_valid,
        "error_message": error_msg
    }
