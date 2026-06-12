import re
import hashlib
import logging
from sqlalchemy import desc
from shared.database import get_db_session
from shared.models import CrawlLog, Job

logger = logging.getLogger(__name__)

class Deduplicator:
    """Deduplication and page fingerprint management module"""

    @staticmethod
    def calculate_text_hash(html_content: str) -> str:
        if not html_content:
            return ""
        
        clean_text = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', html_content, flags=re.I)
        clean_text = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>', '', clean_text, flags=re.I)
        clean_text = re.sub(r'<[^>]+>', ' ', clean_text)
        clean_text = " ".join(clean_text.split())
        return hashlib.sha256(clean_text.encode('utf-8')).hexdigest()

    def is_list_page_unchanged(self, url: str, html_content: str, session=None) -> bool:
        current_hash = self.calculate_text_hash(html_content)
        if not current_hash:
            return False

        if session is not None:
            return self._check_list_unchanged(session, url, current_hash)
        with get_db_session() as s:
            return self._check_list_unchanged(s, url, current_hash)

    def _check_list_unchanged(self, session, url, current_hash) -> bool:
        last_log = session.query(CrawlLog)\
            .filter(CrawlLog.target_url == url, CrawlLog.status == "success")\
            .order_by(desc(CrawlLog.crawled_at))\
            .first()

        if last_log and last_log.html_hash == current_hash:
            logger.info(f"Page content hash matched for {url}. Skipping LLM parsing.")
            return True
        
        logger.info(f"Page content hash changed or no previous log found for {url}.")
        return False

    def is_job_url_exists(self, job_url: str, session=None) -> bool:
        if session is not None:
            return self._check_job_exists(session, job_url)
        with get_db_session() as s:
            return self._check_job_exists(s, job_url)

    def _check_job_exists(self, session, job_url) -> bool:
        exists = session.query(Job.id).filter(Job.job_url == job_url).first() is not None
        if exists:
            logger.debug(f"Job URL already exists in database: {job_url}")
        return exists

    def log_crawl(self, url: str, html_content: str, status: str, error_message: str = None, session=None):
        html_hash = self.calculate_text_hash(html_content) if status == "success" else None
        log = CrawlLog(
            target_url=url,
            html_hash=html_hash,
            status=status,
            error_message=error_message
        )
        
        if session is not None:
            session.add(log)
        else:
            with get_db_session() as s:
                s.add(log)
        logger.debug(f"Logged crawl result for {url} with status {status}")

deduplicator = Deduplicator()
