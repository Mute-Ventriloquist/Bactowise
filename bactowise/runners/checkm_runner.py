from __future__ import annotations

import csv
import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner


class CheckMRunner(CondaToolRunner):
    """
    Runs CheckM for genome assembly quality control.

    CheckM assesses genome completeness and contamination. After running,
    BactoWise parses the output and compares against qc_criteria thresholds.

    If the genome fails the criteria, BactoWise warns but continues —
    the scientist makes the final call.

    Database setup is handled automatically during preflight:
      - The database path is read from config.database.path
      - 'checkm data setRoot <path>' is run inside checkm_env so the user
        never has to do this manually

    Supported modes (set via params.mode):
        taxonomy_wf  — faster, ~2GB database (default)
        lineage_wf   — more accurate, ~40GB database
    """

    # Result stored here so pipeline.py can read it after run()
    qc_result: dict | None = None

    # The conda package name for CheckM differs from its binary name
    CONDA_PACKAGE = "checkm-genome"

    def preflight(self) -> None:
        # Override to use correct conda package name (checkm-genome, not checkm)
        print(f"\n[preflight] Checking conda tool: {self.config.name}")

        if self.config.conda_env:
            self._ensure_checkm_env()
        else:
            if not self._tool_installed(self.config.name):
                raise RuntimeError(
                    f"  ✗  'checkm' not found on PATH.\n"
                    f"     Add a conda_env block to your config or install manually:\n"
                    f"     conda install -c bioconda checkm-genome"
                )

        # Configure database root automatically if database path is provided
        if self.config.database:
            self._configure_database(self.config.database.path)

        # Version check — warn only, never fail
        try:
            result = subprocess.run(
                self._conda_run_cmd(["--version"]),
                capture_output=True,
                text=True,
            )
            raw = result.stdout.strip() or result.stderr.strip()
            installed_version = raw.split()[-1] if raw else "unknown"
            self._check_version(installed_version)
        except Exception:
            print(f"  ⚠  Could not determine installed version of checkm.")

    def _ensure_checkm_env(self) -> None:
        """
        Create checkm_env using 'checkm-genome' as the package name.
        CheckM's conda package is 'checkm-genome' but the binary is 'checkm' —
        the standard _ensure_conda_env() would install 'checkm=x.x.x' which
        doesn't exist on bioconda.
        """
        env_config = self.config.conda_env
        env_name = env_config.name
        conda_root = self._find_conda_root()
        binary_path = Path(conda_root) / "envs" / env_name / "bin" / "checkm"

        if binary_path.exists():
            print(f"  ✓  Conda env '{env_name}' already exists — skipping creation.")
            return

        print(f"  Conda env '{env_name}' not found. Creating it now...")
        if env_config.dependencies:
            print(f"    Extra dependencies: {env_config.dependencies}")
        print(f"    Channels: {env_config.channels}")
        print(f"    This is a one-time step and may take a few minutes.\n")

        conda_bin = self._find_conda_binary()

        # Use checkm-genome as the package name, not checkm
        packages = [f"{self.CONDA_PACKAGE}={self.config.version}"]
        packages += env_config.dependencies

        cmd = [conda_bin, "create", "-n", env_name, "-y"]
        for channel in env_config.channels:
            cmd += ["-c", channel]
        cmd += packages

        print(f"  Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to create conda env '{env_name}'.\n"
                f"     Try running manually:\n"
                f"     {' '.join(cmd)}"
            )

        print(f"\n  ✓  Conda env '{env_name}' created successfully.")

        # The bioconda build of checkm-genome=1.2.3 imports pkg_resources at
        # startup but doesn't handle the case where it's missing (unlike newer
        # pip builds which have a try/except fallback). Rather than fighting
        # conda/pip setuptools version conflicts, we write a minimal shim
        # directly to the env's site-packages. This is deterministic and works
        # regardless of setuptools version or conda channel behaviour.
        site_packages = (
            Path(conda_root) / "envs" / env_name / "lib" / "python3.11" / "site-packages"
        )
        # Fall back to glob if Python version differs
        if not site_packages.exists():
            import glob
            matches = glob.glob(
                str(Path(conda_root) / "envs" / env_name / "lib" / "python3.*" / "site-packages")
            )
            if matches:
                site_packages = Path(sorted(matches)[-1])

        shim_path = site_packages / "pkg_resources.py"
        if not shim_path.exists():
            print(f"  Writing pkg_resources shim to {shim_path}")
            shim_path.write_text(
                "# Minimal pkg_resources shim for checkm-genome=1.2.3\n"
                "import os as _os, sys as _sys\n"
                "def resource_filename(package_or_requirement, resource_name):\n"
                "    if isinstance(package_or_requirement, str):\n"
                "        mod = _sys.modules.get(package_or_requirement)\n"
                "        base = _os.path.dirname(mod.__file__) if mod else _os.getcwd()\n"
                "    else:\n"
                "        base = _os.path.dirname(package_or_requirement.__file__)\n"
                "    return _os.path.join(base, resource_name)\n"
            )
            print(f"  ✓  pkg_resources shim installed.")

    def _configure_database(self, db_path: Path) -> None:
        """
        Run 'checkm data setRoot <path>' inside checkm_env.
        This writes the database location into CheckM's config file so it
        knows where to find its marker genes at runtime.
        Runs every preflight — it's idempotent and fast.
        """
        print(f"  Configuring CheckM database root: {db_path}")

        if not db_path.exists():
            raise RuntimeError(
                f"  ✗  CheckM database path not found: {db_path}\n"
                f"     Download it first:\n"
                f"       mkdir -p {db_path}\n"
                f"       cd {db_path}\n"
                f"       wget https://data.ace.uq.edu.au/public/CheckM_databases/checkm_data_2015_01_16.tar.gz\n"
                f"       tar -xzf checkm_data_2015_01_16.tar.gz"
            )

        cmd = self._conda_run_cmd(["data", "setRoot", str(db_path)])
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to configure CheckM database root.\n"
                f"     Error: {result.stderr.strip()}\n"
                f"     Try manually: conda run -n {self.config.conda_env.name} "
                f"checkm data setRoot {db_path}"
            )

        print(f"  ✓  CheckM database configured.")

    def run(self, fasta: Path) -> Path:
        print(f"\n[checkm] Starting genome quality assessment...")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / "checkm.log"

        mode = self.config.params.get("mode", "taxonomy_wf")
        cmd = self._build_checkm_command(fasta, mode)

        print(f"[checkm] Mode:    {mode}")
        print(f"[checkm] Command: {' '.join(cmd)}")
        print(f"[checkm] Logging to: {log_file}")

        with open(log_file, "w") as log:
            result = subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"[checkm] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self.qc_result = self._parse_results()
        self._evaluate_qc()

        print(f"[checkm] ✓ Finished. Output at: {self.output_dir}")
        return self.output_dir

    def _build_checkm_command(self, fasta: Path, mode: str) -> list[str]:
        # CheckM operates on a directory of bins, not a single fasta.
        # We create a bin dir containing just our fasta via symlink.
        bin_dir = self.output_dir / "bins"
        bin_dir.mkdir(parents=True, exist_ok=True)

        link = bin_dir / fasta.name
        if not link.exists():
            link.symlink_to(fasta)

        checkm_out = self.output_dir / "checkm_out"
        ext = fasta.suffix.lstrip(".") or "fasta"

        # All params have sensible defaults — none are required in pipeline.yaml
        threads = self.config.params.get("threads", 1)

        if mode == "taxonomy_wf":
            rank  = self.config.params.get("rank",  "domain")
            taxon = self.config.params.get("taxon", "Bacteria")
            tool_args = [
                "taxonomy_wf",
                rank, taxon,
                str(bin_dir),
                str(checkm_out),
                "-x", ext,
                "--tab_table",
                "-f", str(self.output_dir / "checkm_summary.tsv"),
                "-t", str(threads),
            ]
        else:
            tool_args = [
                "lineage_wf",
                str(bin_dir),
                str(checkm_out),
                "-x", ext,
                "--tab_table",
                "-f", str(self.output_dir / "checkm_summary.tsv"),
                "-t", str(threads),
            ]

        return self._conda_run_cmd(tool_args)

    def _parse_results(self) -> dict:
        tsv = self.output_dir / "checkm_summary.tsv"

        if not tsv.exists():
            raise RuntimeError(
                f"[checkm] Expected output file not found: {tsv}\n"
                f"CheckM may have failed silently. Check logs at: {self.log_dir / 'checkm.log'}"
            )

        with open(tsv) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        if not rows:
            raise RuntimeError("[checkm] Output TSV is empty — no results to parse.")

        row = rows[0]

        try:
            return {
                "completeness": float(row.get("Completeness", 0)),
                "contamination": float(row.get("Contamination", 100)),
                "strain_heterogeneity": float(row.get("Strain heterogeneity", 0)),
            }
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"[checkm] Could not parse QC metrics from TSV: {e}")

    def _evaluate_qc(self) -> None:
        if not self.qc_result:
            return

        completeness = self.qc_result["completeness"]
        contamination = self.qc_result["contamination"]

        print(f"\n[checkm] QC Results:")
        print(f"          Completeness  : {completeness:.1f}%")
        print(f"          Contamination : {contamination:.1f}%")

        if not self.config.qc_criteria:
            print(f"[checkm] No qc_criteria set — skipping threshold check.")
            return

        criteria = self.config.qc_criteria
        passed = True

        if completeness < criteria.completeness:
            print(
                f"\n  ⚠  WARNING: Completeness {completeness:.1f}% is below "
                f"threshold {criteria.completeness:.1f}%"
            )
            passed = False

        if contamination > criteria.contamination:
            print(
                f"\n  ⚠  WARNING: Contamination {contamination:.1f}% exceeds "
                f"threshold {criteria.contamination:.1f}%"
            )
            passed = False

        if passed:
            print(f"  ✓  Genome passes QC criteria.")
        else:
            print(
                f"\n  ⚠  This genome does not meet the recommended QC thresholds.\n"
                f"     Annotation will proceed — review results carefully."
            )
