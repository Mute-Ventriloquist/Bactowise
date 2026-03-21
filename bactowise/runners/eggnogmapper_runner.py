from __future__ import annotations

import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console
from bactowise.utils.db_manager import (
    _EGGNOG_DB_DIR,
    download_eggnog,
    is_eggnog_present,
)

# Locus tag prefix used by the consensus engine (matches pipeline.yaml default)
_CONSENSUS_FAA_PREFIX = "GENE"


class EggNOGMapperRunner(CondaToolRunner):
    """
    Stage 4 — EggNOG-mapper: functional annotation with GO, KEGG, and COGs.

    EggNOG-mapper assigns Gene Ontology (GO) terms, KEGG pathways, COG
    functional categories, and eggNOG orthology groups to every protein
    by searching against the eggNOG protein diamond database and then
    transferring annotations from fine-grained orthologs.

    Input
    -----
    Unlike the other stage 4 tools, EggNOG-mapper intentionally uses the
    stage 3 consensus engine output (GENE.faa) rather than the raw genome
    FASTA. This provides functional context for every consensus gene
    identified across Bakta, Prokka, and PGAP — the core purpose of this
    stage.

    The FAA file is located at: <output_dir>/consensus/GENE.faa

    Database
    --------
    ~20 GB total, downloaded automatically to:
        ~/.bactowise/databases/eggnog/
            eggnog.db            — main annotation SQLite database (~15 GB)
            eggnog_proteins.dmnd — DIAMOND search database (~4 GB)
            eggnog.taxa.db       — taxonomy database

    Can also be pre-downloaded with: bactowise db download --eggnog

    Output
    ------
    <output_dir>/eggnogmapper/
        eggnog_output.emapper.annotations   per-gene annotations (TSV)
        eggnog_output.emapper.hits           raw DIAMOND hits
        eggnog_output.emapper.seed_orthologs seed orthologs
        logs/eggnogmapper.log

    Conda package : eggnog-mapper (bioconda)
    Binary        : emapper.py

    Optional params (set in pipeline.yaml under params:)
    -----------------------------------------------------
    tax_scope  : Taxonomic scope for annotation (default: Bacteria)
    go_evidence: GO evidence codes to include (default: all)
    threads    : override global thread count
    """

    # Binary name differs from conda package name
    BINARY = "emapper.py"

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking eggnogmapper (stage 4)")

        if self.config.conda_env:
            self._ensure_eggnogmapper_env()
        else:
            if not self._tool_installed(self.BINARY):
                raise RuntimeError(
                    "  ✗  'emapper.py' not found on PATH and no conda_env configured.\n"
                    "     Add a conda_env block for 'eggnogmapper' in pipeline.yaml."
                )

        self._ensure_eggnog_db()

        self._ensure_consensus_faa()

        # Version check — warn only
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
                f"  [warning]⚠[/warning]  Could not determine installed version of emapper.py."
            )

    def _ensure_eggnogmapper_env(self) -> None:
        """Create eggnogmapper_env — standard bioconda install."""
        env_config  = self.config.conda_env
        env_name    = env_config.name
        conda_root  = self._find_conda_root()
        binary_path = Path(conda_root) / "envs" / env_name / "bin" / self.BINARY

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
        packages  = ["eggnog-mapper"] + env_config.dependencies

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

    def _ensure_eggnog_db(self) -> None:
        """Download the EggNOG database if not already present."""
        if is_eggnog_present():
            console.print(
                f"  [success]✓[/success]  EggNOG database found: "
                f"[muted]{_EGGNOG_DB_DIR}[/muted]"
            )
            return

        console.print(
            "  EggNOG database not found. Downloading now (~20 GB, one-time step)..."
        )
        try:
            download_eggnog(force=False)
            console.print(
                f"  [success]✓[/success]  EggNOG database ready: "
                f"[muted]{_EGGNOG_DB_DIR}[/muted]"
            )
        except RuntimeError as e:
            raise RuntimeError(
                f"  ✗  Failed to download EggNOG database.\n{e}\n"
                f"     You can also run: bactowise db download --eggnog"
            ) from e

    def _ensure_consensus_faa(self) -> None:
        """Verify the consensus stage FAA file will exist at runtime.
        We can only warn at preflight — the file is created during stage 3."""
        faa = self._consensus_faa_path()
        if faa.exists():
            console.print(
                f"  [success]✓[/success]  Consensus FAA found: [muted]{faa}[/muted]"
            )
        else:
            # Not an error at preflight — stage 3 hasn't run yet
            console.print(
                f"  [muted]~  Consensus FAA not yet present: {faa}[/muted]\n"
                f"  [muted]   (will be created by the consensus stage)[/muted]"
            )

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting functional annotation (GO / KEGG / COG)...")

        faa      = self._consensus_faa_path()
        log_file = self.log_dir / "eggnogmapper.log"

        if not faa.exists():
            raise RuntimeError(
                f"[eggnogmapper] Consensus protein FAA not found: {faa}\n"
                f"Ensure the consensus stage completed successfully."
            )

        cmd = self._build_command(faa)

        self._cprint(f"[label]Input:[/label]     [muted]{faa}[/muted]")
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
                f"[eggnogmapper] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._report_summary()

        self._cprint(
            f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]"
        )
        console.print()
        return self.output_dir

    def _build_command(self, faa: Path) -> list[str]:
        """
        Build the emapper.py command.

            emapper.py -i <GENE.faa> --itype proteins
                       -m diamond
                       -o eggnog_output --output_dir <dir>
                       --data_dir <db_path>
                       --tax_scope Bacteria
                       --go_evidence all
                       --cpu <n>
                       --override

        --override allows re-running without manually deleting previous output.
        --tax_scope Bacteria focuses orthology lookup on bacterial clades,
          reducing false transfers from distantly related eukaryotic orthologs.
        """
        threads    = self.config.params.get("threads", self.global_threads)
        tax_scope  = self.config.params.get("tax_scope", "Bacteria")
        go_evidence = self.config.params.get("go_evidence", "all")

        tool_args = [
            "-i",           str(faa),
            "--itype",      "proteins",
            "-m",           "diamond",
            "-o",           "eggnog_output",
            "--output_dir", str(self.output_dir),
            "--data_dir",   str(_EGGNOG_DB_DIR),
            "--tax_scope",  tax_scope,
            "--go_evidence", go_evidence,
            "--cpu",        str(threads),
            "--override",
        ]

        return self._conda_run_cmd(tool_args)

    def _consensus_faa_path(self) -> Path:
        """
        Return the path to the consensus engine protein FASTA.
        The consensus runner writes to <output_dir>/consensus/GENE.faa.
        The output_dir here is <base_output>/eggnogmapper/, so we walk
        up to the base output dir.
        """
        base_output_dir = self.output_dir.parent
        return base_output_dir / "consensus" / f"{_CONSENSUS_FAA_PREFIX}.faa"

    def _conda_run_cmd(self, tool_args: list[str]) -> list[str]:
        """Override to use 'emapper.py' as the binary name."""
        if self.config.conda_env:
            conda_bin = self._find_conda_binary()
            return [
                conda_bin, "run",
                "--no-capture-output",
                "-n", self.config.conda_env.name,
                self.BINARY,
            ] + tool_args
        else:
            return [self.BINARY] + tool_args

    def _report_summary(self) -> None:
        """Print annotated gene count after the run."""
        annotations = self.output_dir / "eggnog_output.emapper.annotations"
        if not annotations.exists():
            return
        try:
            with open(annotations) as f:
                rows = [l for l in f if l.strip() and not l.startswith("#")]
            count = len(rows)
            if count > 0:
                self._cprint(
                    f"[success]{count} gene(s)[/success] functionally annotated "
                    f"with GO / KEGG / COG terms."
                )
            else:
                self._cprint("No functional annotations produced.")
        except Exception:
            pass
