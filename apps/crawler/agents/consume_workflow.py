import logging
import json
from typing import Dict, Any, List, Optional, TypedDict
from bs4 import BeautifulSoup
from langgraph.graph import StateGraph, END

from shared.database import get_db_session
from shared.downloader import downloader
from shared.models import Job
from shared.deduplicator import deduplicator
from apps.crawler.scraper import scraper
from apps.crawler.agents.root_agent import get_llm

logger = logging.getLogger("job_seeker_crawler.agents.consume_workflow")

# 1. State Definition
# ==========================================

class DetailConsumeState(TypedDict):
    job_id: int
    job_url: str
    
    # State and HTML
    html_content: str
    is_valid_page: bool
    page_type: str                   # "detail" | "404" | "list" | "home" | "invalid"
    
    # Raw extracted results from LLM
    extracted_details: Dict[str, Any]
    is_extraction_valid: bool
    
    # Data standardization results
    standardized_details: Dict[str, Any]
    
    # Execution logs and errors
    retry_attempts: int
    error_message: Optional[str]
    status: str                      # "completed" | "failed"


# 2. Node Definitions
# ==========================================

def fetch_and_validate_page_node(state: DetailConsumeState) -> Dict[str, Any]:
    """Fetch page physically, pre-validating 404/invalid/redirected pages"""
    url = state["job_url"]
    job_id = state["job_id"]
    logger.info(f"[Job {job_id}] Fetching and validating page: {url}")
    
    try:
        detail_html = downloader.fetch_html(url)
        if not detail_html or len(detail_html) < 1000:
            return {
                "html_content": detail_html or "",
                "is_valid_page": False,
                "page_type": "invalid",
                "error_message": "Fetched HTML content is empty or too small."
            }
            
        soup = BeautifulSoup(detail_html, "html.parser")
        title_text = (soup.title.string or "") if soup.title else ""
        body_text = soup.get_text(strip=True).lower()
        
        # Physical/semantic pre-interception of 404
        is_404 = "404" in title_text or "not found" in title_text.lower() or "page not found" in body_text
        is_expired = "no longer available" in body_text or "position closed" in body_text
        
        # Determine if redirected to homepage/listing page
        is_list_page = "search jobs" in title_text.lower() or "find jobs" in title_text.lower() or "careers" in title_text.lower() and not title_text.strip().replace("Careers", "")
        
        if is_404:
            page_type = "404"
            is_valid = False
            error = "Page returned 404 (Not Found)"
        elif is_expired:
            page_type = "invalid"
            is_valid = False
            error = "Job post is no longer active or expired"
        elif is_list_page:
            page_type = "list"
            is_valid = False
            error = "Redirected to job list or careers home page"
        else:
            page_type = "detail"
            is_valid = True
            error = None
            
        if not is_valid:
            logger.warning(f"[Job {job_id}] Validation failed: {error}")
            
        return {
            "html_content": detail_html,
            "is_valid_page": is_valid,
            "page_type": page_type,
            "error_message": error
        }
    except Exception as e:
        logger.error(f"[Job {job_id}] Exception during fetch: {str(e)}")
        return {
            "html_content": "",
            "is_valid_page": False,
            "page_type": "invalid",
            "error_message": f"Fetch crashed: {str(e)}"
        }

def extract_details_node(state: DetailConsumeState) -> Dict[str, Any]:
    """LLM-based structured details extraction"""
    job_id = state["job_id"]
    html = state["html_content"]
    url = state["job_url"]
    attempts = state.get("retry_attempts", 0)
    
    logger.info(f"[Job {job_id}] Invoking LLM for details extraction (attempt {attempts + 1})...")
    
    try:
        job_details = scraper.extract_job_details(html, url)
        return {
            "extracted_details": job_details,
            "error_message": None
        }
    except Exception as e:
        logger.error(f"[Job {job_id}] Extraction failed: {str(e)}")
        return {
            "extracted_details": {},
            "error_message": f"Extraction exception: {str(e)}"
        }

def validate_details_node(state: DetailConsumeState) -> Dict[str, Any]:
    """Quality and sanity check of LLM extracted results"""
    job_id = state["job_id"]
    extracted = state.get("extracted_details") or {}
    title = extracted.get("title") or ""
    desc = extracted.get("description") or ""
    attempts = state.get("retry_attempts", 0)
    
    is_valid = True
    err = None
    
    if not title or title.lower() in ["unknown", "unknown position", "n/a", "na", ""]:
        is_valid = False
        err = "Extracted title is missing or unknown"
    elif len(desc) < 50:
        is_valid = False
        err = f"Extracted description is too short ({len(desc)} characters)"
        
    result = {
        "is_extraction_valid": is_valid,
        "error_message": err
    }
    
    # If quality is unacceptable, and not in retry-terminal state, increment retry count in Node (write back to State)
    if not is_valid:
        result["retry_attempts"] = attempts + 1
        
    return result

def standardize_details_node(state: DetailConsumeState) -> Dict[str, Any]:
    """LLM node to standardize Location and Salary data"""
    job_id = state["job_id"]
    extracted = state.get("extracted_details") or {}
    raw_location = extracted.get("location") or ""
    raw_salary = extracted.get("salary") or ""
    
    logger.info(f"[Job {job_id}] Normalizing Location: '{raw_location}' and Salary: '{raw_salary}'...")
    
    prompt = (
        "You are an expert recruitment data normalizer. Your job is to parse and clean raw location and salary strings into a standardized JSON format.\n"
        "Analyze the inputs and return a strictly structured JSON without any markdown code block wrapper (no ```json code blocks), containing these keys:\n"
        "1. country (string/null): Standardized English country name (e.g. 'United States', 'China', 'United Kingdom'), or null.\n"
        "2. city (string/null): Standardized city name (e.g. 'Atlanta', 'London', 'Shanghai'), or null.\n"
        "3. state (string/null): Standardized state/province code or name (e.g. 'GA', 'Guangdong', 'England'), or null.\n"
        "4. is_remote (boolean/string): True if the job is explicitly remote or work from home. False if it is on-site or hybrid. If not mentioned or unclear, set to 'Unknown'.\n"
        "5. min_amount (number/null): Minimum salary amount as a number (e.g. 88400), or null.\n"
        "6. max_amount (number/null): Maximum salary amount as a number (e.g. 105000), or null.\n"
        "7. currency (string/null): Standardized 3-letter currency code (e.g. 'USD', 'CNY', 'GBP'), or null.\n"
        "8. period (string/null): One of 'yearly', 'monthly', 'hourly', or null.\n\n"
        f"Input Location: {raw_location}\n"
        f"Input Salary: {raw_salary}\n"
    )
    
    standard_data = {
        "location": {
            "country": None,
            "city": None,
            "state": None,
            "is_remote": "Unknown"
        },
        "salary": {
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "period": None
        }
    }
    
    try:
        llm = get_llm()
        response = llm.invoke(prompt)
        raw_result = response.content.strip()
        
        if "{" in raw_result:
            raw_result = raw_result[raw_result.find("{"):raw_result.rfind("}")+1]
            
        decision = json.loads(raw_result)
        
        # Populate standardized Location
        standard_data["location"]["country"] = decision.get("country")
        standard_data["location"]["city"] = decision.get("city")
        standard_data["location"]["state"] = decision.get("state")
        
        is_remote_val = decision.get("is_remote")
        if isinstance(is_remote_val, bool):
            standard_data["location"]["is_remote"] = is_remote_val
        elif str(is_remote_val).lower() == "true":
            standard_data["location"]["is_remote"] = True
        elif str(is_remote_val).lower() == "false":
            standard_data["location"]["is_remote"] = False
        else:
            standard_data["location"]["is_remote"] = "Unknown"
            
        # Populate standardized Salary
        standard_data["salary"]["min_amount"] = decision.get("min_amount")
        standard_data["salary"]["max_amount"] = decision.get("max_amount")
        standard_data["salary"]["currency"] = decision.get("currency")
        standard_data["salary"]["period"] = decision.get("period")
        
        logger.info(f"[Job {job_id}] Normalization complete: {standard_data}")
    except Exception as e:
        logger.error(f"[Job {job_id}] Normalization failed: {str(e)}")
        
    return {
        "standardized_details": standard_data
    }

def save_to_db_node(state: DetailConsumeState) -> Dict[str, Any]:
    """Unified transactional saving node, safely writing back to database concurrently"""
    job_id = state["job_id"]
    is_valid_page = state.get("is_valid_page", False)
    is_extraction_valid = state.get("is_extraction_valid", False)
    extracted = state.get("extracted_details") or {}
    standardized = state.get("standardized_details") or {}
    error_msg = state.get("error_message")
    
    logger.info(f"[Job {job_id}] Saving pipeline results to DB...")
    
    final_status = "failed"
    if is_valid_page and is_extraction_valid:
        final_status = "completed"
        
    try:
        with get_db_session() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                return {
                    "status": "failed",
                    "error_message": "Job record missing"
                }
                
            if final_status == "completed":
                job.title = extracted.get("title")
                job.department = extracted.get("department")
                job.location = extracted.get("location")
                job.salary = extracted.get("salary")
                job.description = extracted.get("description")
                job.raw_metadata = extracted.get("raw_metadata")
                
                # Write standardized columns
                job.location_standard = standardized.get("location")
                job.salary_standard = standardized.get("salary")
                job.detail_status = "completed"
                
                deduplicator.log_crawl(state["job_url"], state.get("html_content") or "", "success", session=session)
                logger.info(f"[Job {job_id}] Marked as completed: '{job.title}'")
            else:
                job.detail_status = "failed"
                deduplicator.log_crawl(state["job_url"], "", "failed", error_message=error_msg or "Validation/Extraction failed", session=session)
                logger.warning(f"[Job {job_id}] Marked as failed: {error_msg}")
                
        return {
            "status": final_status
        }
    except Exception as e:
        logger.error(f"[Job {job_id}] Database commit exception: {str(e)}")
        return {
            "status": "failed",
            "error_message": f"DB Exception: {str(e)}"
        }


# 3. Route Edges Definition
# ==========================================

def route_after_fetch(state: DetailConsumeState) -> str:
    """Pre-validation result determines whether to proceed to LLM extraction or terminate directly"""
    if state.get("is_valid_page", False):
        return "extract_details"
    return "save_to_db"

def route_after_validation(state: DetailConsumeState) -> str:
    """Sanity check routing: valid goes to standardization, invalid triggers retry or exit"""
    is_valid = state.get("is_extraction_valid", False)
    attempts = state.get("retry_attempts", 0)
    
    if is_valid:
        return "standardize_details"
        
    # If invalid, and retry count <= 1 (only 1 retry allowed)
    if attempts <= 1:
        return "extract_details"
        
    return "save_to_db"


# 4. StateGraph Construction and Entry Points Exposure
# ==========================================

workflow = StateGraph(DetailConsumeState)

workflow.add_node("fetch_and_validate", fetch_and_validate_page_node)
workflow.add_node("extract_details", extract_details_node)
workflow.add_node("validate_details", validate_details_node)
workflow.add_node("standardize_details", standardize_details_node)
workflow.add_node("save_to_db", save_to_db_node)

workflow.set_entry_point("fetch_and_validate")

workflow.add_conditional_edges(
    "fetch_and_validate",
    route_after_fetch,
    {
        "extract_details": "extract_details",
        "save_to_db": "save_to_db"
    }
)

workflow.add_edge("extract_details", "validate_details")

workflow.add_conditional_edges(
    "validate_details",
    route_after_validation,
    {
        "standardize_details": "standardize_details",
        "extract_details": "extract_details",
        "save_to_db": "save_to_db"
    }
)

workflow.add_edge("standardize_details", "save_to_db")
workflow.add_edge("save_to_db", END)

app = workflow.compile()

def run_consume_workflow(job_id: int, job_url: str) -> Dict[str, Any]:
    """Main entry point to invoke the detail multi-agent consume workflow from external modules"""
    initial_state = {
        "job_id": job_id,
        "job_url": job_url,
        "html_content": "",
        "is_valid_page": False,
        "page_type": "invalid",
        "extracted_details": {},
        "is_extraction_valid": False,
        "standardized_details": {},
        "retry_attempts": 0,
        "error_message": None,
        "status": "failed"
    }
    
    try:
        final_state = app.invoke(initial_state)
        return final_state
    except Exception as e:
        logger.error(f"[Job {job_id}] Consume workflow invoke crashed: {str(e)}")
        # Extreme crash self-healing logic: ensure marked as failed without hanging the process
        try:
            with get_db_session() as session:
                job = session.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.detail_status = "failed"
                    deduplicator.log_crawl(job_url, "", "failed", error_message=f"Orchestration crash: {str(e)}", session=session)
        except Exception:
            pass
        return {"status": "failed", "error_message": f"Orchestrator error: {str(e)}"}
