from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator


class DatabaseConfig(BaseModel):
    path: Path
    type: Literal["light", "full"] = "full"

    @field_validator("path", mode="before")
    @classmethod
    def expand_path(cls, v):
        return Path(v).expanduser().resolve()


class CondaEnvConfig(BaseModel):
    """
    Describes a dedicated conda environment for a tool.
    Genoflow creates this environment automatically if it doesn't exist,
    then runs the tool inside it via 'conda run -n <name>' which handles
    all library path setup correctly.

    'dependencies' is an open list of anything conda needs alongside the tool.
    Only specify what's needed to resolve conflicts — the tool itself is always
    included automatically from the parent 'name' and 'version' fields.

    Examples:
        dependencies:
          - python=3.8        # for Python-based tools with version conflicts
          - perl=5.32         # for Perl-based tools
          - openjdk=11        # for Java-based tools (e.g. GATK)
          - openssl=1.1       # for specific library version conflicts

    If the tool has no dependency conflicts, omit 'dependencies' entirely.
    """
    name: str
    channels: list[str] = ["bioconda", "conda-forge"]
    dependencies: list[str] = []


class ToolConfig(BaseModel):
    name: str
    version: str
    runtime: Literal["conda", "docker"]
    image: Optional[str] = None
    database: Optional[DatabaseConfig] = None
    conda_env: Optional[CondaEnvConfig] = None
    params: dict = {}

    @model_validator(mode="after")
    def validate_fields(self) -> ToolConfig:
        if self.runtime == "docker" and self.image is None:
            self.image = f"{self.name}:{self.version}"

        if self.conda_env and self.runtime != "conda":
            raise ValueError(
                f"'conda_env' is only valid for runtime: conda, "
                f"but tool '{self.name}' has runtime: {self.runtime}"
            )
        return self


class PipelineConfig(BaseModel):
    tools: list[ToolConfig]
    output_dir: Path = Path("./results")
    threads: int = 4

    @field_validator("output_dir", mode="before")
    @classmethod
    def expand_output(cls, v):
        return Path(v).expanduser().resolve()

    @field_validator("tools")
    @classmethod
    def at_least_one_tool(cls, v):
        if not v:
            raise ValueError("At least one tool must be specified in config.")
        return v
