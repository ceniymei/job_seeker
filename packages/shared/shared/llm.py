import os
import logging
from shared.config import config

logger = logging.getLogger("shared.llm")

def get_llm():
    """Get LangChain compatible ChatModel instance based on global configuration"""
    provider = config.llm_provider.lower()
    model = config.llm_model
    base_url = config.llm_base_url
    
    logger.info(f"Initializing LLM provider: {provider}, model: {model}")
    
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model,
            base_url=base_url or "http://localhost:11434",
            temperature=0.0
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=config.llm_api_key,
            base_url=base_url,
            temperature=0.0
        )
    elif provider in ["gemini", "google_genai", "google"]:
        from langchain_google_genai import ChatGoogleGenerativeAI
        # Fallback support
        api_key = config.llm_api_key or os.environ.get("GEMINI_API_KEY")
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0.0
        )
    else:
        # Default fallback to Ollama
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model="qwen2:7b",
            base_url="http://localhost:11434",
            temperature=0.0
        )
