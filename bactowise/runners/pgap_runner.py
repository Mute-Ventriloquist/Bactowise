from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.base import BaseRunner

# PGAP data dir and marker are defined in db_manager to ensure a single
# source of truth. pgap_runner imports them rather than redefining them.
from bactowise.utils.db_manager import _DEFAULT_PGAP_DATA_DIR, _PGAP_DATA_MARKER


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

    Prerequisites (one-time, handled automatically by BactoWise):
      - pgap.py is downloaded to ~/.bactowise/bin/ on first run or when
        'bactowise db download --pgap' is called.
      - The supplemental data (~30 GB) is downloaded to
        ~/.bactowise/databases/pgap/ via pgap.py --update.
      - The only external requirement is Singularity, Apptainer, Docker,
        or Podman on PATH.

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
        """
        Locate the pgap.py wrapper script.
        Checks PATH first, then the BactoWise-managed location in
        ~/.bactowise/bin/ where download_pgap() places it.
        """
        from bactowise.utils.db_manager import _PGAP_BIN_DIR
        path = (
            shutil.which("pgap.py")
            or shutil.which("pgap")
            or (str(_PGAP_BIN_DIR / "pgap.py") if (_PGAP_BIN_DIR / "pgap.py").exists() else None)
        )
        if not path:
            raise RuntimeError(
                "  ✗  pgap.py not found.\n"
                "     Run: bactowise db download --pgap\n"
                "     This downloads pgap.py and the supplemental data automatically."
            )
        return path

    def _pgap_data_dir(self) -> Path:
        """
        Return the PGAP supplemental data directory.
        Uses params.pgap_input_dir if set, otherwise PGAP_INPUT_DIR env var,
        otherwise ~/.bactowise/databases/pgap/ (consistent with db_manager).
        """
        from_params = self.config.params.get("pgap_input_dir")
        if from_params:
            return Path(from_params).expanduser().resolve()
        from_env = os.environ.get("PGAP_INPUT_DIR")
        if from_env:
            return Path(from_env).expanduser().resolve()
        return _DEFAULT_PGAP_DATA_DIR

    def _check_data_dir(self, data_dir: Path) -> None:
        from bactowise.utils.db_manager import is_pgap_present
        if not is_pgap_present(data_dir):
            raise RuntimeError(
                f"  ✗  PGAP supplemental data not found at: {data_dir}\n"
                f"     Run once to download (~30 GB):\n"
                f"       bactowise db download --pgap\n"
                f"     Or set a custom path in pipeline.yaml:\n"
                f"       params:\n"
                f"         pgap_input_dir: /path/to/pgap/data"
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

        # Pass PGAP_INPUT_DIR so pgap.py finds the data in our managed location.
        # Merges with the current environment so other required vars are preserved.
        run_env = {**os.environ, "PGAP_INPUT_DIR": str(self._pgap_data_dir())}

        print(f"[pgap] Organism:   {organism}")
        print(f"[pgap] Runtime:    {runtime_bin}")
        print(f"[pgap] Data dir:   {self._pgap_data_dir()}")
        print(f"[pgap] Command:    {' '.join(cmd)}")
        print(f"[pgap] Logging to: {log_file}")

        with open(log_file, "w") as log:
            result = subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env=run_env,
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
          -o  output directory (pgap.py creates this itself — must not pre-exist)
          -D  container runtime binary (singularity, docker, etc.)
          -c  CPU count
          -r or -n  usage reporting flag (required — one or the other)

        Note: pgap.py requires the output directory to not already exist.
        We use a timestamped subdirectory to avoid conflicts on re-runs.
        """
        import time
        # pgap.py creates the output dir itself and fails if it already exists.
        # Use a run-specific subdir so reruns don't conflict.
        output_dir = self.output_dir / f"run_{int(time.time())}"

        cmd = [
            pgap_bin,
            "-g", str(fasta.resolve()),
            "-s", organism,
            "-o", str(output_dir),
            "-D", runtime_bin,
            "-c", str(threads),
        ]

        # Usage reporting: one flag is required by pgap.py
        cmd.append("-r" if report_usage else "-n")

        return cmd
