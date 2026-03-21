from __future__ import annotations

import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console
from bactowise.utils.db_manager import _PHIGARO_DB_DIR, is_phigaro_present


class PhigaroRunner(CondaToolRunner):
    """
    Stage 4 — Phigaro: prophage region detection.

    Phigaro detects prophage regions in bacterial genome assemblies by:
      1. Calling ORFs from the input FASTA using Prodigal
      2. Annotating genes against pVOG HMM profiles (prokaryotic viral
         orthologous groups)
      3. Applying a smoothing window algorithm to identify regions with
         high phage gene density

    Input
    -----
    The original genome FASTA passed to `bactowise run -f`. No stage 2 or
    stage 3 outputs are required — Phigaro performs its own gene calling.

    Setup
    -----
    `phigaro-setup` must be run once after installation to download the pVOG
    HMM database to ~/.phigaro/. BactoWise detects whether setup has been
    done (by checking for ~/.phigaro/config.yml) and runs it automatically
    during preflight if missing.

    Output
    ------
    <output_dir>/phigaro/
        phigaro_output.phg.tsv   prophage coordinates (tab-delimited)
        phigaro_output.phg.gff   prophage regions in GFF3 format
        logs/phigaro.log         full execution log

    Conda package  : phigaro (binary: phigaro)
    Channel order  : conda-forge first, then bioconda (strict priority)

    Optional params (set in pipeline.yaml under params:)
    -----------------------------------------------------
    threads : int   Number of threads (falls back to global_threads).
    """

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking phigaro (stage 4)")

        if self.config.conda_env:
            self._ensure_phigaro_env()
        else:
            if not self._tool_installed("phigaro"):
                raise RuntimeError(
                    "  ✗  'phigaro' not found on PATH and no conda_env configured.\n"
                    "     Add a conda_env block for 'phigaro' in pipeline.yaml."
                )

        self._ensure_phigaro_setup()

        # Version check — warn only, never fail
        try:
            result = subprocess.run(
                self._conda_run_cmd(["--version"]),
                capture_output=True, text=True,
            )
            raw = result.stdout.strip() or result.stderr.strip()
            installed_version = raw.split()[-1] if raw else "unknown"
            self._check_version(installed_version)
        except Exception:
            console.print(
                f"  [warning]⚠[/warning]  Could not determine installed version of phigaro."
            )

    def _ensure_phigaro_env(self) -> None:
        """
        Create phigaro_env using conda-forge first with --strict-channel-priority
        to avoid libcurl/libnghttp2 conflicts (same issue as AMRFinderPlus).
        """
        env_config  = self.config.conda_env
        env_name    = env_config.name
        conda_root  = self._find_conda_root()
        binary_path = Path(conda_root) / "envs" / env_name / "bin" / "phigaro"

        if binary_path.exists():
            console.print(
                f"  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] "
                f"already exists — skipping creation."
            )
            return

        console.print(f"\n  Conda env [bold]'{env_name}'[/bold] not found. Creating it now...")
        console.print(f"    Channels: {env_config.channels}")
        console.print(f"    This is a one-time step and may take a few minutes.\n")

        conda_bin = self._find_conda_binary()

        packages = [f"phigaro={self.config.version}"] if self.config.version != "latest" \
                   else ["phigaro"]
        packages += env_config.dependencies

        cmd = [conda_bin, "create", "-n", env_name, "-y", "--strict-channel-priority"]
        for channel in env_config.channels:
            cmd += ["-c", channel]
        cmd += packages

        console.print(f"  Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to create conda env '{env_name}'.\n"
                f"     Try running manually:\n"
                f"     {' '.join(cmd)}"
            )

        console.print(
            f"\n  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] "
            f"created successfully."
        )

    def _ensure_phigaro_setup(self) -> None:
        """
        Run phigaro-setup if the Phigaro database is not yet present.

        Correct flags (from phigaro-setup --help):
            -c CONFIG   path for the config file
            -p PVOG     directory to store pVOG HMM profiles
            -f          force / non-interactive (no prompts)
            --no-updatedb  skip sudo updatedb (required for non-root users)
        """
        if is_phigaro_present():
            console.print(
                f"  [success]✓[/success]  Phigaro database found: "
                f"[muted]{_PHIGARO_DB_DIR}[/muted]"
            )
            return

        _PHIGARO_DB_DIR.mkdir(parents=True, exist_ok=True)
        pvog_dir    = _PHIGARO_DB_DIR / "pvog"
        config_file = _PHIGARO_DB_DIR / "config.yml"

        console.print(
            "  Phigaro database not found. Running phigaro-setup "
            "(this is a one-time step, ~1.5 GB download)..."
        )

        result = subprocess.run(
            self._conda_run_cmd_for(
                "phigaro-setup",
                [
                    "-c", str(config_file),
                    "-p", str(pvog_dir),
                    "-f",
                    "--no-updatedb",
                ],
            ),
            input="\n",   # auto-select default prodigal path when prompted
            text=True,
        )

        if result.returncode != 0 or not is_phigaro_present():
            raise RuntimeError(
                f"  ✗  phigaro-setup failed.\n"
                f"     Try running manually:\n"
                f"       conda run -n phigaro_env phigaro-setup "
                f"-c {config_file} -p {pvog_dir} -f --no-updatedb"
            )

        console.print(
            f"  [success]✓[/success]  Phigaro setup complete: "
            f"[muted]{_PHIGARO_DB_DIR}[/muted]"
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting prophage detection...")

        # Output prefix — Phigaro appends .phg.tsv and .phg.gff to this
        output_prefix = self.output_dir / "phigaro_output"
        log_file      = self.log_dir / "phigaro.log"

        cmd = self._build_command(fasta, output_prefix)

        self._cprint(f"[label]Input:[/label]     [muted]{fasta}[/muted]")
        self._cprint(f"[label]Output:[/label]    [muted]{output_prefix}.phg.*[/muted]")
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
                f"[phigaro] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._report_summary(output_prefix)

        self._cprint(
            f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]"
        )
        console.print()
        return self.output_dir

    def _build_command(self, fasta: Path, output_prefix: Path) -> list[str]:
        """
        Build the phigaro command.

            phigaro -f <fasta> -o <prefix> -e tsv gff --not-open -t <threads>

        --not-open suppresses the browser auto-open behaviour, which is
        essential for non-interactive pipeline use.
        Output extensions tsv and gff give us structured coordinates and
        GFF3 output without generating the heavy HTML report.
        """
        threads = self.config.params.get("threads", self.global_threads)

        tool_args = [
            "-f", str(fasta.resolve()),
            "-o", str(output_prefix),
            "-e", "tsv", "gff",
            "--not-open",
            "-c", str(_PHIGARO_DB_DIR / "config.yml"),
            "-t", str(threads),
        ]

        return self._conda_run_cmd(tool_args)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _conda_run_cmd_for(self, binary: str, tool_args: list[str]) -> list[str]:
        """
        Build a conda run command for an arbitrary binary in the same env.
        Used for phigaro-setup which has a different binary name than phigaro.
        """
        if self.config.conda_env:
            conda_bin = self._find_conda_binary()
            return [
                conda_bin, "run",
                "--no-capture-output",
                "-n", self.config.conda_env.name,
                binary,
            ] + tool_args
        else:
            return [binary] + tool_args

    def _report_summary(self, output_prefix: Path) -> None:
        """Print a brief prophage count to the console after the run."""
        tsv = Path(str(output_prefix) + ".phg.tsv")
        if not tsv.exists():
            return
        try:
            with open(tsv) as f:
                # TSV has a header line; count data lines
                rows = [l for l in f if l.strip() and not l.startswith("scaffold")]
            count = len(rows)
            if count > 0:
                self._cprint(
                    f"[success]{count} prophage region(s)[/success] detected. "
                    f"Results in [muted]{tsv.name}[/muted]."
                )
            else:
                self._cprint("No prophage regions detected.")
        except Exception:
            pass
