from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.base import BaseRunner
from bactowise.utils.console import console

# SIF images are stored here rather than in Singularity's internal cache.
# On HPC clusters the internal cache sits in $HOME which is often quota-limited.
# Storing SIFs explicitly also makes it obvious what has been pulled and where.
_SIF_DIR = Path("~/.bactowise/images").expanduser()


class SingularityToolRunner(BaseRunner):
    """
    Runs tools inside Singularity/Apptainer containers (e.g. Bakta).

    Works on any system where Singularity or Apptainer is installed —
    including HPC clusters running SLURM, where Docker is not permitted.
    """

    def __init__(self, tool_config: ToolConfig, output_dir: Path, organism: str = "", global_threads: int = 4):
        super().__init__(tool_config, output_dir, organism, global_threads)

    # ── Preflight ─────────────────────────────────────────────────────────────

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking singularity tool: [bold]{self.config.name}[/bold]")

        binary = self._find_singularity()
        console.print(f"  [success]✓[/success]  Found container runtime: [muted]{binary}[/muted]")

        self._validate_required_fields()

        if self.config.database:
            db_path = self.config.database.path
            if not db_path.exists():
                raise RuntimeError(
                    f"  ✗  Database for '{self.config.name}' not found at: {db_path}\n"
                    f"     Run: bactowise db download --bakta"
                )
            console.print(f"  [success]✓[/success]  Database found at: [muted]{db_path}[/muted]")

        self._ensure_sif()

    def _validate_required_fields(self) -> None:
        if self.config.name == "bakta":
            if not self.config.database:
                raise RuntimeError(
                    f"  ✗  Bakta requires a database path.\n"
                    f"     Add to pipeline.yaml:\n"
                    f"       database:\n"
                    f"         path: ~/.bactowise/databases/bakta/db\n"
                    f"         type: full\n"
                    f"     Then run: bactowise db download --bakta"
                )

    def _ensure_sif(self) -> None:
        sif = self._sif_path()

        if sif.exists():
            console.print(f"  [success]✓[/success]  SIF image found: [muted]{sif}[/muted]")
            return

        _SIF_DIR.mkdir(parents=True, exist_ok=True)
        binary = self._find_singularity()
        uri    = f"docker://{self.config.image}"

        console.print(f"  SIF image not found. Pulling [bold]{uri}[/bold]")
        console.print(f"  Destination: [muted]{sif}[/muted]")
        console.print(f"  This is a one-time step and may take several minutes.\n")

        result = subprocess.run([binary, "pull", str(sif), uri], text=True)

        if result.returncode != 0 or not sif.exists():
            sif.unlink(missing_ok=True)
            raise RuntimeError(
                f"  ✗  Failed to pull Singularity image: {uri}\n"
                f"     Check your network connection and that the image exists on Docker Hub.\n"
                f"     Try manually: {binary} pull {sif} {uri}"
            )

        console.print(f"\n  [success]✓[/success]  Image pulled: [muted]{sif}[/muted]")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting annotation inside Singularity...")

        sif      = self._sif_path()
        binds    = self._build_binds(fasta)
        cmd_args = self._build_command(fasta)
        log_file = self.log_dir / f"{self.config.name}.log"
        binary   = self._find_singularity()

        cmd = [binary, "run"] + binds + ["--writable-tmpfs", str(sif)] + cmd_args

        self._cprint(f"[label]Image:[/label]      [muted]{sif}[/muted]")
        self._cprint(f"[label]Command:[/label]    [muted]{' '.join(cmd)}[/muted]")
        self._cprint(f"[label]Logging to:[/label] [muted]{log_file}[/muted]")

        with open(log_file, "w") as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"[{self.config.name}] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._cprint(f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]")
        console.print()
        return self.output_dir

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_singularity(self) -> str:
        for binary in ["singularity", "apptainer"]:
            path = shutil.which(binary)
            if path:
                return path
        raise RuntimeError(
            "  ✗  Neither 'singularity' nor 'apptainer' was found on PATH.\n"
            "     On HPC clusters, try: module load singularity\n"
            "     For local install: https://apptainer.org/docs/admin/main/installation.html"
        )

    def _sif_path(self) -> Path:
        safe_name = self.config.image.replace("/", "_").replace(":", "_")
        return _SIF_DIR / f"{safe_name}.sif"

    def _build_binds(self, fasta: Path) -> list[str]:
        binds = [
            "--bind", f"{fasta.parent.resolve()}:/input:ro",
            "--bind", f"{self.output_dir.resolve()}:/output:rw",
        ]
        if self.config.database:
            binds += ["--bind", f"{self.config.database.path}:/db:ro"]
        return binds

    def _build_command(self, fasta: Path) -> list[str]:
        if self.config.name == "bakta":
            return self._bakta_command(fasta)
        if self.config.name == "pgap":
            return self._pgap_command(fasta)
        return ["--input", f"/input/{fasta.name}", "--output", "/output"]

    def _bakta_command(self, fasta: Path) -> list[str]:
        cmd = [
            f"/input/{fasta.name}",
            "--db",     "/db",
            "--output", "/output",
            "--force",
        ]
        for key, val in self.config.params.items():
            cmd += [f"--{key}", str(val)]

        if "--threads" not in cmd:
            cmd += ["--threads", str(self.global_threads)]

        genus, species = self._organism_parts()
        if genus and "--genus" not in cmd:
            cmd += ["--genus", genus]
        if species and "--species" not in cmd:
            cmd += ["--species", species]

        return cmd

    def _pgap_command(self, fasta: Path) -> list[str]:
        cmd = [
            "--fasta",    f"/input/{fasta.name}",
            "--output",   "/output",
            "--database", "/db",
        ]
        for key, val in self.config.params.items():
            cmd += [f"--{key}", str(val)]
        return cmd
