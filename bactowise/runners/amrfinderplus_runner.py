from __future__ import annotations

import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console


class AMRFinderPlusRunner(CondaToolRunner):
    """
    Stage 4 — AMRFinderPlus: antimicrobial resistance gene and point mutation detection.

    AMRFinderPlus scans for acquired AMR genes, virulence factors, stress
    resistance genes, and (optionally) known point mutations for specific taxa.

    Input sources
    -------------
    Nucleotide FASTA  : the original genome FASTA passed to `bactowise run`

    Runs in nucleotide-only mode (-n). Protein mode (-p) can be enabled in a
    future update once consensus FAA header compatibility is confirmed.

    Database
    --------
    Downloaded automatically via `amrfinder -u` during preflight if not present.
    Stored inside the amrfinderplus_env conda environment's data directory.

    Optional params (set in pipeline.yaml under params:)
    -------------------------------------------------------
    organism : str   AMRFinderPlus taxon name for point mutation screening.
                     Must be a value from `amrfinder --list_organisms`.
                     Examples: Escherichia, Salmonella, Staphylococcus_aureus.
                     Omit if organism is not in AMRFinderPlus's supported list.
    plus     : bool  Include virulence, stress, and biocide resistance genes
                     (default: true — strongly recommended).
    threads  : int   Number of threads (falls back to global_threads).

    Output
    ------
    <output_dir>/amrfinderplus/
        amrfinderplus_results.tsv   tab-delimited AMR findings
        logs/amrfinderplus.log      full execution log

    Conda package : ncbi-amrfinderplus (binary: amrfinder)
    """

    # The conda package name differs from the tool name used elsewhere
    CONDA_PACKAGE = "ncbi-amrfinderplus"

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking amrfinderplus (stage 4)")

        if self.config.conda_env:
            self._ensure_amrfinderplus_env()
        else:
            if not self._tool_installed("amrfinder"):
                raise RuntimeError(
                    "  ✗  'amrfinder' not found on PATH and no conda_env configured.\n"
                    "     Add a conda_env block for 'amrfinderplus' in pipeline.yaml."
                )

        self._ensure_database()

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
                f"  [warning]⚠[/warning]  Could not determine installed version of amrfinder."
            )

    def _ensure_amrfinderplus_env(self) -> None:
        """
        Create the amrfinderplus_env using 'ncbi-amrfinderplus' as the package name.
        The conda package name differs from the binary name 'amrfinder', so the
        standard _ensure_conda_env() would try to install 'amrfinderplus=x.x.x'
        which doesn't exist on bioconda.
        """
        env_config  = self.config.conda_env
        env_name    = env_config.name
        conda_root  = self._find_conda_root()
        binary_path = Path(conda_root) / "envs" / env_name / "bin" / "amrfinder"

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

        # Install ncbi-amrfinderplus without a version pin.
        # --strict-channel-priority is required to prevent conda mixing
        # conda-forge and bioconda builds of libcurl/libnghttp2, which causes
        # an unsatisfiable dependency conflict on pinned versions.
        # Channel order must be conda-forge first, then bioconda (per NCBI docs).
        packages = [self.CONDA_PACKAGE]
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

    def _ensure_database(self) -> None:
        """
        Download the AMRFinderPlus database if not already present.
        Uses `amrfinder --database_version` to check presence — if it fails
        (exit code != 0) the database is missing and `amrfinder -u` is run.
        This is idempotent: -u is a no-op if the database is already current.
        """
        console.print("  Checking AMRFinderPlus database...")

        check = subprocess.run(
            self._conda_run_cmd(["--database_version"]),
            capture_output=True, text=True,
        )

        if check.returncode == 0:
            db_version = (check.stdout.strip() or check.stderr.strip()).split()[-1]
            console.print(
                f"  [success]✓[/success]  AMRFinderPlus database present "
                f"(version [bold]{db_version}[/bold])."
            )
            return

        console.print(
            "  AMRFinderPlus database not found. Downloading now "
            "(this is a one-time step)..."
        )

        result = subprocess.run(
            self._conda_run_cmd(["-u"]),
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "  ✗  Failed to download AMRFinderPlus database.\n"
                "     Try manually:\n"
                "       conda run -n amrfinderplus_env amrfinder -u"
            )

        console.print("  [success]✓[/success]  AMRFinderPlus database downloaded.")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting AMR gene detection...")

        output_tsv = self.output_dir / "amrfinderplus_results.tsv"
        log_file   = self.log_dir / "amrfinderplus.log"

        cmd = self._build_command(fasta, output_tsv)

        self._cprint(f"[label]Nucleotide:[/label] [muted]{fasta}[/muted]")
        self._cprint(f"[label]Output:[/label]     [muted]{output_tsv}[/muted]")
        self._cprint(f"[label]Command:[/label]    [muted]{' '.join(cmd)}[/muted]")
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
                f"[amrfinderplus] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._report_summary(output_tsv)

        self._cprint(
            f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]"
        )
        console.print()
        return self.output_dir

    def _build_command(
        self,
        fasta: Path,
        output_tsv: Path,
    ) -> list[str]:
        """
        Build the amrfinder command in nucleotide-only mode.

            amrfinder -n <fasta> --plus -t <threads> -o <tsv>
                      [--organism <taxon>]
        """
        threads = self.config.params.get("threads", self.global_threads)
        plus    = self.config.params.get("plus", True)

        tool_args = [
            "-n", str(fasta.resolve()),
            "-o", str(output_tsv),
            "-t", str(threads),
        ]

        if plus:
            tool_args.append("--plus")

        organism = self.config.params.get("organism")
        if organism:
            tool_args += ["--organism", str(organism)]

        return self._conda_run_cmd(tool_args)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _report_summary(self, output_tsv: Path) -> None:
        """Print a brief count of findings to the console after the run."""
        if not output_tsv.exists():
            return
        try:
            with open(output_tsv) as f:
                lines = [l for l in f if not l.startswith("Protein") and l.strip()]
            count = len(lines)
            if count > 0:
                self._cprint(
                    f"[success]{count} AMR finding(s)[/success] written to "
                    f"[muted]{output_tsv.name}[/muted]."
                )
            else:
                self._cprint("No AMR genes or mutations detected.")
        except Exception:
            pass

    def _conda_run_cmd(self, tool_args: list[str]) -> list[str]:
        """
        Override to use 'amrfinder' as the binary name (not 'amrfinderplus').
        The tool name in config is 'amrfinderplus' for clarity, but the actual
        binary installed by ncbi-amrfinderplus is 'amrfinder'.
        """
        if self.config.conda_env:
            conda_bin = self._find_conda_binary()
            return [
                conda_bin, "run",
                "--no-capture-output",
                "-n", self.config.conda_env.name,
                "amrfinder",
            ] + tool_args
        else:
            return ["amrfinder"] + tool_args
