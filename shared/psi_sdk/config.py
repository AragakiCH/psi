from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "model_serve"
    kafka_bootstrap: str
    postgres_dsn: str
    redis_url: str | None = None
    mlflow_tracking_uri: str
    feast_repo: str = "/workspace/mlops/feast_repo"
    auth_jwks_url: str
    class Config:
        env_file = ".env"
