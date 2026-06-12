import os
import yaml
from typing import Dict, Any, List

class Config:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        env_config = os.environ.get("JOB_SEEKER_CONFIG")
        if env_config and os.path.exists(env_config):
            config_file = env_config
        else:
            # Try to find config.yaml in several possible locations
            paths_to_try = [
                self.config_path,
                os.path.join(os.getcwd(), "config.yaml"),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../config.yaml")),
                os.path.abspath(os.path.join(os.path.dirname(__file__), "../../config.yaml"))
            ]
            config_file = None
            for p in paths_to_try:
                if os.path.exists(p):
                    config_file = p
                    break
            
            if not config_file:
                raise FileNotFoundError(f"Configuration file 'config.yaml' not found. Tried paths: {paths_to_try}")

        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @property
    def database_dsn(self) -> str:
        env_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_DSN")
        if env_url:
            return env_url
        db_config = self.data.get("database", {})
        return db_config.get("dsn", "postgresql://postgres:postgres@localhost:5432/job_seeker")

    @property
    def llm_provider(self) -> str:
        llm_config = self.data.get("llm", {})
        return os.environ.get("LLM_PROVIDER") or llm_config.get("provider", "gemini")

    @property
    def llm_model(self) -> str:
        llm_config = self.data.get("llm", {})
        return os.environ.get("LLM_MODEL") or llm_config.get("model", "gemini-1.5-flash")

    @property
    def llm_api_key(self) -> str:
        provider = self.llm_provider.lower()
        if provider == "gemini":
            env_key = os.environ.get("GEMINI_API_KEY")
        elif provider == "openai":
            env_key = os.environ.get("OPENAI_API_KEY")
        else:
            env_key = os.environ.get("LLM_API_KEY")
        
        if env_key:
            return env_key

        llm_config = self.data.get("llm", {})
        return llm_config.get("api_key", "")

    @property
    def llm_base_url(self) -> str:
        env_url = os.environ.get("LLM_BASE_URL") or os.environ.get("OLLAMA_BASE_URL")
        if env_url:
            return env_url
        llm_config = self.data.get("llm", {})
        return llm_config.get("base_url", "")

    @property
    def concurrency_limit(self) -> int:
        crawler_config = self.data.get("crawler", {})
        return int(os.environ.get("CRAWLER_CONCURRENCY") or crawler_config.get("concurrency_limit", 2))

    @property
    def timeout(self) -> int:
        crawler_config = self.data.get("crawler", {})
        return int(crawler_config.get("timeout", 30000))

    @property
    def export_json(self) -> bool:
        crawler_config = self.data.get("crawler", {})
        return bool(crawler_config.get("export_json", True))

    @property
    def export_dir(self) -> str:
        # If it is a relative path, convert it to an absolute path (relative to project root)
        crawler_config = self.data.get("crawler", {})
        export_path = crawler_config.get("export_dir", "./exports")
        if not os.path.isabs(export_path):
            # Mount the relative path under the project root directory
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
            return os.path.abspath(os.path.join(base_dir, export_path))
        return export_path

    @property
    def companies(self) -> List[Dict[str, Any]]:
        companies_list = self.data.get("companies", [])
        return [c for c in companies_list if c.get("is_active", True)]

config = Config()
