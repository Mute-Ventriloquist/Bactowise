from __future__ import annotations

import subprocess
from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.utils.console import console


class MobileElementFinderRunner(CondaToolRunner):
    """
    Stage 4 — MobileElementFinder: transposon, insertion sequence, and
    integron detection.

    MobileElementFinder identifies mobile genetic elements (MGEs) in assembled
    bacterial genomes by aligning contigs against a curated reference database
    of known elements. It detects transposons, insertion sequences (IS),
    integrons, and flags putative composite transposons.

    Input
    -----
    The original genome FASTA passed to `bactowise run -f`. No stage 2/3
    outputs are required.

    Installation
    ------------
    Installed via pip inside a conda env that provides BLAST+ and KMA as
    conda dependencies. The MGE reference database is bundled with the pip
    package — no separate download step is needed.

    Output
    ------
    <output_dir>/mefinder/
        mefinder_output.csv    MGE predictions with quality metrics
        mefinder_output.gff    MGE locations in GFF3 format
        logs/mefinder.log

    Conda env : mefinder_env (with blast and kma installed via conda,
                               MobileElementFinder installed via pip)

    Optional params (set in pipeline.yaml under params:)
    -----------------------------------------------------
    threads : int  override global thread count
    """

    # The conda package name for the env binary differs from tool name
    BINARY = "mefinder"

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking mefinder (stage 4)")

        if self.config.conda_env:
            self._ensure_mefinder_env()
        else:
            if not self._tool_installed(self.BINARY):
                raise RuntimeError(
                    "  ✗  'mefinder' not found on PATH and no conda_env configured.\n"
                    "     Add a conda_env block for 'mefinder' in pipeline.yaml."
                )

        # Version check — warn only, never fail
        try:
            result = subprocess.run(
                self._conda_run_cmd(["find", "--version"]),
                capture_output=True, text=True,
            )
            raw = result.stdout.strip() or result.stderr.strip()
            installed_version = raw.split()[-1] if raw else "unknown"
            self._check_version(installed_version)
        except Exception:
            console.print(
                f"  [warning]⚠[/warning]  Could not determine installed version of mefinder."
            )

    def _ensure_mefinder_env(self) -> None:
        """
        Create mefinder_env with blast and kma via conda, then install
        MobileElementFinder via pip. Checks for the mefinder binary.
        """
        env_config  = self.config.conda_env
        env_name    = env_config.name
        conda_root  = self._find_conda_root()
        binary_path = Path(conda_root) / "envs" / env_name / "bin" / self.BINARY

        if binary_path.exists():
            console.print(
                f"  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] "
                f"already exists — skipping creation."
            )
            # Always ensure the shim is present — covers existing envs that
            # were created before this fix was added.
            self._write_pkg_resources_shim(env_name)
            return

        console.print(f"\n  Conda env [bold]'{env_name}'[/bold] not found. Creating it now...")
        console.print(f"    Channels: {env_config.channels}")
        console.print(f"    This is a one-time step and may take a few minutes.\n")

        conda_bin = self._find_conda_binary()

        # Step 1: create env with conda deps.
        # - python=3.11 pinned: biopython has no pre-built wheel for 3.12+
        # - All MobileElementFinder pure-python deps that have conda packages
        #   are installed here so pip install --no-deps doesn't miss them.
        #   (pyyaml, click, attrs, tabulate all have conda-forge packages)
        _EXCLUDE = {"MobileElementFinder", "mobileelement-finder",
                    "biopython", "pyyaml", "click", "attrs", "tabulate"}
        conda_deps = ["python=3.11", "biopython", "pyyaml", "click",
                      "attrs", "tabulate", "blast", "kma"] + [
            d for d in env_config.dependencies if d not in _EXCLUDE
        ]

        cmd = [conda_bin, "create", "-n", env_name, "-y", "--strict-channel-priority"]
        for channel in env_config.channels:
            cmd += ["-c", channel]
        cmd += conda_deps

        console.print(f"  Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to create conda env '{env_name}'.\n"
                f"     Try running manually:\n"
                f"     {' '.join(cmd)}"
            )

        # Step 2: install MobileElementFinder via pip into the env.
        # --no-deps skips biopython reinstallation — it is already present
        # as the conda binary build and does not need to be rebuilt from source.
        pip_cmd = [
            conda_bin, "run", "--no-capture-output",
            "-n", env_name,
            "pip", "install", "MobileElementFinder", "--no-deps",
        ]
        console.print(f"  Installing MobileElementFinder via pip (--no-deps)...")
        console.print(f"  Running: {' '.join(pip_cmd)}\n")

        result = subprocess.run(pip_cmd, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"  ✗  Failed to install MobileElementFinder via pip.\n"
                f"     Try running manually:\n"
                f"       conda run -n {env_name} pip install MobileElementFinder --no-deps"
            )

        # MobileElementFinder imports pkg_resources at startup but setuptools
        # is not always present in conda envs. Write the same minimal shim
        # used for CheckM so the import succeeds without pulling in setuptools.
        self._write_pkg_resources_shim(env_name)

        console.print(
            f"\n  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] "
            f"created successfully."
        )

    def _write_pkg_resources_shim(self, env_name: str) -> None:
        """
        Write a minimal pkg_resources.py shim to the env's site-packages.
        MobileElementFinder calls pkg_resources.resource_string() at import
        time to load its bundled database files. The shim implements only
        what is needed and is skipped if the real setuptools is already present.
        """
        import glob
        conda_root  = self._find_conda_root()
        base        = Path(conda_root) / "envs" / env_name / "lib"

        matches = glob.glob(str(base / "python3.*" / "site-packages"))
        if not matches:
            return
        site_packages = Path(sorted(matches)[-1])
        shim_path     = site_packages / "pkg_resources.py"

        if shim_path.exists():
            return

        console.print(f"  Writing pkg_resources shim to [muted]{shim_path}[/muted]")
        shim_path.write_text(
            "# Minimal pkg_resources shim for MobileElementFinder\n"
            "import os as _os, sys as _sys\n"
            "def resource_string(package_or_requirement, resource_name):\n"
            "    if isinstance(package_or_requirement, str):\n"
            "        mod = _sys.modules.get(package_or_requirement)\n"
            "        base = _os.path.dirname(mod.__file__) if mod else _os.getcwd()\n"
            "    else:\n"
            "        base = _os.path.dirname(package_or_requirement.__file__)\n"
            "    path = _os.path.join(base, resource_name)\n"
            "    with open(path, 'rb') as f:\n"
            "        return f.read()\n"
            "def resource_filename(package_or_requirement, resource_name):\n"
            "    if isinstance(package_or_requirement, str):\n"
            "        mod = _sys.modules.get(package_or_requirement)\n"
            "        base = _os.path.dirname(mod.__file__) if mod else _os.getcwd()\n"
            "    else:\n"
            "        base = _os.path.dirname(package_or_requirement.__file__)\n"
            "    return _os.path.join(base, resource_name)\n"
        )
        console.print(f"  [success]✓[/success]  pkg_resources shim installed.")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting mobile element detection...")

        output_prefix = self.output_dir / "mefinder_output"
        log_file      = self.log_dir / "mefinder.log"
        cmd           = self._build_command(fasta, output_prefix)

        self._cprint(f"[label]Input:[/label]     [muted]{fasta}[/muted]")
        self._cprint(f"[label]Output:[/label]    [muted]{output_prefix}.*[/muted]")
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
                f"[mefinder] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._report_summary(output_prefix)

        self._cprint(
            f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]"
        )
        console.print()
        return self.output_dir

    def _build_command(self, fasta: Path, output_prefix: Path) -> list[str]:
        """
        Build the mefinder command.

            mefinder find -c <fasta> -t <threads> -g <output_prefix>

        The output prefix is a positional argument — mefinder appends
        .csv and .gff to it automatically. -g requests GFF3 output.
        """
        threads = self.config.params.get("threads", self.global_threads)

        tool_args = [
            "find",
            "-c", str(fasta.resolve()),
            "-t", str(threads),
            "-g",
            str(output_prefix),
        ]

        return self._conda_run_cmd(tool_args)

    def _report_summary(self, output_prefix: Path) -> None:
        """Print a brief MGE count after the run."""
        csv = Path(str(output_prefix) + ".csv")
        if not csv.exists():
            return
        try:
            with open(csv) as f:
                # First 5 lines are comment headers starting with #
                rows = [l for l in f if l.strip() and not l.startswith("#")]
            count = len(rows) - 1 if rows else 0  # subtract header row
            if count > 0:
                self._cprint(
                    f"[success]{count} mobile element(s)[/success] detected. "
                    f"Results in [muted]{csv.name}[/muted]."
                )
            else:
                self._cprint("No mobile elements detected.")
        except Exception:
            pass

    def _conda_run_cmd(self, tool_args: list[str]) -> list[str]:
        """Override to use 'mefinder' as the binary name."""
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
