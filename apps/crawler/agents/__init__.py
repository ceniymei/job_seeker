from typing import TypedDict, List, Dict, Any, Optional

class ParentCrawlState(TypedDict):
    """State definition of the top-level coordination workflow"""
    company_name: str
    homepage_url: str
    company_config: Dict[str, Any]
    crawl_config: Dict[str, Any]
    
    homepage_html: str
    network_traffic: List[Dict[str, Any]]
    
    assigned_agent: str                # "api" | "playwright" | "traditional" | "none"
    history: List[Dict[str, Any]]      # Record feedback from each agent run
    
    raw_urls: List[str]
    final_urls: List[str]
    
    is_successful: bool
    sniff_attempts: int
    error_message: Optional[str]
