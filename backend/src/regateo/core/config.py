"""Config file loading and project paths."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TypeVar

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = BACKEND_DIR.parent


def configs_dir() -> Path:
    return Path(os.environ.get("REGATEO_CONFIGS", BACKEND_DIR / "configs"))


def data_dir() -> Path:
    path = Path(os.environ.get("REGATEO_DATA", REPO_DIR / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_env() -> None:
    """Load backend/.env if present. Real environment variables win."""
    load_dotenv(BACKEND_DIR / ".env", override=False)


def load_yaml(path: str | Path, model: type[T]) -> T:
    """Load a YAML file into a pydantic model. `${VAR}` and `${VAR:-default}` are expanded."""
    text = Path(path).read_text()
    return model.model_validate(yaml.safe_load(_expand_env(text)) or {})


def _expand_env(text: str) -> str:
    def sub(m: re.Match[str]) -> str:
        name, _, default = m.group(1).partition(":-")
        return os.environ.get(name, default)

    return re.sub(r"\$\{([^}]+)\}", sub, text)
