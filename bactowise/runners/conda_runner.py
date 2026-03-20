from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from bactowise.models.config import CondaEnvConfig, ToolConfig
from bactowise.runners.base import BaseRunner
from bactowise.utils.console import console


class CondaToolRunner(BaseRunner):
    """
    Runs tools installed via conda (e.g. Prokka, Samtools, GATK).

    If conda_env is specified in the config, bactowise will:
      1. Check if the named environment already exists
      2. Create it automatically if it doesn't, installing the tool and
         any extra dependencies declared in the config
      3. Run the tool via 'conda run -n <env_name>' which activates the env
         internally, sets all correct library paths, and returns cleanly —
         no manual activation or path resolution needed

    If conda_env is not set, the tool binary is expected on the active PATH.
    """

    def __init__(self, tool_config: ToolConfig, output_dir: Path, organism: str = "", global_threads: int = 4):
        super().__init__(tool_config, output_dir, organism, global_threads)

    def preflight(self) -> None:
        console.print(f"\n[info]\\[preflight][/info] Checking conda tool: [bold]{self.config.name}[/bold]")

        if self.config.conda_env:
            self._ensure_conda_env(self.config.conda_env)
        else:
            if not self._tool_installed(self.config.name):
                raise RuntimeError(
                    f"  ✗  '{self.config.name}' not found on PATH.\n"
                    f"     Install it with: conda install -c bioconda {self.config.name}\n"
                    f"     Or add a conda_env block to your config."
                )

        # Version check — warn only, never fail
        try:
            cmd = self._conda_run_cmd(["--version"])
            result = subprocess.run(cmd, capture_output=True, text=True)
            raw = result.stdout.strip() or result.stderr.strip()
            installed_version = raw.split()[-1] if raw else "unknown"
            self._check_version(installed_version)
        except Exception:
            console.print(f"  [warning]⚠[/warning]  Could not determine installed version of [bold]{self.config.name}[/bold].")

    def _ensure_conda_env(self, env_config: CondaEnvConfig) -> None:
        """
        Create the conda environment if it doesn't already exist.
        Installs the tool + any extra dependencies declared in the config.
        Skips silently if the environment is already present.
        """
        env_name = env_config.name

        # Check if env already exists by looking for the binary inside it
        conda_root = self._find_conda_root()
        binary_path = Path(conda_root) / "envs" / env_name / "bin" / self.config.name

        if binary_path.exists():
            console.print(f"  [success]✓[/success]  Conda env [bold]'{env_name}'[/bold] already exists — skipping creation.")
            return

        console.print(f"\n  Conda env [bold]'{env_name}'[/bold] not found. Creating it now...")
        if env_config.dependencies:
            console.print(f"    Extra dependencies: {env_config.dependencies}")
        console.print(f"    Channels: {env_config.channels}")
        console.print(f"    This is a one-time step and may take a few minutes.\n")

        conda_bin = self._find_conda_binary()

        packages = [f"{self.config.name}={self.config.version}"]
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

    def _conda_run_cmd(self, tool_args: list[str]) -> list[str]:
        """
        Build a 'conda run -n <env_name> <tool> <args>' command.

        conda run activates the named env internally, runs the tool with
        all correct library paths (PERL5LIB, PYTHONPATH, etc.), then returns.
        This is the correct way to invoke tools in isolated envs without
        activating them in the calling shell.

        If no conda_env is set, falls back to calling the tool directly on PATH.
        """
        if self.config.conda_env:
            conda_bin = self._find_conda_binary()
            return [
                conda_bin, "run",
                "--no-capture-output",
                "-n", self.config.conda_env.name,
                self.config.name,
            ] + tool_args
        else:
            return [self.config.name] + tool_args

    def _find_conda_binary(self) -> str:
        """
        Locate the conda or mamba executable.

        Checks PATH first, then falls back to common install locations
        derived from conda environment variables and well-known default paths.
        """
        for binary in ["mamba", "conda"]:
            path = shutil.which(binary)
            if path:
                return path

        conda_root_candidates = []

        if os.environ.get("CONDA_PREFIX_1"):
            conda_root_candidates.append(os.environ["CONDA_PREFIX_1"])

        if os.environ.get("CONDA_PREFIX"):
            prefix = Path(os.environ["CONDA_PREFIX"])
            conda_root_candidates.append(str(prefix.parent.parent))
            conda_root_candidates.append(str(prefix))

        home = Path.home()
        conda_root_candidates += [
            str(home / "miniconda3"),
            str(home / "anaconda3"),
            str(home / "mambaforge"),
            str(home / "miniforge3"),
            "/opt/conda",
            "/opt/miniconda3",
            "/opt/anaconda3",
        ]

        for root in conda_root_candidates:
            for binary in ["mamba", "conda"]:
                candidate = Path(root) / "bin" / binary
                if candidate.exists():
                    return str(candidate)

        raise RuntimeError(
            "Could not locate conda or mamba.\n"
            "Tried PATH and common install locations. Please ensure conda is\n"
            "installed and try running: conda activate base"
        )

    def _find_conda_root(self) -> str:
        """Locate the conda installation root directory."""
        root = os.environ.get("CONDA_PREFIX_1")
        if root:
            return root
        prefix = os.environ.get("CONDA_PREFIX", "")
        if prefix:
            p = Path(prefix)
            if (p / "envs").exists():
                return str(p)
            return str(p.parent.parent)
        return os.path.expanduser("~/miniconda3")

    def run(self, fasta: Path) -> Path:
        console.print()
        self._cprint("Starting annotation...")

        cmd = self._build_command(fasta)
        log_file = self.log_dir / f"{self.config.name}.log"

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
                f"[{self.config.name}] Failed with exit code {result.returncode}.\n"
                f"Check logs at: {log_file}"
            )

        self._cprint(f"[success]✓ Finished.[/success] Output at: [muted]{self.output_dir}[/muted]")
        console.print()
        return self.output_dir

    def _build_command(self, fasta: Path) -> list[str]:
        if self.config.name == "prokka":
            return self._prokka_command(fasta)

        # Generic fallback
        tool_args = ["--input", str(fasta), "--outdir", str(self.output_dir)]
        for key, val in self.config.params.items():
            tool_args += [f"--{key}", str(val)]
        # Fall back to global_threads if threads not explicitly set in params
        if "--threads" not in tool_args:
            tool_args += ["--threads", str(self.global_threads)]
        return self._conda_run_cmd(tool_args)

    def _prokka_command(self, fasta: Path) -> list[str]:
        tool_args = [
            "--outdir", str(self.output_dir),
            "--force",
            "--prefix", "prokka_output",
        ]
        for key, val in self.config.params.items():
            tool_args += [f"--{key}", str(val)]

        # Fall back to global_threads if cpus not set in params.
        # Prokka uses --cpus rather than --threads.
        if "--cpus" not in tool_args:
            tool_args += ["--cpus", str(self.global_threads)]

        # Inject genus/species from the -n/--organism CLI arg if provided.
        # These improve gene naming accuracy but do not affect the core annotation.
        # Only add if not already set via params in the config.
        genus, species = self._organism_parts()
        if genus and "--genus" not in tool_args:
            tool_args += ["--genus", genus]
        if species and "--species" not in tool_args:
            tool_args += ["--species", species]

        tool_args.append(str(fasta))
        return self._conda_run_cmd(tool_args)
