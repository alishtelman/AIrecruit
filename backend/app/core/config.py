from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://recruiting:recruiting@postgres:5432/recruiting"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ANTHROPIC_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    UPLOAD_DIR: str = "/app/uploads"
    RESUME_STORAGE_DIR: str = "/app/storage/resumes"
    RECORDING_STORAGE_DIR: str = "/app/storage/recordings"
    MAX_RESUME_SIZE_MB: int = 10
    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = "AIRecruit <noreply@airecruit.app>"
    APP_URL: str = "http://localhost:3000"


settings = Settings()
