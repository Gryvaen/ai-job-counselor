"""Docker Compose 运行时配置（通过 .env 覆盖）。"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_model: str = "qwen2.5:7b"
    webui_api_token: str = ""
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_prefix": "", "extra": "ignore"}


settings = Settings()
