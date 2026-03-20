from __future__ import annotations

import abc
import shutil
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.utils.console import console, cprint_tool


class BaseRunner(abc.ABC):
    """
    Abstract base class for all tool runners.
    Every runner — conda or docker — exposes the same run() interface.
    Swapping BaktaRunner for PGAPRunner is a config change, not a code change.
    """

    def __init__(self, tool_config: ToolConfig, output_dir: Path, organism: str = "", global_threads: int = 4):
        self.config = tool_config
        self.organism = organism.strip()
        self.global_threads = global_threads
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

    def _cprint(self, message: str) -> None:
        """Print a coloured [tool_name] prefixed line to the console."""
        cprint_tool(self.config.name, message)

    def _check_version(self, installed_version: str) -> None:
        """Warn if installed version differs from config version. Never hard-fails."""
        if installed_version.strip() != self.config.version.strip():
            console.print(
                f"  [warning]⚠[/warning]  [bold]{self.config.name}[/bold]: "
                f"config version is [bold]{self.config.version}[/bold] "
                f"but installed version is [bold]{installed_version.strip()}[/bold]. "
                f"Continuing anyway."
            )
        else:
            console.print(
                f"  [success]✓[/success]  [bold]{self.config.name}[/bold]: "
                f"version [bold]{installed_version.strip()}[/bold] confirmed."
            )

    def _tool_installed(self, tool_name: str) -> bool:
        return shutil.which(tool_name) is not None

    def _organism_parts(self) -> tuple[str, str]:
        """
        Split self.organism into (genus, species).
        "Mycoplasmoides genitalium" -> ("Mycoplasmoides", "genitalium")
        "Mycoplasma"               -> ("Mycoplasma", "")
        ""                         -> ("", "")
        """
        if not self.organism:
            return ("", "")
        parts = self.organism.split(" ", 1)
        genus = parts[0]
        species = parts[1] if len(parts) > 1 else ""
        return (genus, species)
