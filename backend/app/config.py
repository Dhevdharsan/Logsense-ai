from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "LogSense AI"
    env: str = "development"
    debug: bool = True
    database_url: str = "postgresql+asyncpg://logsense:logsense_dev_pwd@localhost:5432/logsense_db"
    redis_url: str = "redis://localhost:6379/0"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    ollama_timeout_seconds: int = 60
    anomaly_contamination: float = 0.05
    dbscan_eps: float = 0.5
    dbscan_min_samples: int = 3
    tfidf_max_features: int = 384
    llm_cache_ttl_seconds: int = 21600
    llm_max_sample_logs: int = 10
    max_batch_size: int = 10000
    max_message_length: int = 10000

    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
