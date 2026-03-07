from __future__ import annotations

import abc
import shutil
from pathlib import Path

from genoflow.models.config import ToolConfig


class BaseRunner(abc.ABC):
    """
    Abstract base class for all tool runners.
    Every runner — conda or docker — exposes the same run() interface.
    Swapping BaktaRunner for PGAPRunner is a config change, not a code change.
    """

    def __init__(self, tool_config: ToolConfig, output_dir: Path):
        self.config = tool_config
        self.output_dir = output_dir / tool_config.name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = self.output_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @abc.abstractmethod
    def preflight(self) -> None:
        """
        Run all checks BEFORE execution:
        - Is the tool installed / image available?
        - Does the database path exist?
        - Does the version match?
        Raises RuntimeError with a helpful message if anything is wrong.
        """
        ...

    @abc.abstractmethod
    def run(self, fasta: Path) -> Path:
        """
        Execute the tool on the given fasta file.
        Returns the output directory path.
        """
        ...

    def _check_version(self, installed_version: str) -> None:
        """Warn if installed version differs from config version. Never hard-fails."""
        if installed_version.strip() != self.config.version.strip():
            print(
                f"  ⚠  {self.config.name}: config version is {self.config.version} "
                f"but installed version is {installed_version.strip()}. "
                f"Continuing anyway."
            )
        else:
            print(f"  ✓  {self.config.name}: version {installed_version.strip()} confirmed.")

    def _tool_installed(self, tool_name: str) -> bool:
        return shutil.which(tool_name) is not None
