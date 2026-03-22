from __future__ import annotations

import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console
from bactowise.utils.db_manager import (
    _SPIFINDER_DB_DIR,
    _SPIFINDER_ROOT,
    _SPIFINDER_SCRIPT,
    download_spifinder,
    is_spifinder_present,
)


class SPIFinderRunner(CondaToolRunner):
    """
    Stage 4 — SPIFinder: Salmonella Pathogenicity Island detection.

    SPIFinder screens assembled Salmonella genomes against a curated BLAST
    database of 15 known Salmonella Pathogenicity Islands (SPI-1 to SPI-14
    plus SPI-24), identifying which SPIs are present and reporting coverage
    and identity for each hit.

    Salmonella-only constraint
    --------------------------
    SPIFinder only makes biological sense for Salmonella. BactoWise checks
    the genus extracted from the -n/--organism CLI input and skips this tool
    entirely (with an informational message) when the genus is not Salmonella.
    This avoids meaningless results for non-Salmonella genomes.

    Installation
    ------------
    No Docker image or conda package exists for SPIFinder. BactoWise installs
    it by git-cloning both the tool and its database from Bitbucket into
    ~/.bactowise/databases/spifinder/:
        spifinder/      — the spifinder.py Python script
        spifinder_db/   — the BLAST database files (~3 MB)

    The spifinder_env conda environment provides Python, BLAST+, and git.
    The CGE Python library (cgecore) and other dependencies are installed
    via pip into the same environment.

    Input
    -----
    The original genome FASTA passed to `bactowise run -f`. No stage 2 or
    stage 3 outputs are required.

    Output
    ------
    <output_dir>/spifinder/
        spifinder_results.tsv       — SPI hits (tab-delimited)
        spifinder_results.json      — full CGE-format results
        Hit_in_genome_seq.fsa       — matched genomic sequences (FASTA)
        logs/spifinder.log

    Optional params (set in pipeline.yaml under params:)
    -----------------------------------------------------
    min_cov   : float  Minimum coverage threshold 0–1 (default: 0.60)
    threshold : float  Minimum identity threshold 0–1 (default: 0.95)
    """

    # pip packages required inside spifinder_env
    _PIP_DEPS = ["cgecore", "tabulate", "biopython", "gitpython", "python-dateutil"]

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking spifinder (stage 4)")

        if not self._is_salmonella():
            console.print(
                f"  [muted]~  SPIFinder skipped — only runs for Salmonella.\n"
                f"     Organism: '{self.organism}' (genus is not Salmonella)[/muted]"
            )
            return

        if self.config.conda_env:
            self._ensure_spifinder_env()
        else:
            if not self._tool_installed("blastn"):
                raise RuntimeError(
                    "  ✗  'blastn' not found on PATH and no conda_env configured.\n"
                    "     Add a conda_env block for 'spifinder' in pipeline.yaml."
                )

        self._ensure_spifinder_install()

        console.print(
            f"  [success]✓[/success]  SPIFinder ready for Salmonella analysis."
        )

    def _is_salmonella(self) -> bool:
        """Return True if the organism name has genus Salmonella."""
        if not self.organism:
            return False
        return self.organism.strip().lower().split()[0] == "salmonella"

    def _ensure_spifinder_env(self) -> None:
        """
        Create spifinder_env with python, blast, and git via conda,
        then install CGE Python dependencies via pip.
        """
        env_config  = self.config.conda_env
        env_name    = env_config.name
        conda_root  = self._find_conda_root()
        blastn_path = Path(conda_root) / "envs" / env_name / "bin" / "blastn"

        if blastn_path.exists():
            console.print(
                f"  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] "
                f"already exists — skipping creation."
            )
            # Always ensure pip deps are present (handles envs created before
            # pip install step was added)
            self._ensure_pip_deps(env_name)
            return

        console.print(f"\n  Conda env [bold]'{env_name}'[/bold] not found. Creating it now...")
        console.print(f"    Channels: {env_config.channels}")
        console.print(f"    This is a one-time step and may take a few minutes.\n")

        conda_bin  = self._find_conda_binary()
        conda_deps = ["python", "blast", "git"] + [
            d for d in env_config.dependencies
            if d not in self._PIP_DEPS
        ]

        cmd = [conda_bin, "create", "-n", env_name, "-y", "--strict-channel-priority"]
        for channel in env_config.channels:
            cmd += ["-c", channel]
        cmd += conda_deps

        console.print(f"  Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to create conda env '{env_name}'.\n"
                f"     Try running manually:\n"
                f"     {' '.join(cmd)}"
            )

        self._ensure_pip_deps(env_name)

        console.print(
            f"\n  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] "
            f"created successfully."
        )

    def _ensure_pip_deps(self, env_name: str) -> None:
        """Install CGE Python dependencies via pip into the env."""
        conda_bin = self._find_conda_binary()
        pip_cmd = [
            conda_bin, "run", "--no-capture-output",
            "-n", env_name,
            "pip", "install", "--quiet",
        ] + self._PIP_DEPS

        result = subprocess.run(pip_cmd, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to install SPIFinder Python dependencies.\n"
                f"     Try manually:\n"
                f"       conda run -n {env_name} pip install {' '.join(self._PIP_DEPS)}"
            )

    def _ensure_spifinder_install(self) -> None:
        """Clone SPIFinder and its database if not already present."""
        if is_spifinder_present():
            console.print(
                f"  [success]✓[/success]  SPIFinder installation found: "
                f"[muted]{_SPIFINDER_ROOT}[/muted]"
            )
            return

        console.print(
            "  SPIFinder not found. Cloning from Bitbucket (this is a one-time step)..."
        )
        try:
            download_spifinder(force=False)
            console.print(
                f"  [success]✓[/success]  SPIFinder installed: "
                f"[muted]{_SPIFINDER_ROOT}[/muted]"
            )
        except RuntimeError as e:
            raise RuntimeError(
                f"  ✗  Failed to install SPIFinder.\n{e}\n"
                f"     You can also run: bactowise db download --spifinder"
            ) from e

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        # Salmonella gate — skip silently if not applicable
        if not self._is_salmonella():
            console.print()
            self._cprint(
                f"Skipped — SPIFinder only runs for Salmonella "
                f"(organism: '{self.organism}')."
            )
            console.print()
            return self.output_dir

        console.print()
        self._cprint("Starting Salmonella Pathogenicity Island detection...")

        log_file = self.log_dir / "spifinder.log"
        blastn   = self._blastn_path()
        cmd      = self._build_command(fasta, blastn)

        self._cprint(f"[label]Input:[/label]     [muted]{fasta}[/muted]")
        self._cprint(f"[label]Output:[/label]    [muted]{self.output_dir}[/muted]")
        self._cprint(f"[label]Command:[/label]   [muted]{' '.join(cmd)}[/muted]")
        self._cprint(f"[label]Logging to:[/label] [muted]{log_file}[/muted]")

        with open(log_file, "w") as log:
            result = subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"[spifinder] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._report_summary()

        self._cprint(
            f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]"
        )
        console.print()
        return self.output_dir

    def _build_command(self, fasta: Path, blastn: str) -> list[str]:
        """
        Build the spifinder command:

            python spifinder.py
                -i <fasta>
                -o <output_dir>
                -p <spifinder_db>
                -mp <blastn_path>
                -l <min_cov>
                -t <threshold>
        """
        min_cov   = self.config.params.get("min_cov", 0.60)
        threshold = self.config.params.get("threshold", 0.95)

        tool_args = [
            str(_SPIFINDER_SCRIPT),
            "-i", str(fasta.resolve()),
            "-o", str(self.output_dir),
            "-p", str(_SPIFINDER_DB_DIR),
            "-mp", blastn,
            "-l", str(min_cov),
            "-t", str(threshold),
        ]

        # Run python directly inside the conda env
        if self.config.conda_env:
            conda_bin = self._find_conda_binary()
            return [
                conda_bin, "run", "--no-capture-output",
                "-n", self.config.conda_env.name,
                "python",
            ] + tool_args
        else:
            return ["python"] + tool_args

    def _blastn_path(self) -> str:
        """
        Return the path to the blastn binary inside the conda env,
        falling back to the PATH-based binary if no conda env is configured.
        """
        if self.config.conda_env:
            conda_root = self._find_conda_root()
            blastn = (
                Path(conda_root)
                / "envs"
                / self.config.conda_env.name
                / "bin"
                / "blastn"
            )
            if blastn.exists():
                return str(blastn)
        import shutil
        on_path = shutil.which("blastn")
        if on_path:
            return on_path
        raise RuntimeError(
            "  ✗  blastn not found in spifinder_env or on PATH.\n"
            "     Re-run to recreate the environment, or install blastn manually."
        )

    def _report_summary(self) -> None:
        """Print a brief SPI count after the run."""
        tsv = self.output_dir / "spifinder_results.tsv"
        if not tsv.exists():
            return
        try:
            with open(tsv) as f:
                rows = [l for l in f if l.strip() and not l.startswith("#")
                        and not l.lower().startswith("pathogenicity")]
            count = len(rows)
            if count > 0:
                self._cprint(
                    f"[success]{count} SPI region(s)[/success] detected. "
                    f"Results in [muted]{tsv.name}[/muted]."
                )
            else:
                self._cprint("No Salmonella Pathogenicity Islands detected.")
        except Exception:
            pass
