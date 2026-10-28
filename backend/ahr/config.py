from pathlib import Path
from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AHR_", env_file=ROOT / ".env", extra="ignore")
    env: str = "development"
    demo_mode: bool = True
    host: str = "127.0.0.1"
    port: int = 8765
    database_url: str = ""
    redis_url: str = ""
    runtime_dir: str = str(ROOT / "runtime")
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    vision_model: str = ""
    embedding_model: str = ""
    allow_external_models: bool = False
    segmentation_checkpoint: str = ""
    inpaint_method: str = "interpolation"
    inpaint_checkpoint: str = ""
    retrieval_model_dir: str = ""
    retrieval_backend: Literal["dinov2","clip"] = "dinov2"
    sam_model_dir: str = ""
    storage: Literal["local","obs"] = "local"
    obs_endpoint: str = ""
    obs_bucket: str = ""
    obs_access_key: str = ""
    obs_secret_key: str = ""
    obs_region: str = "cn-north-4"
    bootstrap_password: str = ""
    allowed_origins: str = "http://127.0.0.1:8765,http://localhost:8765,http://127.0.0.1:5173,http://localhost:5173"

    @property
    def runtime(self):
        path = Path(self.runtime_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_url(self):
        return self.database_url or f"sqlite:///{self.runtime / 'ahr.db'}"


@lru_cache
def settings():
    return Settings()

