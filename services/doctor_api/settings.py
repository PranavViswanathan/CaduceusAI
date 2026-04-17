from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    JWT_SECRET: str
    FERNET_KEY: str
    INTERNAL_API_KEY: str
    OLLAMA_URL: str
    OLLAMA_MODEL: str = "llama3"
    FINE_TUNED_MODEL_NAME: str = "medical-risk-ft"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    COOKIE_DOMAIN: str = "localhost"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 30

    class Config:
        env_file = ".env"


settings = Settings()
