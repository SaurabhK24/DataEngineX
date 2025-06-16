import os
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv('.env')

class Config:
    """Application configuration settings"""
    
    # ArXiv API Settings
    ARXIV_BASE_URL = "http://export.arxiv.org/api/query"
    API_TIMEOUT = 30.0
    USER_AGENT = "DataEngine/1.0 (https://github.com/NeuxsAI/DataEngine)"
    RATE_LIMIT_DELAY = 1  # seconds to wait on 429 error
    
    # Paper Categories and Impact
    MAJOR_CATEGORIES = {'cs.AI', 'cs.LG', 'cs.CL', 'stat.ML'}
    RECENT_YEAR_THRESHOLD = 2020
    
    # Search Defaults
    DEFAULT_MAX_RESULTS = 10
    DEFAULT_SORT_BY = "relevance"
    DEFAULT_SORT_ORDER = "descending"
    
    # Storage Settings
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    
    # Llama API for AI processing
    LLAMA_API_KEY = os.getenv("LLAMA_API_KEY")
    
    # Research Platform Configuration
    DEFAULT_SEARCH_LIMIT = 20
    MAX_SEARCH_LIMIT = 50
    MAX_UPLOAD_SIZE_MB = 50
    
    @classmethod
    def get_env_var(cls, key: str, default: Any = None) -> Any:
        """Get environment variable with optional default"""
        return os.getenv(key, default) 