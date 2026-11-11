import os
import urllib.parse
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field

class Settings(BaseSettings):
    PROJECT_NAME: str = "NetworkOS API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "networkos"
    POSTGRES_PORT: int = 5432
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    SERPER_API_KEY: str = ""
    ENABLE_EPISTEMIC_VERIFICATION: bool = True

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        safe_pass = urllib.parse.quote_plus(urllib.parse.unquote(self.POSTGRES_PASSWORD))
        ssl_suffix = "?ssl=require" if ("supabase" in self.POSTGRES_SERVER or "pooler" in self.POSTGRES_SERVER) else ""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{safe_pass}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}{ssl_suffix}"
    
    @computed_field
    @property
    def SQLALCHEMY_SYNC_DATABASE_URI(self) -> str:
        safe_pass = urllib.parse.quote_plus(urllib.parse.unquote(self.POSTGRES_PASSWORD))
        ssl_suffix = "?sslmode=require" if ("supabase" in self.POSTGRES_SERVER or "pooler" in self.POSTGRES_SERVER) else ""
        return f"postgresql://{self.POSTGRES_USER}:{safe_pass}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}{ssl_suffix}"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    @computed_field
    @property
    def REDIS_URI(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

settings = Settings()
