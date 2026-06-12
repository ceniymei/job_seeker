import os
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin
from sqlalchemy.orm import Session
from shared.config import config
from shared.database import init_db, get_db_session
from shared.models import Company, Job, CrawlLog
from shared.deduplicator import deduplicator
from shared.downloader import downloader
from apps.crawler.agents.workflow import run_multi_agent_crawler

def utc_now() -> datetime:
    """Returns current UTC time matching SQLAlchemy Naive DateTime, avoiding Python 3.12 deprecation warning"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Configure global logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("job_seeker_crawler")

def get_or_create_company(session: Session, name: str, homepage_url: str) -> Company:
    company = session.query(Company).filter(Company.name == name).first()
    if not company:
        logger.info(f"Creating new company record for {name} in database.")
        company = Company(name=name, homepage_url=homepage_url, is_active=True)
        session.add(company)
        session.flush()
    else:
        if company.homepage_url != homepage_url:
            company.homepage_url = homepage_url
            session.flush()
    return company

def process_company_crawler(session: Session, company_config: dict):
    name = company_config["name"]
    homepage_url = company_config["url"]

    logger.info(f"=== Starting Crawling Process for Company: {name} ===")
    crawl_start_time = utc_now()

    company = get_or_create_company(session, name, homepage_url)
    company_id = company.id

    # 1. Fetch homepage HTML (used for deduplication check)
    try:
        homepage_html = downloader.fetch_html(homepage_url)
    except Exception as e:
        logger.error(f"Failed to fetch homepage for {name}: {str(e)}")
        deduplicator.log_crawl(homepage_url, "", "failed", error_message=str(e), session=session)
        return

    # 2. Deduplication check
    if deduplicator.is_list_page_unchanged(homepage_url, homepage_html, session=session):
        logger.info(f"No changes detected on {name}'s career homepage. Skipping detail processing.")
        session.query(Job).filter(
            Job.company_id == company_id,
            Job.status == "active"
        ).update({Job.last_seen_at: utc_now()})
        deduplicator.log_crawl(homepage_url, homepage_html, "success", session=session)
        return

    # 3. Run multi-agent directed graph workflow
    try:
        raw_urls = run_multi_agent_crawler(name, homepage_url, company_config)
    except Exception as e:
        logger.error(f"Multi-Agent Workflow execution crashed for {name}: {str(e)}")
        deduplicator.log_crawl(homepage_url, homepage_html, "failed", error_message=str(e), session=session)
        return

    logger.info(f"Total unique job URLs collected: {len(raw_urls)} across all pages.")

    if not raw_urls:
        logger.warning(f"No job URLs extracted from {name} via Multi-Agent Workflow.")
        deduplicator.log_crawl(homepage_url, homepage_html, "failed", error_message="No job URLs extracted via Multi-Agent Workflow", session=session)
        return

    deduplicator.log_crawl(homepage_url, homepage_html, "success", session=session)

    # 7. Compare jobs and save to database
    new_jobs_count = 0
    existing_jobs_count = 0

    for raw_url in raw_urls:
        job_url = urljoin(homepage_url, raw_url)

        if deduplicator.is_job_url_exists(job_url, session=session):
            session.query(Job).filter(Job.job_url == job_url).update({
                Job.last_seen_at: utc_now(),
                Job.status: "active"
            })
            existing_jobs_count += 1
            continue

        logger.info(f"Found new job URL: {job_url}. Adding as pending detail task...")
        try:
            new_job = Job(
                company_id=company_id,
                title="Unknown Position",
                location="Unknown Location",
                job_url=job_url,
                status="active",
                detail_status="pending",
                first_seen_at=utc_now(),
                last_seen_at=utc_now()
            )
            session.add(new_job)
            session.flush()
            new_jobs_count += 1
            logger.info(f"Successfully added pending job URL: {job_url}")
        except Exception as ex:
            logger.error(f"Error adding job record for {job_url}: {str(ex)}")
            continue

    logger.info(f"Crawl summary for {name}: {new_jobs_count} new pending jobs, {existing_jobs_count} updated existing jobs.")

    # 8. Mark closed positions
    closed_count = session.query(Job).filter(
        Job.company_id == company_id,
        Job.status == "active",
        Job.last_seen_at < crawl_start_time
    ).update({Job.status: "closed"}, synchronize_session=False)

    if closed_count > 0:
        logger.info(f"Marked {closed_count} expired positions as 'closed' for {name}.")

def export_active_jobs_to_json(session: Session):
    if not config.export_json:
        return

    logger.info("Exporting active jobs to JSON...")
    active_jobs = session.query(Job).filter(Job.status == "active").all()

    output_data = []
    for job in active_jobs:
        output_data.append({
            "id": job.id,
            "company": job.company.name,
            "title": job.title,
            "department": job.department,
            "location": job.location,
            "salary": job.salary,
            "job_url": job.job_url,
            "description": job.description,
            "first_seen": job.first_seen_at.isoformat(),
            "last_seen": job.last_seen_at.isoformat()
        })

    os.makedirs(config.export_dir, exist_ok=True)
    export_path = os.path.join(config.export_dir, "active_jobs.json")

    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Successfully exported {len(output_data)} active jobs to {export_path}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run the job seeker crawler scraper")
    parser.add_argument("--company", type=str, help="Specific company name to crawl")
    args = parser.parse_args()

    logger.info("Initializing Database...")
    init_db()

    companies = config.companies
    if not companies:
        logger.warning("No active companies configured in config.yaml. Exiting.")
        return

    target_name = args.company
    if target_name:
        matched = [c for c in companies if c["name"].lower() == target_name.lower()]
        if not matched:
            logger.error(f"No matched company found in config.yaml for: {target_name}")
            return
        companies_to_crawl = matched
    else:
        companies_to_crawl = [c for c in companies if c.get("is_active", True)]

    logger.info(f"Found {len(companies_to_crawl)} active companies to crawl.")

    with get_db_session() as session:
        for company_cfg in companies_to_crawl:
            try:
                process_company_crawler(session, company_cfg)
            except Exception as e:
                logger.error(f"Error crawling company {company_cfg.get('name')}: {str(e)}")
                continue

        try:
            export_active_jobs_to_json(session)
        except Exception as e:
            logger.error(f"Failed to export jobs to JSON: {str(e)}")

if __name__ == "__main__":
    main()
