from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    chat_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")

    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    max_pages: int = Field(default=20, alias="MAX_PAGES")
    max_upload_mb: int = Field(default=20, alias="MAX_UPLOAD_MB")
    request_timeout: float = Field(default=15.0, alias="REQUEST_TIMEOUT")

    chunk_size: int = Field(default=1000, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=150, alias="CHUNK_OVERLAP")
    top_k: int = Field(default=6, alias="TOP_K")


settings = Settings()
