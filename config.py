__author__ = "Se Hoon Kim(sehoon787@korea.ac.kr)"

# Standard imports
from pathlib import Path

# Third-party imports
from pydantic_settings import BaseSettings
import yaml


class Settings(BaseSettings):
    version: str

    chat_path: str
    file_path: str

    @classmethod
    def load_from_yaml(cls, env: str = "development") -> "Settings":
        config_file = Path(__file__).parent / f"config-{env}.yml"

        # Load YAML configuration
        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        return cls(
            version=config["version"],
            chat_path=config["path"]["chat"],
            file_path=config["path"]["file"],
        )


# Load settings from YAML
settings = Settings.load_from_yaml(env="development")
