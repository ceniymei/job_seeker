import logging
import httpx
from typing import Dict, Any, List
import re

logger = logging.getLogger("job_seeker_crawler.agents.api_agent")

def run_api_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """Direct API Sub-Agent logic, focusing on calling APIs and extracting job URLs"""
    logger.info(f"APIProtocolAgent started for: {state['company_name']}")
    
    crawl_config = state.get("crawl_config") or {}
    url_template = crawl_config.get("url_template")
    
    if not url_template:
        return {
            "error_message": "No API URL template found in crawl config.",
            "is_successful": False
        }
        
    downloader_cfg = state.get("company_config", {}).get("downloader", {})
    max_pages = int(downloader_cfg.get("max_pages", 5))
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    raw_urls = []
    success_pages = 0
    
    with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as client:
        for page_idx in range(1, max_pages + 1):
            try:
                # Support replacing {page} placeholder
                page_url = url_template.replace("{page}", str(page_idx))
            except Exception:
                page_url = url_template
                
            logger.info(f"APIProtocolAgent calling API page {page_idx}: {page_url}")
            
            try:
                response = client.get(page_url)
                if response.status_code >= 400:
                    logger.warning(f"API returned status {response.status_code} for page {page_idx}")
                    break
                    
                try:
                    data = response.json()
                except Exception:
                    logger.warning(f"API response is not valid JSON on page {page_idx}. Trying regex HTML extraction...")
                    found = re.findall(r'(https?://[^\s\'"]+|/[^\s\'"]+)', response.text)
                    page_urls = [u for u in found if "/job/" in u or "/position/" in u]
                    if not page_urls:
                        break
                    raw_urls.extend(page_urls)
                    success_pages += 1
                    continue
                
                # Deep scan JSON for URLs
                def scan_json(val: Any) -> List[str]:
                    found_urls = []
                    if isinstance(val, dict):
                        for k, v in val.items():
                            if isinstance(v, (dict, list)):
                                found_urls.extend(scan_json(v))
                            elif isinstance(v, str):
                                if "/job/" in v or "/position/" in v or v.startswith("http"):
                                    found_urls.append(v)
                    elif isinstance(val, list):
                        for item in val:
                            found_urls.extend(scan_json(item))
                    return found_urls
                
                page_urls = scan_json(data)
                
                if not page_urls:
                    logger.info(f"No job URLs found in JSON response of page {page_idx}. Stopping API loop.")
                    break
                    
                logger.info(f"APIProtocolAgent extracted {len(page_urls)} URLs from page {page_idx}")
                raw_urls.extend(page_urls)
                success_pages += 1
                
            except Exception as e:
                logger.error(f"APIProtocolAgent request error on page {page_idx}: {str(e)}")
                return {
                    "error_message": f"API request failed on page {page_idx}: {str(e)}",
                    "is_successful": False
                }
                
    if success_pages == 0:
        return {
            "error_message": "Failed to fetch any API pages.",
            "is_successful": False
        }
        
    unique_urls = list(dict.fromkeys(raw_urls))
    logger.info(f"APIProtocolAgent successfully completed. Collected {len(unique_urls)} unique URLs.")
    
    return {
        "raw_urls": unique_urls,
        "is_successful": True,
        "history_record": {
            "agent": "api",
            "success": True,
            "pages_fetched": success_pages,
            "urls_collected": len(unique_urls)
        }
    }
