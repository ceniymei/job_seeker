import os
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from shared.config import config
from shared.database import init_db, get_db_session
from shared.models import Job
from apps.crawler.agents.consume_workflow import run_consume_workflow

# Configure global logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("detail_consumer")

def process_single_job(job_id: int, job_url: str, shutdown_event: threading.Event = None):
    if shutdown_event and shutdown_event.is_set():
        logger.info(f"[Job {job_id}] Shutdown event detected. Skipping.")
        return

    logger.info(f"[Job {job_id}] Starting fetching and LLM extracting for URL: {job_url}")
    
    # 1. Quickly query database to verify if job task is still active and needs parsing
    try:
        with get_db_session() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job or job.status != "active":
                logger.warning(f"[Job {job_id}] Job is no longer active or missing. Skipping.")
                return
            if job.detail_status != "pending":
                logger.info(f"[Job {job_id}] Job detail status is already '{job.detail_status}'. Skipping.")
                return
    except Exception as db_err:
        logger.error(f"[Job {job_id}] Failed to check job status from DB: {str(db_err)}")
        return

    if shutdown_event and shutdown_event.is_set():
        logger.info(f"[Job {job_id}] Shutdown event detected before workflow invocation. Skipping.")
        return

    # 2. Delegate to the directed graph workflow (releasing current DB connection)
    try:
        run_consume_workflow(job_id, job_url)
    except Exception as e:
        logger.error(f"[Job {job_id}] Consume workflow failed with crash: {str(e)}")

def main():
    logger.info("Initializing Database...")
    init_db()
    
    concurrency = int(config.data.get("crawler", {}).get("concurrency_limit", 2))
    logger.info(f"Detail Consumer started with concurrency limit: {concurrency}")
    
    # Retrieve all pending and active jobs
    with get_db_session() as session:
        pending_jobs = (
            session.query(Job)
            .filter(Job.detail_status == "pending", Job.status == "active")
            .all()
        )
        job_tasks = [(j.id, j.job_url) for j in pending_jobs]
        
    if not job_tasks:
        logger.info("No pending job detail tasks found. Exiting.")
        return
        
    logger.info(f"Found {len(job_tasks)} pending job detail tasks to process.")
    
    shutdown_event = threading.Event()
    
    # Register signal handlers to allow graceful shutdown via kill or Ctrl+C
    def signal_handler(signum, frame):
        logger.warning(f"\nSignal {signum} caught. Setting shutdown event to stop all workers gracefully...")
        shutdown_event.set()
        
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Concurrent execution
    try:
        if concurrency > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = []
                for job_id, job_url in job_tasks:
                    if shutdown_event.is_set():
                        break
                    futures.append(executor.submit(process_single_job, job_id, job_url, shutdown_event))
                
                # Poll submitted tasks, using time.sleep to allow the main thread to capture signals and interrupts
                while futures:
                    futures = [f for f in futures if not f.done()]
                    if shutdown_event.is_set():
                        # Attempt to cancel all tasks that have not started execution yet
                        for f in futures:
                            f.cancel()
                        break
                    time.sleep(0.5)
        else:
            for job_id, job_url in job_tasks:
                if shutdown_event.is_set():
                    break
                process_single_job(job_id, job_url, shutdown_event)
    except KeyboardInterrupt:
        logger.warning("\nKeyboardInterrupt caught. Setting shutdown event to stop all workers gracefully...")
        shutdown_event.set()
        
    if shutdown_event.is_set():
        logger.warning("Detail Consumer terminated. Remaining jobs kept as pending.")
    else:
        logger.info("All pending jobs processed.")

if __name__ == "__main__":
    main()
