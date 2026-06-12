from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
from shared.config import config

# Dynamically assign engine parameters based on database type
engine_kwargs = {"pool_pre_ping": True}
if not config.database_dsn.startswith("sqlite"):
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_engine(config.database_dsn, **engine_kwargs)

db_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Session = scoped_session(db_session_factory)

Base = declarative_base()

@contextmanager
def get_db_session():
    """Database session context manager with automatic commit and close"""
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def init_db():
    """Initialize database tables and perform adaptive column migration upgrades"""
    import shared.models
    from sqlalchemy import text
    Base.metadata.create_all(bind=engine)
    
    # Dynamically inspect and add missing columns in the jobs table
    if config.database_dsn.startswith("postgresql"):
        try:
            with engine.begin() as conn:
                res = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='jobs'"))
                columns = [row[0] for row in res]
                
                if "location_standard" not in columns:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN location_standard JSONB"))
                    print("Database Migration: Added location_standard column to jobs table.")
                if "salary_standard" not in columns:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN salary_standard JSONB"))
                    print("Database Migration: Added salary_standard column to jobs table.")
                if "embedding" not in columns:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN embedding JSONB"))
                    print("Database Migration: Added embedding column to jobs table.")
                if "embedding_model" not in columns:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN embedding_model VARCHAR(250)"))
                    print("Database Migration: Added embedding_model column to jobs table.")
        except Exception as e:
            print(f"PostgreSQL migration warning: {str(e)}")
    else:
        try:
            with engine.begin() as conn:
                res = conn.execute(text("PRAGMA table_info(jobs)"))
                columns = [row[1] for row in res]
                if "location_standard" not in columns:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN location_standard JSON"))
                    print("Database Migration: Added location_standard column to jobs table (SQLite).")
                if "salary_standard" not in columns:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN salary_standard JSON"))
                    print("Database Migration: Added salary_standard column to jobs table (SQLite).")
                if "embedding" not in columns:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN embedding JSON"))
                    print("Database Migration: Added embedding column to jobs table (SQLite).")
                if "embedding_model" not in columns:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN embedding_model VARCHAR(250)"))
                    print("Database Migration: Added embedding_model column to jobs table (SQLite).")
        except Exception as e:
            print(f"SQLite migration warning: {str(e)}")

