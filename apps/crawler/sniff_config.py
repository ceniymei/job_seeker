import argparse
import logging
from shared.config import config
from shared.database import init_db, get_db_session
from shared.models import Company
from apps.crawler.agents.root_agent import sniff_traffic_and_decision

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("config_sniffer")

def sniff_company_config(company_name: str, homepage_url: str, company_config: dict):
    logger.info(f"=== Starting Config Sniffing for {company_name} ===")
    
    # Construct initial state needed for ParentCrawlState, bypassing database queries
    state = {
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
        # 1. Force LLM network sniffing and identification decision (launch Playwright directly and intercept traffic)
        decision_result = sniff_traffic_and_decision(state)
        new_cfg = decision_result.get("crawl_config")
        
        if new_cfg:
            # The purpose of manual sniffing trigger is to force-update or overwrite the existing configuration, hence write directly to the database
            with get_db_session() as session:
                db_company = session.query(Company).filter(Company.name == company_name).first()
                if not db_company:
                    logger.info(f"Creating missing company record in DB: {company_name}")
                    db_company = Company(name=company_name, homepage_url=homepage_url, is_active=True)
                    session.add(db_company)
                    session.flush()
                
                db_company.crawl_config = new_cfg
                session.commit()
                
            logger.info(f"Successfully sniffed and updated config for {company_name} in DB: {new_cfg}")
        else:
            logger.error(f"Failed to generate configuration for {company_name}: LLM did not return any config.")
    except Exception as e:
        logger.error(f"Sniffing crashed for {company_name}: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="Force sniff pagination and cookie configuration for companies")
    parser.add_argument("--company", type=str, help="Specific company name to sniff")
    args = parser.parse_args()
    
    logger.info("Initializing Database...")
    init_db()
    
    companies = config.companies
    if not companies:
        logger.warning("No companies configured in config.yaml.")
        return
        
    target_name = args.company
    if target_name:
        matched = [c for c in companies if c["name"].lower() == target_name.lower()]
        if not matched:
            logger.error(f"No matched company found in config.yaml for: {target_name}")
            return
        companies_to_sniff = matched
    else:
        companies_to_sniff = companies
        
    logger.info(f"Found {len(companies_to_sniff)} companies to sniff.")
    for company_cfg in companies_to_sniff:
        name = company_cfg["name"]
        url = company_cfg["url"]
        try:
            sniff_company_config(name, url, company_cfg)
        except Exception as e:
            logger.error(f"Failed to process config sniffing for {name}: {str(e)}")

if __name__ == "__main__":
    main()
