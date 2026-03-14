from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.base import BaseRunner

# PGAP stores its supplemental data here by default.
# Can be overridden by setting PGAP_INPUT_DIR in the environment,
# or by passing pgap_input_dir in the tool's params block.
_DEFAULT_PGAP_DATA_DIR = Path("~/.pgap").expanduser()

# Marker file that confirms pgap.py --update has completed successfully.
# PGAP extracts a build-stamped yaml into its data dir on every update.
_PGAP_DATA_MARKER = "build_number"


class PGAPRunner(BaseRunner):
    """
    Runs NCBI PGAP (Prokaryotic Genome Annotation Pipeline).

    PGAP is architecturally different from Bakta and Prokka:
      - It is invoked through pgap.py, a Python wrapper script downloaded
        from NCBI, rather than called directly as a binary or container.
      - pgap.py manages its own container (Docker or Singularity) internally.
        BactoWise does not pull or manage the PGAP image.
      - pgap.py manages its own ~30 GB supplemental data directory
        (~/.pgap/ by default). BactoWise does not download or manage this.
      - The fasta and organism name are passed directly as CLI flags.
        No submol.yaml or input.yaml is required for basic annotation.

    Prerequisites (one-time, done outside BactoWise):
      1. Download pgap.py and make it executable:
           curl -OL https://github.com/ncbi/pgap/raw/prod/scripts/pgap.py
           chmod +x pgap.py
           mv pgap.py /usr/local/bin/   # or anywhere on PATH

      2. Download the supplemental data (~30 GB):
           pgap.py --update

      3. Ensure Docker or Singularity is available on PATH.

    Config example (see pipeline.yaml for the full commented block):
      - name: pgap
        version: "2024-07-18.build7555"
        runtime: pgap
        depends_on: [checkm]
        params:
          organism: "Mycoplasmoides genitalium"   # required
          threads: 4                               # optional
          report_usage: false                      # optional, default false
    """

    # ── Preflight ─────────────────────────────────────────────────────────────

    def preflight(self) -> None:
        print(f"\n[preflight] Checking pgap tool: {self.config.name}")

        # 1. pgap.py must be on PATH
        pgap_bin = self._find_pgap()
        print(f"  ✓  Found pgap.py: {pgap_bin}")

        # 2. Supplemental data directory must exist and be populated
        data_dir = self._pgap_data_dir()
        self._check_data_dir(data_dir)

        # 3. A container runtime must be available
        runtime_bin = self._find_container_runtime()
        print(f"  ✓  Container runtime: {runtime_bin}")

        # 4. organism is required
        if not self.config.params.get("organism"):
            raise RuntimeError(
                f"  ✗  PGAP requires an organism name.\n"
                f"     Add to pipeline.yaml under params:\n"
                f"       params:\n"
                f'         organism: "Genus species"'
            )
        print(f"  ✓  Organism: {self.config.params['organism']}")

    def _find_pgap(self) -> str:
        path = shutil.which("pgap.py") or shutil.which("pgap")
        if not path:
            raise RuntimeError(
                "  ✗  pgap.py not found on PATH.\n"
                "     Download and install it once:\n"
                "       curl -OL https://github.com/ncbi/pgap/raw/prod/scripts/pgap.py\n"
                "       chmod +x pgap.py\n"
                "       mv pgap.py ~/.local/bin/   # or any directory on PATH"
            )
        return path

    def _pgap_data_dir(self) -> Path:
        """
        Return the PGAP supplemental data directory.
        Uses params.pgap_input_dir if set, otherwise PGAP_INPUT_DIR env var,
        otherwise the default ~/.pgap/.
        """
        from_params = self.config.params.get("pgap_input_dir")
        if from_params:
            return Path(from_params).expanduser().resolve()
        from_env = os.environ.get("PGAP_INPUT_DIR")
        if from_env:
            return Path(from_env).expanduser().resolve()
        return _DEFAULT_PGAP_DATA_DIR

    def _check_data_dir(self, data_dir: Path) -> None:
        if not data_dir.exists() or not any(data_dir.iterdir()):
            raise RuntimeError(
                f"  ✗  PGAP supplemental data not found at: {data_dir}\n"
                f"     Run once to download (~30 GB):\n"
                f"       pgap.py --update\n"
                f"     Or set a custom path in pipeline.yaml:\n"
                f"       params:\n"
                f"         pgap_input_dir: /path/to/pgap/data"
            )
        marker = data_dir / _PGAP_DATA_MARKER
        if not marker.exists():
            raise RuntimeError(
                f"  ✗  PGAP data directory exists at {data_dir} but appears incomplete.\n"
                f"     Re-run to finish the download:\n"
                f"       pgap.py --update"
            )
        print(f"  ✓  PGAP data directory found: {data_dir}")

    def _find_container_runtime(self) -> str:
        """
        Return whichever container runtime is available.
        pgap.py accepts the path via its -D flag.
        Singularity/Apptainer is preferred on HPC; Docker on workstations.
        """
        for binary in ["singularity", "apptainer", "docker", "podman"]:
            path = shutil.which(binary)
            if path:
                return path
        raise RuntimeError(
            "  ✗  No container runtime found on PATH.\n"
            "     PGAP requires Docker, Singularity, Apptainer, or Podman.\n"
            "     On HPC clusters: module load singularity"
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        print(f"\n[pgap] Starting NCBI PGAP annotation...")

        pgap_bin      = self._find_pgap()
        runtime_bin   = self._find_container_runtime()
        organism      = self.config.params["organism"]
        threads       = self.config.params.get("threads", 1)
        report_usage  = self.config.params.get("report_usage", False)
        log_file      = self.log_dir / "pgap.log"

        cmd = self._build_command(
            pgap_bin    = pgap_bin,
            runtime_bin = runtime_bin,
            fasta       = fasta,
            organism    = organism,
            threads     = threads,
            report_usage = report_usage,
        )

        print(f"[pgap] Organism:   {organism}")
        print(f"[pgap] Runtime:    {runtime_bin}")
        print(f"[pgap] Command:    {' '.join(cmd)}")
        print(f"[pgap] Logging to: {log_file}")

        with open(log_file, "w") as log:
            result = subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"[pgap] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        print(f"[pgap] ✓ Finished. Output at: {self.output_dir}")
        return self.output_dir

    def _build_command(
        self,
        pgap_bin: str,
        runtime_bin: str,
        fasta: Path,
        organism: str,
        threads: int,
        report_usage: bool,
    ) -> list[str]:
        """
        Build the pgap.py command.

        pgap.py manages the container internally — we pass it:
          -g  path to the input fasta
          -s  organism name (genus or genus species)
          -o  output directory
          -D  container runtime binary (singularity, docker, etc.)
          -c  CPU count
          -r or -n  usage reporting flag (required — one or the other)
        """
        cmd = [
            pgap_bin,
            "-g", str(fasta.resolve()),
            "-s", organism,
            "-o", str(self.output_dir.resolve()),
            "-D", runtime_bin,
            "-c", str(threads),
            "--no-internet",   # safe default for HPC; remove if NCBI connectivity needed
        ]

        # Usage reporting: one flag is required by pgap.py
        cmd.append("-r" if report_usage else "-n")

        return cmd
