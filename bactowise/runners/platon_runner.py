from __future__ import annotations

import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console
from bactowise.utils.db_manager import _PLATON_DB_DIR, download_platon, is_platon_present


class PlatonRunner(CondaToolRunner):
    """
    Stage 4 — Platon: plasmid contig classification and characterization.

    Platon identifies plasmid-borne contigs within bacterial draft assemblies
    by analysing the distribution bias of protein-coding gene families between
    chromosomes and plasmids (replicon distribution scores, RDS). It then
    characterises plasmid contigs by searching for replication, mobilisation
    and conjugation genes, oriT sequences, and incompatibility group probes.

    Input
    -----
    The original genome FASTA passed to `bactowise run -f`. No stage 2/3
    outputs are required — Platon performs its own gene calling via Prodigal.

    Database
    --------
    Mandatory, ~2.8 GB unzipped. Downloaded automatically during preflight
    to ~/.bactowise/databases/platon/db/ if not already present.
    Can also be pre-downloaded with: bactowise db download --platon

    Output
    ------
    <output_dir>/platon/
        platon_output.tsv              plasmid contig summary (tab-delimited)
        platon_output.json             comprehensive per-contig results
        platon_output_plasmid.fasta    plasmid contig sequences
        platon_output_chromosome.fasta chromosomal contig sequences
        logs/platon.log

    Conda package : platon (bioconda)

    Optional params (set in pipeline.yaml under params:)
    -----------------------------------------------------
    mode    : sensitivity | accuracy | specificity  (default: accuracy)
    threads : int  override global thread count
    """

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking platon (stage 4)")

        if self.config.conda_env:
            self._ensure_conda_env(self.config.conda_env)
        else:
            if not self._tool_installed("platon"):
                raise RuntimeError(
                    "  ✗  'platon' not found on PATH and no conda_env configured.\n"
                    "     Add a conda_env block for 'platon' in pipeline.yaml."
                )

        self._ensure_platon_db()

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
                f"  [warning]⚠[/warning]  Could not determine installed version of platon."
            )

    def _ensure_platon_db(self) -> None:
        """Download the Platon database if not already present."""
        if is_platon_present():
            console.print(
                f"  [success]✓[/success]  Platon database found: "
                f"[muted]{_PLATON_DB_DIR}[/muted]"
            )
            return

        console.print(
            "  Platon database not found. Downloading now (~1.6 GB, one-time step)..."
        )
        try:
            download_platon(force=False)
            console.print(
                f"  [success]✓[/success]  Platon database ready: "
                f"[muted]{_PLATON_DB_DIR}[/muted]"
            )
        except RuntimeError as e:
            raise RuntimeError(
                f"  ✗  Failed to download Platon database.\n{e}\n"
                f"     You can also run: bactowise db download --platon"
            ) from e

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting plasmid contig classification...")

        log_file = self.log_dir / "platon.log"
        cmd      = self._build_command(fasta)

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
                f"[platon] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._report_summary()

        self._cprint(
            f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]"
        )
        console.print()
        return self.output_dir

    def _build_command(self, fasta: Path) -> list[str]:
        """
        Build the platon command.

            platon <genome.fasta> --db <db_path>
                   --output <output_dir> --prefix platon_output
                   --mode <mode> --threads <n>
        """
        mode    = self.config.params.get("mode", "accuracy")
        threads = self.config.params.get("threads", self.global_threads)

        tool_args = [
            str(fasta.resolve()),
            "--db",     str(_PLATON_DB_DIR),
            "--output", str(self.output_dir),
            "--prefix", "platon_output",
            "--mode",   mode,
            "--threads", str(threads),
        ]

        return self._conda_run_cmd(tool_args)

    def _report_summary(self) -> None:
        """Print a brief plasmid count to the console after the run."""
        tsv = self.output_dir / "platon_output.tsv"
        if not tsv.exists():
            return
        try:
            with open(tsv) as f:
                rows = [l for l in f if l.strip() and not l.startswith("#")]
            count = len(rows) - 1 if rows else 0  # subtract header
            if count > 0:
                self._cprint(
                    f"[success]{count} plasmid contig(s)[/success] identified. "
                    f"Results in [muted]{tsv.name}[/muted]."
                )
            else:
                self._cprint("No plasmid contigs detected.")
        except Exception:
            pass
