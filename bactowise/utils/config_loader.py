from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from bactowise.models.config import PipelineConfig


def load_config(config_path: Path) -> PipelineConfig:
    """
    Load and validate a pipeline.yaml file.
    Pydantic will raise a clear, structured error if anything is wrong
    before a single tool is invoked.
    """
    config_path = Path(config_path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    try:
        return PipelineConfig(**raw)
    except ValidationError as e:
        # Re-raise with a friendlier message
        raise ValueError(
            f"Invalid config file: {config_path}\n\n{e}"
        ) from e
