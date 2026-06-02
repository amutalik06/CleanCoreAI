"""
CleanCore AI — Configuration Module
Centralized configuration with environment variable support.
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    APP_NAME: str = "CleanCore AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # SAP Connection (defaults — overridden per project)
    SAP_ASHOST: str = ""
    SAP_SYSNR: str = "00"
    SAP_CLIENT: str = "100"
    SAP_USER: str = ""
    SAP_PASSWD: str = ""
    SAP_LANG: str = "EN"
    SAP_SAPROUTER: str = ""
    SAPNWRFC_HOME: str = ""
    SAP_ADT_URL: str = ""  # e.g. https://my-s4hana.example.com:44300
    SAP_ADT_VERIFY_SSL: bool = False
    SAP_CONNECT_TIMEOUT_SECONDS: float = 30.0
    SAP_RFC_CALL_TIMEOUT_SECONDS: float = 60.0

    # LLM Configuration
    LLM_PROVIDER: str = "openai"  # openai | azure | ollama | gemini
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "deepseek-coder:33b"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-pro"

    # Token Optimization
    LLM_MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.1
    CONFIDENCE_THRESHOLD: float = 0.85

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Storage
    UPLOAD_DIR: str = "./uploads"
    KNOWLEDGE_BASE_DIR: str = "./knowledge_base"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_value(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
