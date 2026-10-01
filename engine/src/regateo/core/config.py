"""Config file loading and project paths."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, TypeVar

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

ENGINE_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = ENGINE_DIR.parent


def configs_dir() -> Path:
    return Path(os.environ.get("REGATEO_CONFIGS", ENGINE_DIR / "configs"))


def data_dir() -> Path:
    path = Path(os.environ.get("REGATEO_DATA", REPO_DIR / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_env() -> None:
    """Load engine/.env if present. Real environment variables win."""
    load_dotenv(ENGINE_DIR / ".env", override=False)


def load_yaml(path: str | Path, model: type[T]) -> T:
    """Load a YAML file into a pydantic model. `${VAR}` and `${VAR:-default}` are expanded."""
    return model.model_validate(load_yaml_dict(path))


def load_yaml_dict(path: str | Path) -> dict[str, Any]:
    """Load a YAML mapping, with `${VAR}` expanded, for callers that merge files before validating."""
    return yaml.safe_load(_expand_env(Path(path).read_text())) or {}


def _expand_env(text: str) -> str:
    def sub(m: re.Match[str]) -> str:
        name, _, default = m.group(1).partition(":-")
        return os.environ.get(name, default)

    return re.sub(r"\$\{([^}]+)\}", sub, text)
