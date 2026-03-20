from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console

# Resolve the engine path relative to this file so it works whether BactoWise
# is installed as a conda package, a wheel, or run directly from source.
_ENGINE_PATH = Path(__file__).parent.parent / "consensus" / "consensus_engine.py"

# GFF extensions the engine accepts
_GFF_EXTENSIONS = (".gff3", ".gff")


class ConsensusRunner(CondaToolRunner):
    """
    Stage 3 — BactoWise Consensus Engine.

    Collects GFF outputs from Bakta, Prokka, and PGAP (stage 2), copies them
    into a clean staging directory with tool-name-prefixed filenames, then
    invokes the consensus engine to merge them into a single annotation.

    Staging folder layout (<output_dir>/consensus/stage3_input/):
        bakta_annotation.gff3   — Bakta output, renamed for engine compatibility
        prokka_annotation.gff   — Prokka output, renamed
        pgap_annotation.gff     — PGAP output, renamed
        <genome>.fasta           — Copy of the input FASTA

    The staging folder is kept after the run for debugging purposes.

    Engine invocation:
        conda run -n consensus_env python /path/to/consensus_engine.py
            --input  <output_dir>/consensus/stage3_input/
            --output <output_dir>/consensus/
    """

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking consensus engine (stage 3)")

        # Warn if the engine is still a placeholder (empty implementation)
        self._check_engine_present()

        # Ensure the conda env exists, checking for 'python' as the binary
        if self.config.conda_env:
            self._ensure_consensus_env()
        else:
            if not shutil.which("python"):
                raise RuntimeError(
                    "  ✗  'python' not found on PATH and no conda_env configured.\n"
                    "     Add a conda_env block for 'consensus' in pipeline.yaml."
                )

    def _check_engine_present(self) -> None:
        """Verify consensus_engine.py exists and is importable."""
        if not _ENGINE_PATH.exists():
            raise RuntimeError(
                f"  ✗  consensus_engine.py not found at: {_ENGINE_PATH}\n"
                f"     The BactoWise installation may be incomplete. Try reinstalling."
            )
        console.print(f"  [success]✓[/success]  consensus_engine.py found: [muted]{_ENGINE_PATH}[/muted]")

    def _ensure_consensus_env(self) -> None:
        """
        Create the consensus conda environment if it doesn't already exist.
        Checks for 'python' as the target binary (not 'consensus').
        """
        env_config = self.config.conda_env
        env_name   = env_config.name
        conda_root = self._find_conda_root()
        python_path = Path(conda_root) / "envs" / env_name / "bin" / "python"

        if python_path.exists():
            console.print(
                f"  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] already exists — skipping creation."
            )
            return

        console.print(f"\n  Conda env [bold]'{env_name}'[/bold] not found. Creating it now...")
        if env_config.dependencies:
            console.print(f"    Dependencies: {env_config.dependencies}")
        console.print(f"    Channels: {env_config.channels}")
        console.print(f"    This is a one-time step and may take a few minutes.\n")

        conda_bin = self._find_conda_binary()

        cmd = [conda_bin, "create", "-n", env_name, "-y"]
        for channel in env_config.channels:
            cmd += ["-c", channel]
        cmd += env_config.dependencies   # e.g. ["pandas", "openpyxl"]

        console.print(f"  Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to create conda env '{env_name}'.\n"
                f"     Try running manually:\n"
                f"     {' '.join(cmd)}"
            )

        console.print(f"\n  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] created successfully.")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting BactoWise Consensus Engine...")

        staging_dir  = self.output_dir / "stage3_input"
        log_file     = self.log_dir / "consensus.log"

        staging_dir.mkdir(parents=True, exist_ok=True)

        # ── Step 1: collect and stage GFFs ───────────────────────────────────
        self._cprint("Collecting stage 2 outputs into staging folder...")
        console.print()

        output_root = self.output_dir.parent   # <config.output_dir>

        bakta_gff  = self._find_gff("bakta",  output_root)
        prokka_gff = self._find_gff("prokka", output_root)
        pgap_gff   = self._find_gff("pgap",   output_root)

        staged_bakta  = staging_dir / f"bakta_annotation{bakta_gff.suffix}"
        staged_prokka = staging_dir / f"prokka_annotation{prokka_gff.suffix}"
        staged_pgap   = staging_dir / f"pgap_annotation{pgap_gff.suffix}"
        staged_fasta  = staging_dir / fasta.name

        shutil.copy2(bakta_gff,  staged_bakta)
        shutil.copy2(prokka_gff, staged_prokka)
        shutil.copy2(pgap_gff,   staged_pgap)
        shutil.copy2(fasta,      staged_fasta)

        console.print(f"  [success]✓[/success]  [bold]bakta[/bold]  → [muted]{staged_bakta}[/muted]")
        console.print(f"  [success]✓[/success]  [bold]prokka[/bold] → [muted]{staged_prokka}[/muted]")
        console.print(f"  [success]✓[/success]  [bold]pgap[/bold]   → [muted]{staged_pgap}[/muted]")
        console.print(f"  [success]✓[/success]  [bold]fasta[/bold]  → [muted]{staged_fasta}[/muted]")
        console.print()

        # ── Step 2: invoke the consensus engine ──────────────────────────────
        cmd = self._build_engine_command(staging_dir, self.output_dir)

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
                f"[consensus] Consensus engine failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._cprint(f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]")
        console.print()
        return self.output_dir

    def _build_engine_command(self, staging_dir: Path, output_dir: Path) -> list[str]:
        """
        Build the full conda run command to invoke the consensus engine.

            conda run -n consensus_env python /path/to/consensus_engine.py
                --input  <staging_dir>
                --output <output_dir>
        """
        conda_bin = self._find_conda_binary()
        env_name  = self.config.conda_env.name if self.config.conda_env else None

        base = (
            [conda_bin, "run", "--no-capture-output", "-n", env_name, "python"]
            if env_name
            else ["python"]
        )

        return base + [
            str(_ENGINE_PATH),
            "--input",  str(staging_dir),
            "--output", str(output_dir),
        ]

    # ── GFF discovery helpers ─────────────────────────────────────────────────

    def _find_gff(self, tool: str, output_root: Path) -> Path:
        """
        Locate the GFF file produced by a stage 2 tool.

        Checks the tool's output directory for:
          - Normal run output (tool-specific patterns)
          - GFF-bypass output (provided_*.gff / provided_*.gff3)

        Raises RuntimeError with a clear message if no GFF is found.
        """
        tool_dir = output_root / tool

        if not tool_dir.exists():
            raise RuntimeError(
                f"  ✗  Stage 2 output directory not found: {tool_dir}\n"
                f"     Ensure '{tool}' completed successfully before running stage 3."
            )

        if tool == "bakta":
            return self._find_bakta_gff(tool_dir)
        elif tool == "prokka":
            return self._find_prokka_gff(tool_dir)
        elif tool == "pgap":
            return self._find_pgap_gff(tool_dir)
        else:
            raise ValueError(f"Unknown stage 2 tool: {tool}")

    def _find_bakta_gff(self, bakta_dir: Path) -> Path:
        # Normal Bakta run: <stem>.gff3 directly in the output dir
        gffs = [p for p in bakta_dir.glob("*.gff3") if p.is_file()]
        if gffs:
            return sorted(gffs)[0]
        # GFF-bypass: provided_<name>.gff3 or provided_<name>.gff
        for ext in _GFF_EXTENSIONS:
            provided = [p for p in bakta_dir.glob(f"provided_*{ext}") if p.is_file()]
            if provided:
                return sorted(provided)[0]
        raise RuntimeError(
            f"  ✗  No Bakta GFF found in: {bakta_dir}\n"
            f"     Expected a .gff3 file from a completed Bakta run or --gff bypass."
        )

    def _find_prokka_gff(self, prokka_dir: Path) -> Path:
        # Normal Prokka run: hardcoded prefix 'prokka_output'
        standard = prokka_dir / "prokka_output.gff"
        if standard.exists():
            return standard
        # GFF-bypass
        for ext in _GFF_EXTENSIONS:
            provided = [p for p in prokka_dir.glob(f"provided_*{ext}") if p.is_file()]
            if provided:
                return sorted(provided)[0]
        raise RuntimeError(
            f"  ✗  No Prokka GFF found in: {prokka_dir}\n"
            f"     Expected prokka_output.gff from a completed Prokka run or --gff bypass."
        )

    def _find_pgap_gff(self, pgap_dir: Path) -> Path:
        # Normal PGAP run: most recent run_<timestamp>/annot.gff
        run_dirs = sorted(
            [p for p in pgap_dir.iterdir() if p.is_dir() and p.name.startswith("run_")],
            key=lambda p: p.name,
            reverse=True,
        )
        for run_dir in run_dirs:
            gff = run_dir / "annot.gff"
            if gff.exists():
                return gff
        # GFF-bypass
        for ext in _GFF_EXTENSIONS:
            provided = [p for p in pgap_dir.glob(f"provided_*{ext}") if p.is_file()]
            if provided:
                return sorted(provided)[0]
        raise RuntimeError(
            f"  ✗  No PGAP GFF found in: {pgap_dir}\n"
            f"     Expected annot.gff inside a run_<timestamp>/ subfolder, "
            f"or a --gff bypass file."
        )
