from __future__ import annotations

import csv
import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console


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
        console.print(f"\n[info]\\[preflight][/info] Checking conda tool: [bold]{self.config.name}[/bold]")

        if self.config.conda_env:
            self._ensure_checkm_env()
        else:
            if not self._tool_installed(self.config.name):
                raise RuntimeError(
                    f"  ✗  'checkm' not found on PATH.\n"
                    f"     Add a conda_env block to your config or install manually:\n"
                    f"     conda install -c bioconda checkm-genome"
                )

        if self.config.database:
            self._configure_database(self.config.database.path)

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
            console.print(f"  [warning]⚠[/warning]  Could not determine installed version of checkm.")

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
            console.print(f"  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] already exists — skipping creation.")
            return

        console.print(f"\n  Conda env [bold]'{env_name}'[/bold] not found. Creating it now...")
        if env_config.dependencies:
            console.print(f"    Extra dependencies: {env_config.dependencies}")
        console.print(f"    Channels: {env_config.channels}")
        console.print(f"    This is a one-time step and may take a few minutes.\n")

        conda_bin = self._find_conda_binary()

        packages = [f"{self.CONDA_PACKAGE}={self.config.version}"]
        packages += env_config.dependencies

        cmd = [conda_bin, "create", "-n", env_name, "-y"]
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

        console.print(f"\n  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] created successfully.")

        # pkg_resources shim for checkm-genome=1.2.3
        site_packages = (
            Path(conda_root) / "envs" / env_name / "lib" / "python3.11" / "site-packages"
        )
        if not site_packages.exists():
            import glob
            matches = glob.glob(
                str(Path(conda_root) / "envs" / env_name / "lib" / "python3.*" / "site-packages")
            )
            if matches:
                site_packages = Path(sorted(matches)[-1])

        shim_path = site_packages / "pkg_resources.py"
        if not shim_path.exists():
            console.print(f"  Writing pkg_resources shim to [muted]{shim_path}[/muted]")
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
            console.print(f"  [success]✓[/success]  pkg_resources shim installed.")

    def _configure_database(self, db_path: Path) -> None:
        """
        Run 'checkm data setRoot <path>' inside checkm_env.
        Runs every preflight — it's idempotent and fast.
        """
        console.print(f"  Configuring CheckM database root: [muted]{db_path}[/muted]")

        if not db_path.exists():
            raise RuntimeError(
                f"  ✗  CheckM database path not found: {db_path}\n"
                f"     Run: bactowise db download --checkm"
            )

        cmd = self._conda_run_cmd(["data", "setRoot", str(db_path)])
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        combined = result.stdout.strip()

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to configure CheckM database root.\n"
                f"     Output: {combined}\n"
                f"     Try manually: conda run -n {self.config.conda_env.name} "
                f"checkm data setRoot {db_path}"
            )

        console.print(f"  [success]✓[/success]  CheckM database configured.")

    def run(self, fasta: Path) -> Path:
        self._cprint("Starting genome quality assessment...")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / "checkm.log"

        mode = self.config.params.get("mode", "taxonomy_wf")
        cmd = self._build_checkm_command(fasta, mode)

        self._cprint(f"Mode:       [muted]{mode}[/muted]")
        self._cprint(f"Command:    [muted]{' '.join(cmd)}[/muted]")
        self._cprint(f"Logging to: [muted]{log_file}[/muted]")

        with open(log_file, "w") as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"[checkm] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self.qc_result = self._parse_results()
        self._evaluate_qc()

        self._cprint(f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]")
        return self.output_dir

    def _build_checkm_command(self, fasta: Path, mode: str) -> list[str]:
        bin_dir = self.output_dir / "bins"
        bin_dir.mkdir(parents=True, exist_ok=True)

        link = bin_dir / fasta.name
        if not link.exists():
            link.symlink_to(fasta)

        checkm_out = self.output_dir / "checkm_out"
        ext = fasta.suffix.lstrip(".") or "fasta"
        threads = self.config.params.get("threads", self.global_threads)

        if mode == "taxonomy_wf":
            rank  = self.config.params.get("rank",  "domain")
            taxon = self.config.params.get("taxon", "Bacteria")
            tool_args = [
                "taxonomy_wf", rank, taxon,
                str(bin_dir), str(checkm_out),
                "-x", ext, "--tab_table",
                "-f", str(self.output_dir / "checkm_summary.tsv"),
                "-t", str(threads),
            ]
        else:
            tool_args = [
                "lineage_wf",
                str(bin_dir), str(checkm_out),
                "-x", ext, "--tab_table",
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

        completeness  = self.qc_result["completeness"]
        contamination = self.qc_result["contamination"]

        console.print()
        self._cprint("QC Results:")
        self._cprint(f"  Completeness  : [bold]{completeness:.1f}%[/bold]")
        self._cprint(f"  Contamination : [bold]{contamination:.1f}%[/bold]")

        if not self.config.qc_criteria:
            self._cprint("No qc_criteria set — skipping threshold check.")
            return

        criteria = self.config.qc_criteria
        passed = True

        if completeness < criteria.completeness:
            console.print(
                f"\n  [warning]⚠  WARNING:[/warning] Completeness [bold]{completeness:.1f}%[/bold] "
                f"is below threshold [bold]{criteria.completeness:.1f}%[/bold]"
            )
            passed = False

        if contamination > criteria.contamination:
            console.print(
                f"\n  [warning]⚠  WARNING:[/warning] Contamination [bold]{contamination:.1f}%[/bold] "
                f"exceeds threshold [bold]{criteria.contamination:.1f}%[/bold]"
            )
            passed = False

        if passed:
            console.print(f"\n  [success]✓[/success]  Genome passes QC criteria.")
        else:
            console.print(
                f"\n  [warning]⚠[/warning]  This genome does not meet the recommended QC thresholds.\n"
                f"     Annotation will proceed — review results carefully."
            )
        console.print()
