import logging
import io
import json
import re
import math
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from fastapi import FastAPI, Depends, Query, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader
from sqlalchemy.orm import Session
from shared.database import get_db_session, init_db
from shared.models import Company, Job, CrawlLog
from shared.config import config
from shared.llm import get_llm

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job_seeker_server")

# Initialize database tables on startup
logger.info("Checking database tables...")
init_db()

app = FastAPI(
    title="Job Seeker API",
    description="FastAPI Backend for Job Seeker Monorepo",
    version="1.0.0"
)

# Enable CORS (preparing for React frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    with get_db_session() as session:
        yield session

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "Job Seeker API is running successfully.",
        "docs_url": "/docs"
    }

@app.get("/companies")
def get_companies(db: Session = Depends(get_db)):
    """Retrieve list of all companies"""
    companies = db.query(Company).order_by(Company.name).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "homepage_url": c.homepage_url,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None
        } for c in companies
    ]

@app.get("/jobs")
def get_jobs(
    company_id: Optional[int] = Query(None, description="Filter by company ID"),
    status: Optional[str] = Query("active", description="Job status (active/closed/all)"),
    db: Session = Depends(get_db)
):
    """Retrieve list of jobs"""
    query = db.query(Job)
    
    if company_id:
        query = query.filter(Job.company_id == company_id)
        
    if status and status.lower() != "all":
        query = query.filter(Job.status == status.lower())
        
    jobs = query.order_by(Job.last_seen_at.desc()).all()
    
    return [
        {
            "id": j.id,
            "company_name": j.company.name,
            "company_id": j.company_id,
            "title": j.title,
            "department": j.department,
            "location": j.location,
            "salary": j.salary,
            "description": j.description,
            "job_url": j.job_url,
            "status": j.status,
            "raw_metadata": j.raw_metadata,
            "first_seen_at": j.first_seen_at.isoformat() if j.first_seen_at else None,
            "last_seen_at": j.last_seen_at.isoformat() if j.last_seen_at else None
        } for j in jobs
    ]

@app.get("/logs")
def get_logs(
    limit: int = Query(50, ge=1, le=100, description="Maximum number of logs to return"),
    db: Session = Depends(get_db)
):
    """Retrieve recent crawler logs"""
    logs = db.query(CrawlLog).order_by(CrawlLog.crawled_at.desc()).limit(limit).all()
    return [
        {
            "id": log.id,
            "target_url": log.target_url,
            "html_hash": log.html_hash,
            "status": log.status,
            "error_message": log.error_message,
            "crawled_at": log.crawled_at.isoformat() if log.crawled_at else None
        } for log in logs
    ]


def parse_resume_file(file: UploadFile) -> str:
    filename = file.filename.lower()
    content_bytes = file.file.read()
    
    if filename.endswith(".pdf"):
        pdf_file = io.BytesIO(content_bytes)
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
        return text
    else:
        # Fallback to text parsing (TXT/MD)
        return content_bytes.decode("utf-8", errors="ignore")


def extract_resume_keywords(resume_text: str) -> dict:
    """Extract core job keywords, preferred locations, and negative keywords to exclude using LLM"""
    prompt = (
        "You are a professional job search assistant. Please analyze the following resume content and extract 5-8 core skill or job keywords that best suit the candidate (e.g. python, react, backend, machine learning, etc.). "
        "Analyze their preferred job location(s) (e.g. Singapore, Beijing, etc. Return null if not mentioned). "
        "Also extract mismatching career directions or negative keywords to exclude (e.g. if the candidate is a core developer, they should avoid words related to ['test', 'qa', 'compliance', 'manufacturing', 'hardware', 'support', 'recruiting', 'sales']; if they are a QA engineer, they should avoid ['marketing', 'design'], etc.).\n"
        "Output ONLY a valid JSON object, do not include any markdown code blocks (do NOT use ```json markup), and it must start with '{' and end with '}'. Example format:\n"
        "{\n"
        "  \"keywords\": [\"python\", \"fastapi\", \"backend\"],\n"
        "  \"exclude_keywords\": [\"test\", \"qa\", \"compliance\"],\n"
        "  \"locations\": [\"singapore\"]\n"
        "}\n\n"
        f"Resume content:\n{resume_text[:4000]}"
    )
    
    try:
        llm = get_llm()
        response = llm.invoke(prompt)
        raw_result = response.content.strip()
        
        # Remove markdown code block markers
        if "{" in raw_result:
            raw_result = raw_result[raw_result.find("{"):raw_result.rfind("}")+1]
            
        data = json.loads(raw_result)
        data["keywords"] = [k.lower().strip() for k in data.get("keywords", [])]
        data["exclude_keywords"] = [k.lower().strip() for k in data.get("exclude_keywords", [])]
        data["locations"] = [loc.lower().strip() for loc in data.get("locations", []) if loc]
        return data
    except Exception as e:
        logger.error(f"Failed to extract keywords using LLM: {e}")
        return {"keywords": [], "exclude_keywords": [], "locations": []}


def pre_filter_jobs(db: Session, keywords: List[str], exclude_keywords: List[str], target_locations: List[str], limit: int = 30) -> List[Job]:
    """Pre-filter and score active jobs in database based on keywords, negative keywords, and target locations"""
    all_jobs = db.query(Job).filter(Job.status == "active").all()
    if not all_jobs:
        return []
        
    if not keywords and not target_locations and not exclude_keywords:
        return all_jobs[:limit]
        
    scored_jobs = []
    for job in all_jobs:
        score = 0
        title_lower = (job.title or "").lower()
        desc_lower = (job.description or "").lower()
        dept_lower = (job.department or "").lower()
        loc_lower = (job.location or "").lower()
        
        # 1. Penalty for negative/exclude keywords
        has_exclude = False
        if exclude_keywords:
            for ex_kw in exclude_keywords:
                # Heavy penalty if title contains exclude keyword
                if ex_kw in title_lower:
                    score -= 100
                    has_exclude = True
                # Moderate penalty if description or department contains exclude keyword
                if ex_kw in desc_lower or ex_kw in dept_lower:
                    score -= 30
        
        # 2. Location match
        for target_loc in target_locations:
            if target_loc in loc_lower:
                score += 25
                break
                
        # 3. Keyword match (significantly boost title match weight to reduce noise from descriptions)
        for keyword in keywords:
            if keyword in title_lower:
                score += 45  # Heavily boost Title weight
            if keyword in dept_lower:
                score += 5
            matches = len(re.findall(re.escape(keyword), desc_lower))
            # Limit maximum score from description matches to prevent non-dev roles mentioning dev languages from scoring high
            score += min(matches * 1.5, 8)
            
        scored_jobs.append((score, job))
        
    scored_jobs.sort(key=lambda x: x[0], reverse=True)
    
    # Filter out obviously mismatched roles (e.g., those heavily penalized)
    valid_scored = [j for j in scored_jobs if j[0] > -30]
    return [job for _, job in valid_scored[:limit]]

EMBEDDING_MODEL_NAME = "models/gemini-embedding-2"

import threading

# Global state to track if background embedding generation thread is running
_embedding_generation_lock = threading.Lock()
_embedding_generation_running = False

def _bg_generate_embeddings(db_dsn: str, missing_job_ids: List[int]):
    """Generate missing embeddings in a background thread"""
    global _embedding_generation_running
    logger.info(f"Background embedding generation thread started for {len(missing_job_ids)} jobs.")
    
    try:
        from shared.database import get_db_session
        from shared.models import Job
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        
        embed = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL_NAME,
            google_api_key=config.llm_api_key
        )
        
        batch_size = 50
        for offset in range(0, len(missing_job_ids), batch_size):
            batch_ids = missing_job_ids[offset : offset + batch_size]
            
            with get_db_session() as session:
                # Query job entities in the current thread's session to avoid cross-thread session sharing issues
                batch_jobs = session.query(Job).filter(Job.id.in_(batch_ids)).all()
                if not batch_jobs:
                    continue
                    
                batch_texts = []
                for j in batch_jobs:
                    text = f"{j.title or ''} {j.department or ''} {j.location or ''}\n{(j.description or '')[:1500]}"
                    batch_texts.append(text)
                    
                logger.info(f"Generating embeddings batch {offset // batch_size + 1} ({len(batch_texts)} jobs) in background...")
                vectors = embed.embed_documents(batch_texts)
                
                for j, vec in zip(batch_jobs, vectors):
                    j.embedding = vec
                    j.embedding_model = EMBEDDING_MODEL_NAME
                
                session.commit()
                logger.info(f"Successfully saved background embeddings batch {offset // batch_size + 1} to database.")
    except Exception as e:
        logger.error(f"Failed to generate embeddings in background thread: {e}")
    finally:
        with _embedding_generation_lock:
            _embedding_generation_running = False
        logger.info("Background embedding generation thread finished.")


def get_or_create_job_embeddings(db: Session, jobs: List[Job]) -> dict:
    """Retrieve embeddings or launch a background thread to generate them for active jobs missing embeddings"""
    global _embedding_generation_running
    
    missing_jobs = [
        j for j in jobs
        if j.embedding is None or j.embedding_model != EMBEDDING_MODEL_NAME
    ]
    
    if missing_jobs:
        missing_ids = [j.id for j in missing_jobs]
        logger.info(f"Detecting {len(missing_jobs)} jobs missing/outdated embeddings.")
        
        start_thread = False
        with _embedding_generation_lock:
            if not _embedding_generation_running:
                _embedding_generation_running = True
                start_thread = True
                
        if start_thread:
            # Start background thread without blocking the HTTP request
            t = threading.Thread(
                target=_bg_generate_embeddings,
                args=(config.database_dsn, missing_ids),
                daemon=True
            )
            t.start()
            logger.info("Launched background thread to populate missing embeddings.")
        else:
            logger.info("Background embedding generation is already running. Skipping duplicate thread launch.")
            
    # Use only job embeddings that already exist in DB and match the model
    return {j.id: j.embedding for j in jobs if j.embedding is not None and j.embedding_model == EMBEDDING_MODEL_NAME}


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity"""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude_v1 = math.sqrt(sum(a * a for a in v1))
    magnitude_v2 = math.sqrt(sum(b * b for b in v2))
    if magnitude_v1 == 0 or magnitude_v2 == 0:
        return 0.0
    return dot_product / (magnitude_v1 * magnitude_v2)


def vector_filter_jobs(db: Session, resume_text: str, exclude_keywords: List[str] = None, limit: int = 30) -> List[Job]:
    """Generate resume embedding and perform pre-filtering using cosine similarity in memory"""
    all_jobs = db.query(Job).filter(Job.status == "active").all()
    if not all_jobs:
        return []
        
    # 1. Lazy-load and fill missing embeddings
    id_to_vec = get_or_create_job_embeddings(db, all_jobs)
    
    # 2. Generate resume embedding
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        embed = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL_NAME,
            google_api_key=config.llm_api_key
        )
        resume_vector = embed.embed_query(resume_text)
    except Exception as e:
        logger.error(f"Failed to generate resume embedding: {e}")
        return all_jobs[:limit]
        
    # 3. Calculate similarity in memory
    scored_jobs = []
    for job in all_jobs:
        vec = id_to_vec.get(job.id)
        if vec:
            sim = cosine_similarity(resume_vector, vec)
            
            # Filter vector results using negative/exclude keywords
            if exclude_keywords:
                title_lower = (job.title or "").lower()
                desc_lower = (job.description or "").lower()
                for ex_kw in exclude_keywords:
                    if ex_kw in title_lower:
                        sim -= 0.5  # Heavy penalty
                        break
                    elif ex_kw in desc_lower:
                        sim -= 0.15 # Moderate penalty
            
            scored_jobs.append((sim, job))
            
    scored_jobs.sort(key=lambda x: x[0], reverse=True)
    if scored_jobs:
        logger.info(f"Vector search matched {len(scored_jobs)} jobs. Top similarity score: {scored_jobs[0][0]}")
    return [job for _, job in scored_jobs[:limit]]


def refined_match_jobs(resume_text: str, candidate_jobs: List[Job]) -> List[dict]:
    """Perform parallelized LLM-based refined matching in batches"""
    if not candidate_jobs:
        return []
        
    batch_size = 30
    batches = [candidate_jobs[i : i + batch_size] for i in range(0, len(candidate_jobs), batch_size)]
    
    logger.info(f"Divided candidate pool of {len(candidate_jobs)} jobs into {len(batches)} batches for parallel LLM ranking.")
    
    def process_single_batch(batch_jobs: List[Job], batch_index: int) -> List[dict]:
        jobs_data = []
        for i, job in enumerate(batch_jobs):
            # Preserve the full description to avoid losing qualifications details
            jobs_data.append({
                "index": i + 1,
                "job_id": job.id,
                "title": job.title,
                "company": job.company.name if job.company else "Unknown",
                "location": job.location,
                "department": job.department,
                "salary": job.salary,
                "description": job.description
            })
            
        prompt = (
            "You are a professional senior career advisor and recruiter. Please carefully read the candidate's resume below:\n"
            "------------------\n"
            f"{resume_text[:4000]}\n"
            "------------------\n\n"
            f"Here is batch {batch_index + 1} of candidate jobs pre-filtered from the database:\n"
            f"{json.dumps(jobs_data, ensure_ascii=False, indent=2)}\n\n"
            "Please evaluate the fit of each job position against the candidate's resume. You must strictly compare the following three dimensions and apply strict penalties for mismatches:\n"
            "1. Job Function & Career Intent Alignment (Crucial for preventing mis-matches):\n"
            "   - If the candidate's target role is core backend development/architecture, but the job is in 'Manufacturing Test', 'Security Compliance', 'SRE/Operations', etc., even if the job requires scripting in Python, this is a mismatch! Deduct 35-50 points immediately, and the total match score must not exceed 65!\n"
            "2. Core Tech Stack Alignment:\n"
            "   - If the job primarily requires Java, but the candidate is in the Python ecosystem (or vice versa), deduct 20-30 points even if the other language is briefly mentioned but not their primary tool.\n"
            "3. Years of Experience & Seniority Level Alignment:\n"
            "   - If the candidate has 5+ years of senior experience, but the job is 'Early Careers/Junior/Intern', deduct 15-20 points.\n\n"
            "[Selection & Output Requirements]:\n"
            "- Only select positions with a match score of 70 or higher. Recommend a MAXIMUM of 3 positions per batch. If no positions in this batch match, return an empty array []! Do not force recommendations.\n"
            "- For each recommended job, provide:\n"
            "  1. job_id: Must be the actual integer job_id from the job list (e.g. 815, 235), DO NOT use index/sequence numbers.\n"
            "  2. match_score: An integer between 70 and 100.\n"
            "  3. discrepancies: An array of strings describing misalignment points (e.g. ['Role mismatch (QA)', 'Tech stack mismatch (Java)']). If no mismatch, return an empty array [].\n"
            "  4. reason: A concise analysis in English (100-200 words) explaining why the role is a good fit, combining the job's core responsibilities and the candidate's background.\n\n"
            "Output ONLY a valid JSON array, do not include any markdown code blocks (do NOT use ```json markup), and it must start with '[' and end with ']'. Example format:\n"
            "[\n"
            "  {\n"
            "    \"job_id\": 123,\n"
            "    \"match_score\": 78,\n"
            "    \"discrepancies\": [\"Role focuses on manufacturing test rather than core backend development\"],\n"
            "    \"reason\": \"This role mainly involves maintaining hardware test frameworks. While it requires Python and the candidate is proficient in Python, it deviates from their core career direction of backend services.\"\n"
            "  }\n"
            "]\n"
        )
        
        try:
            logger.info(f"Launching LLM ranking for Batch {batch_index + 1} ({len(batch_jobs)} jobs)...")
            llm = get_llm()
            response = llm.invoke(prompt)
            raw_result = response.content.strip()
            
            if "[" in raw_result:
                raw_result = raw_result[raw_result.find("["):raw_result.rfind("]")+1]
                
            recommendations = json.loads(raw_result)
            
            # Store batch index for accurate mapping recovery
            for r in recommendations:
                r["_batch_index"] = batch_index
            return recommendations
        except Exception as e:
            logger.error(f"Failed to match jobs for Batch {batch_index + 1} using LLM: {e}")
            return []

    # Execute all batches in parallel using thread pool
    results = []
    with ThreadPoolExecutor(max_workers=len(batches)) as executor:
        futures = [executor.submit(process_single_batch, batch, idx) for idx, batch in enumerate(batches)]
        for f in futures:
            results.extend(f.result())
            
    logger.info(f"Concurrent batch ranking completed. Gathered {len(results)} recommendations from all batches.")
    return results


def process_match(resume_text: str, db: Session):
    extracted = extract_resume_keywords(resume_text)
    keywords = extracted.get("keywords", [])
    exclude_keywords = extracted.get("exclude_keywords", [])
    locations = extracted.get("locations", [])
    
    logger.info(f"Extracted resume keywords: {keywords}, exclude_keywords: {exclude_keywords}, locations: {locations}")
    
    # 1. SQL Pre-filtering
    sql_candidates = pre_filter_jobs(db, keywords, exclude_keywords, locations, limit=30)
    logger.info(f"Pre-filtered {len(sql_candidates)} jobs via SQL keyword matching.")
    
    # 2. Vector Pre-filtering
    vector_candidates = vector_filter_jobs(db, resume_text, exclude_keywords, limit=30)
    logger.info(f"Pre-filtered {len(vector_candidates)} jobs via Vector Semantic matching.")
    
    # 3. Hybrid Search Union and Deduplication
    candidate_map = {}
    for job in sql_candidates + vector_candidates:
        candidate_map[job.id] = job
        
    candidate_jobs = list(candidate_map.values())
    logger.info(f"Hybrid search merged pool contains {len(candidate_jobs)} unique jobs.")
    
    if not candidate_jobs:
        return []
        
    # 4. Parallel Refined Match (LLM)
    recommendations = refined_match_jobs(resume_text, candidate_jobs)
    logger.info(f"LLM matching recommendations returned {len(recommendations)} jobs.")
    
    # Map LLM recommendation results back to database IDs based on batch index
    batch_size = 30
    batches = [candidate_jobs[i : i + batch_size] for i in range(0, len(candidate_jobs), batch_size)]
    
    id_map = {}
    for batch_idx, batch in enumerate(batches):
        for i, job in enumerate(batch):
            id_map[(batch_idx, str(i + 1))] = job.id
            id_map[(batch_idx, str(job.id))] = job.id
            
    matched_job_ids = {}
    for rec in recommendations:
        batch_idx = rec.get("_batch_index", 0)
        raw_id_str = str(rec.get("job_id"))
        key = (batch_idx, raw_id_str)
        if key in id_map:
            real_id = id_map[key]
            matched_job_ids[real_id] = rec
        else:
            logger.warning(f"LLM returned unmatched job_id: {raw_id_str} in Batch {batch_idx}")
            
    result = []
    for job in candidate_jobs:
        if job.id in matched_job_ids:
            rec_data = matched_job_ids[job.id]
            result.append({
                "id": job.id,
                "company_name": job.company.name if job.company else "Unknown",
                "company_id": job.company_id,
                "title": job.title,
                "department": job.department,
                "location": job.location,
                "salary": job.salary,
                "description": job.description,
                "job_url": job.job_url,
                "status": job.status,
                "raw_metadata": job.raw_metadata,
                "first_seen_at": job.first_seen_at.isoformat() if job.first_seen_at else None,
                "last_seen_at": job.last_seen_at.isoformat() if job.last_seen_at else None,
                "match_score": rec_data["match_score"],
                "match_reason": rec_data["reason"]
            })
            
    result.sort(key=lambda x: x["match_score"], reverse=True)
    return result


@app.post("/match-jobs/file")
def match_jobs_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Match jobs intelligently by uploading a resume file (PDF/TXT/MD)"""
    try:
        resume_text = parse_resume_file(file)
        if not resume_text or len(resume_text.strip()) < 10:
            raise HTTPException(status_code=400, detail="Could not extract sufficient text content from the resume file.")
        return process_match(resume_text, db)
    except Exception as e:
        logger.error(f"Error in match_jobs_file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class MatchTextRequest(BaseModel):
    resume_text: str


@app.post("/match-jobs/text")
def match_jobs_text(
    request: MatchTextRequest,
    db: Session = Depends(get_db)
):
    """Match jobs intelligently by pasting resume text"""
    resume_text = request.resume_text
    if not resume_text or len(resume_text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Resume text is too short or empty.")
    try:
        return process_match(resume_text, db)
    except Exception as e:
        logger.error(f"Error in match_jobs_text: {e}")
        raise HTTPException(status_code=500, detail=str(e))

