from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.base import BaseRunner

# SIF images are stored here rather than in Singularity's internal cache.
# On HPC clusters the internal cache sits in $HOME which is often quota-limited.
# Storing SIFs explicitly also makes it obvious what has been pulled and where.
_SIF_DIR = Path("~/.bactowise/images").expanduser()


class SingularityToolRunner(BaseRunner):
    """
    Runs tools inside Singularity/Apptainer containers (e.g. Bakta, PGAP).

    Works on any system where Singularity or Apptainer is installed —
    including HPC clusters running SLURM, where Docker is not permitted.

    Key differences from DockerToolRunner
    --------------------------------------
    - No Python SDK. Singularity is invoked entirely via subprocess.
    - Images are pulled once as .sif files to ~/.bactowise/images/ and reused.
      This avoids repeated Docker Hub pulls on shared filesystems and respects
      HPC disk quotas better than Singularity's internal cache.
    - Volume mounts use --bind src:dest:mode flags, not a Python dict.
    - Uses 'singularity run' (not 'exec') so the image's entrypoint is active,
      matching Docker's behaviour. Tool arguments are passed without the binary
      name — the entrypoint supplies it, just as in Docker.
    - Containers run as the current user — no root escalation.

    Supports both 'singularity' and 'apptainer' — whichever is on PATH.
    """

    def __init__(self, tool_config: ToolConfig, output_dir: Path):
        super().__init__(tool_config, output_dir)

    # ── Preflight ─────────────────────────────────────────────────────────────

    def preflight(self) -> None:
        print(f"\n[preflight] Checking singularity tool: {self.config.name}")

        # 1. Confirm singularity/apptainer binary is available
        binary = self._find_singularity()
        print(f"  ✓  Found container runtime: {binary}")

        # 2. Validate tool-specific required fields (e.g. bakta needs a database)
        self._validate_required_fields()

        # 3. Check database path exists if configured
        if self.config.database:
            db_path = self.config.database.path
            if not db_path.exists():
                raise RuntimeError(
                    f"  ✗  Database for '{self.config.name}' not found at: {db_path}\n"
                    f"     Run: bactowise db download --bakta"
                )
            print(f"  ✓  Database found at: {db_path}")

        # 4. Pull image if the .sif file is not yet present
        self._ensure_sif()

    def _validate_required_fields(self) -> None:
        """Raise for missing fields that will definitely cause the tool to fail."""
        if self.config.name == "bakta":
            if not self.config.database:
                raise RuntimeError(
                    f"  ✗  Bakta requires a database path.\n"
                    f"     Add to pipeline.yaml:\n"
                    f"       database:\n"
                    f"         path: ~/.bactowise/databases/bakta/db-light\n"
                    f"         type: light\n"
                    f"     Then run: bactowise db download --bakta"
                )

    def _ensure_sif(self) -> None:
        """
        Pull the Docker image as a SIF file if it doesn't already exist.

        Images are stored in ~/.bactowise/images/ as
        <repo>_<name>_<tag>.sif — for example:
            oschwengers/bakta:v1.12.0  →  oschwengers_bakta_v1.12.0.sif

        This is a one-time operation. Subsequent runs reuse the local SIF.
        """
        sif = self._sif_path()

        if sif.exists():
            print(f"  ✓  SIF image found: {sif}")
            return

        _SIF_DIR.mkdir(parents=True, exist_ok=True)
        binary = self._find_singularity()
        uri    = f"docker://{self.config.image}"

        print(f"  SIF image not found. Pulling {uri}")
        print(f"  Destination: {sif}")
        print(f"  This is a one-time step and may take several minutes.\n")

        result = subprocess.run(
            [binary, "pull", str(sif), uri],
            text=True,
        )

        if result.returncode != 0 or not sif.exists():
            sif.unlink(missing_ok=True)
            raise RuntimeError(
                f"  ✗  Failed to pull Singularity image: {uri}\n"
                f"     Check your network connection and that the image exists on Docker Hub.\n"
                f"     Try manually: {binary} pull {sif} {uri}"
            )

        print(f"\n  ✓  Image pulled: {sif}")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        print(f"\n[{self.config.name}] Starting annotation inside Singularity...")

        sif      = self._sif_path()
        binds    = self._build_binds(fasta)
        cmd_args = self._build_command(fasta)
        log_file = self.log_dir / f"{self.config.name}.log"
        binary   = self._find_singularity()

        # Use 'singularity run' rather than 'singularity exec'.
        # 'run' invokes the image's entrypoint/runscript (equivalent to Docker's
        # entrypoint behaviour), so we don't need to spell out the tool binary.
        # 'exec' bypasses the entrypoint entirely — bakta is then not on PATH
        # because the micromamba environment inside the image isn't activated.
        cmd = [binary, "run"] + binds + ["--writable-tmpfs", str(sif)] + cmd_args

        print(f"[{self.config.name}] Image:      {sif}")
        print(f"[{self.config.name}] Command:    {' '.join(cmd)}")
        print(f"[{self.config.name}] Logging to: {log_file}")

        with open(log_file, "w") as log:
            result = subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"[{self.config.name}] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        print(f"[{self.config.name}] ✓ Finished. Output at: {self.output_dir}")
        return self.output_dir

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_singularity(self) -> str:
        """
        Return the path to the singularity or apptainer binary.
        Apptainer is the community fork of Singularity and is functionally
        identical for our purposes — we support whichever is available.
        """
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
        """
        Derive a stable local .sif filename from the Docker image reference.

        oschwengers/bakta:v1.12.0  →  ~/.bactowise/images/oschwengers_bakta_v1.12.0.sif
        """
        safe_name = self.config.image.replace("/", "_").replace(":", "_")
        return _SIF_DIR / f"{safe_name}.sif"

    def _build_binds(self, fasta: Path) -> list[str]:
        """
        Build --bind flags for all required volume mounts.

        Mirrors the Docker volume dict but uses Singularity's
        --bind src:dest:mode syntax.
        """
        binds = [
            "--bind", f"{fasta.parent.resolve()}:/input:ro",
            "--bind", f"{self.output_dir.resolve()}:/output:rw",
        ]
        if self.config.database:
            binds += ["--bind", f"{self.config.database.path}:/db:ro"]
        return binds

    def _build_command(self, fasta: Path) -> list[str]:
        """
        Return the arguments passed to the container's entrypoint.

        Because we use 'singularity run', the image's entrypoint is active —
        just like 'docker run'. The tool binary name is NOT included here;
        the entrypoint handles that. We only pass the tool's arguments.
        """
        if self.config.name == "bakta":
            return self._bakta_command(fasta)
        if self.config.name == "pgap":
            return self._pgap_command(fasta)
        # Generic fallback
        return ["--input", f"/input/{fasta.name}", "--output", "/output"]

    def _bakta_command(self, fasta: Path) -> list[str]:
        # No 'bakta' at the front — the image entrypoint supplies it.
        cmd = [
            f"/input/{fasta.name}",
            "--db",     "/db",
            "--output", "/output",
            "--force",
        ]
        for key, val in self.config.params.items():
            cmd += [f"--{key}", str(val)]
        return cmd

    def _pgap_command(self, fasta: Path) -> list[str]:
        # No 'pgap' at the front — the image entrypoint supplies it.
        cmd = [
            "--fasta",    f"/input/{fasta.name}",
            "--output",   "/output",
            "--database", "/db",
        ]
        for key, val in self.config.params.items():
            cmd += [f"--{key}", str(val)]
        return cmd
