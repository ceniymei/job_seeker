import logging
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END

from apps.crawler.agents import ParentCrawlState
from apps.crawler.agents.root_agent import sniff_traffic_and_decision, validate_and_recover_urls
from apps.crawler.agents.api_agent import run_api_agent
from apps.crawler.agents.playwright_agent import run_playwright_agent
from apps.crawler.agents.traditional_agent import run_traditional_agent

from shared.database import get_db_session
from shared.models import Company

logger = logging.getLogger("job_seeker_crawler.agents.workflow")

# ==========================================
# 1. Define Node Functions in State Graph
# ==========================================

def fetch_and_decide_node(state: ParentCrawlState) -> Dict[str, Any]:
    """Check cache or execute traffic sniffing decision node"""
    company_name = state["company_name"]
    homepage_url = state["homepage_url"]
    
    # 1. Try to load persisted configuration from database
    saved_cfg = None
    with get_db_session() as session:
        db_company = session.query(Company).filter(Company.name == company_name).first()
        if db_company:
            saved_cfg = db_company.crawl_config
            
    # If cache exists in database
    if saved_cfg:
        logger.info(f"Workflow: Loaded cached crawl config for {company_name}: {saved_cfg}")
        
        # Semantic validity check: verify if the cached selector points to a numeric page button
        cached_sel = saved_cfg.get("next_page_selector")
        need_re_sniff = False
        if cached_sel:
            try:
                # Lightweight fetch of homepage HTML for BeautifulSoup validation
                from shared.downloader import downloader
                from bs4 import BeautifulSoup
                homepage_html = downloader.fetch_html(homepage_url)
                soup = BeautifulSoup(homepage_html, "html.parser")
                elements = soup.select(cached_sel)
                if elements:
                    first_el = elements[0]
                    el_text = first_el.get_text(strip=True)
                    el_aria = first_el.get("aria-label") or ""
                    if el_text.isdigit() or ("page" in el_aria.lower() and any(c.isdigit() for c in el_aria) and "next" not in el_aria.lower()):
                        logger.warning(f"Workflow: Cached next_page_selector '{cached_sel}' targets a numeric page button. Evicting cache...")
                        need_re_sniff = True
            except Exception as e:
                logger.warning(f"Workflow: Error validating cached selector '{cached_sel}': {str(e)}")
                
        # Verify if url_template contains ellipsis
        if saved_cfg.get("url_template") and "..." in saved_cfg.get("url_template", ""):
            need_re_sniff = True
            
        if not need_re_sniff:
            # Cache is valid; determine Sub-Agent and route based on cache
            pag_type = str(saved_cfg.get("pagination_type") or "none").lower()
            url_template = saved_cfg.get("url_template")
            next_page_selector = saved_cfg.get("next_page_selector")
            
            if pag_type == "api_direct" and url_template:
                assigned_agent = "api"
            elif pag_type == "url_template" and url_template:
                assigned_agent = "traditional"
            elif next_page_selector:
                assigned_agent = "playwright"
            else:
                assigned_agent = "traditional" # Fallback to traditional/single page
                
            return {
                "crawl_config": saved_cfg,
                "assigned_agent": assigned_agent,
                "is_successful": False
            }
            
    # 2. No cache or cache expired, call Root Agent to execute Playwright traffic interception and LLM decision
    decision_result = sniff_traffic_and_decision(state)
    
    # Cache new config in DB only when decision succeeds and config is valid, preventing re-sniffing next time
    new_cfg = decision_result.get("crawl_config")
    if new_cfg and new_cfg.get("is_paginated"):
        with get_db_session() as session:
            db_company = session.query(Company).filter(Company.name == company_name).first()
            if db_company:
                db_company.crawl_config = new_cfg
                session.flush()
                logger.info(f"Workflow: Successfully cached new crawl config for {company_name} in DB.")
                
    return decision_result

def api_agent_node(state: ParentCrawlState) -> Dict[str, Any]:
    """Direct API Sub-Agent execution node"""
    return run_api_agent(state)

def playwright_agent_node(state: ParentCrawlState) -> Dict[str, Any]:
    """Browser emulation Sub-Agent execution node"""
    return run_playwright_agent(state)

def traditional_agent_node(state: ParentCrawlState) -> Dict[str, Any]:
    """Traditional URL template Sub-Agent execution node"""
    return run_traditional_agent(state)

def validation_node(state: ParentCrawlState) -> Dict[str, Any]:
    """URL physical restoration and result validity validation node"""
    result = validate_and_recover_urls(state)
    
    # If physical validation fails and self-healing needs to be triggered, increment retry count in this node
    if not result.get("is_successful", False):
        result["sniff_attempts"] = state.get("sniff_attempts", 0) + 1
        
    return result


# ==========================================
# 2. Define Conditional Edges in State Graph
# ==========================================

def route_to_worker(state: ParentCrawlState) -> str:
    """Dispatch task to corresponding specialized Sub-Agent based on Root Agent decision"""
    agent = state.get("assigned_agent")
    if agent == "api":
        return "api_agent"
    elif agent == "playwright":
        return "playwright_agent"
    elif agent == "traditional":
        return "traditional_agent"
    return "traditional_agent" # Fallback

def route_after_validation(state: ParentCrawlState) -> str:
    """Routing logic after validation: supports self-healing or normal completion"""
    is_successful = state.get("is_successful", False)
    sniff_attempts = state.get("sniff_attempts", 0)
    
    if is_successful:
        logger.info("Workflow: Verification success! Ending workflow.")
        return END
        
    # If validation fails, but retry limit is not reached (only allow one retry, count equals 1 after increment)
    if sniff_attempts <= 1:
        logger.warning(f"Workflow: Validation failed. Attempt {sniff_attempts} failed. Triggering Self-Healing...")
        # Clear bad cached config in DB to ensure re-sniffing next time
        with get_db_session() as session:
            db_company = session.query(Company).filter(Company.name == state["company_name"]).first()
            if db_company:
                db_company.crawl_config = None
                session.flush()
                logger.info("Workflow: Cleared bad DB crawl config cache to prepare for re-sniffing.")
                
        return "fetch_and_decide"
        
    logger.warning("Workflow: Reached maximum self-healing limit. Ending workflow.")
    return END


# ==========================================
# 3. Build StateGraph Workflow and Expose Entrypoint
# ==========================================

# Create LangGraph graph
workflow = StateGraph(ParentCrawlState)

# Register all nodes
workflow.add_node("fetch_and_decide", fetch_and_decide_node)
workflow.add_node("api_agent", api_agent_node)
workflow.add_node("playwright_agent", playwright_agent_node)
workflow.add_node("traditional_agent", traditional_agent_node)
workflow.add_node("validation", validation_node)

# Set default entry point
workflow.set_entry_point("fetch_and_decide")

# Register conditional edges (dispatch routing)
workflow.add_conditional_edges(
    "fetch_and_decide",
    route_to_worker,
    {
        "api_agent": "api_agent",
        "playwright_agent": "playwright_agent",
        "traditional_agent": "traditional_agent"
    }
)

# Route all worker outputs to the top-level validation node
workflow.add_edge("api_agent", "validation")
workflow.add_edge("playwright_agent", "validation")
workflow.add_edge("traditional_agent", "validation")

# Register conditional edges (validation self-healing)
workflow.add_conditional_edges(
    "validation",
    route_after_validation,
    {
        "fetch_and_decide": "fetch_and_decide",
        END: END
    }
)

# Compile Graph instance
app = workflow.compile()

def run_multi_agent_crawler(company_name: str, homepage_url: str, company_config: Dict[str, Any]) -> List[str]:
    """Exposed entrypoint to start the multi-agent graph workflow"""
    logger.info(f"=== RootAgent orchestrating Multi-Agent Workflow for {company_name} ===")
    
    initial_state = {
        "company_name": company_name,
        "homepage_url": homepage_url,
        "company_config": company_config,
        "homepage_html": "",
        "network_traffic": [],
        "assigned_agent": "none",
        "history": [],
        "raw_urls": [],
        "final_urls": [],
        "is_successful": False,
        "sniff_attempts": 0,
        "error_message": None
    }
    
    try:
        final_state = app.invoke(initial_state)
        return final_state.get("final_urls") or []
    except Exception as e:
        logger.error(f"Multi-Agent Workflow execution crashed: {str(e)}")
        # Fallback: return empty list on exception
        return []
