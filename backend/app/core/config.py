from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    DATABASE_URL: str = "postgresql+asyncpg://recruiting:recruiting@postgres:5432/recruiting"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    SESSION_COOKIE_NAME: str = "airecruit_session"
    SESSION_COOKIE_SAMESITE: str = "lax"
    SESSION_COOKIE_SECURE: bool = False
    ANTHROPIC_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    ALLOW_MOCK_AI: bool = True
    ELEVENLABS_API_KEY: str = ""
    TTS_PROVIDER: str = "groq"
    TTS_FALLBACK_PROVIDER: str = "groq"
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_TTS_MODEL: str = "eleven_flash_v2_5"
    REPORT_SYNC_GENERATION_TIMEOUT_SECONDS: float = 8.0
    REPORT_ASSESSMENT_TIMEOUT_SECONDS: float = 25.0
    REPORT_MAX_AUTO_RETRIES: int = 3
    REPORT_RETRY_BASE_BACKOFF_SECONDS: int = 2
    REPORT_RETRY_MAX_BACKOFF_SECONDS: int = 12
    REPORT_LOCK_STALE_SECONDS: int = 300
    UPLOAD_DIR: str = "/app/uploads"
    RESUME_STORAGE_DIR: str = "/app/storage/resumes"
    RECORDING_STORAGE_DIR: str = "/app/storage/recordings"
    MAX_RESUME_SIZE_MB: int = 10
    MAX_RECORDING_SIZE_MB: int = 250
    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = "AIRecruit <noreply@airecruit.app>"
    APP_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000"
    PROCTORING_POLICY_MODE: str = "observe_only"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_local_or_test(self) -> bool:
        return self.APP_ENV.lower() in {"development", "dev", "local", "test"}

    @property
    def allow_mock_ai(self) -> bool:
        return self.ALLOW_MOCK_AI and self.is_local_or_test

    def validate_security_settings(self) -> None:
        insecure_defaults = {
            "change-me-in-production",
            "change-me-in-production-use-long-random-string",
        }
        if not self.is_local_or_test and (
            self.SECRET_KEY in insecure_defaults or len(self.SECRET_KEY) < 32
        ):
            raise ValueError(
                "SECRET_KEY must be overridden with a long random value outside development/test."
            )


settings = Settings()
settings.validate_security_settings()
