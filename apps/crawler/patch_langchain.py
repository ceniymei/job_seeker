"""
Compatibility patch for scrapegraphai.
Due to a known bug in scrapegraphai (up to version 2.1.1+), the package internally imports 
ChatOllama from the deprecated path `langchain_community.chat_models`. Since langchain-community >= 0.3.0 
has removed ChatOllama from its community exports, this causes an ImportError on startup.

This patch dynamically shims langchain_community.chat_models to include ChatOllama from langchain_ollama 
to allow scrapegraphai to import successfully.
"""
import sys
import types
import logging

logger = logging.getLogger(__name__)

# Apply monkey patch to prevent scrapegraphai import crash
try:
    import langchain_community.chat_models
except ImportError:
    # If the module doesn't exist, create it in sys.modules
    langchain_community_chat_models = types.ModuleType("langchain_community.chat_models")
    sys.modules["langchain_community.chat_models"] = langchain_community_chat_models
    import langchain_community.chat_models

try:
    from langchain_ollama import ChatOllama
    langchain_community.chat_models.ChatOllama = ChatOllama
except ImportError:
    logger.warning("langchain-ollama is not installed; ChatOllama shim could not be loaded.")

# Globally silence warnings about unexpected 'model_tokens' argument, caused by ScrapegraphAI passing model_tokens to cloud models (e.g. Gemini, OpenAI)
import warnings
warnings.filterwarnings("ignore", message=".*Unexpected argument 'model_tokens'.*")
