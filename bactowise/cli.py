from __future__ import annotations

from pathlib import Path

import typer

from bactowise.pipeline import Pipeline
from bactowise.utils.config_loader import load_config
from bactowise.utils.db_manager import (
    DEFAULT_DB_ROOT,
    download_bakta,
    download_checkm,
    is_bakta_present,
    is_checkm_present,
)

app = typer.Typer(
    name="bactowise",
    help="""
\b
BactoWise — Bacterial Genome QC & Annotation Pipeline

Runs genome quality assessment (CheckM) followed by parallel gene annotation
(Prokka, Bakta). Tools run in dependency order — QC first, then annotation
only after QC completes. All tools are configured via a YAML config file.

\b
QUICK START
-----------
Step 1 — Download databases (one-time setup):
    bactowise db download

Step 2 — Validate your config file:
    bactowise validate -c pipeline.yaml

Step 3 — Run the pipeline on a genome:
    bactowise run -f genome.fasta -c pipeline.yaml

\b
PIPELINE STAGES
---------------
Stage 1 — Quality Control (CheckM):
    Assesses genome completeness and contamination.
    Default pass criteria: completeness > 95%, contamination < 5%.
    If the genome fails, BactoWise warns you and continues annotation
    — the scientist makes the final call.

Stage 2 — Gene Annotation (Prokka + Bakta, in parallel):
    Both tools run simultaneously after CheckM completes.

\b
FIRST TIME SETUP
----------------
Before running, make sure you have:

  1. Databases downloaded (stored in ~/.bactowise/databases/):
       bactowise db download

  2. Docker running (for Docker-based tools like Bakta):
       Linux:   sudo systemctl start docker
       Mac/Win: Open Docker Desktop

  3. A genome file in .fasta or .fna format.
     Download the M. genitalium test genome:
       efetch -db nucleotide -id NC_000908.2 -format fasta > mgenitalium.fasta

\b
CONDA TOOLS (CheckM, Prokka)
-----------------------------
Tools with a conda_env block in pipeline.yaml will have their
conda environment created automatically on first run. No manual
setup needed.

\b
OUTPUT
------
Results are written to separate subfolders under output_dir:
    results/
    ├── checkm/
    │   ├── checkm_summary.tsv
    │   └── logs/
    ├── prokka/
    │   └── logs/
    └── bakta/
        └── logs/
""",
    add_completion=False,
)

# ── db sub-command group ──────────────────────────────────────────────────────

db_app = typer.Typer(
    name="db",
    help="Manage BactoWise databases (download, status).",
    add_completion=False,
)
app.add_typer(db_app, name="db")


@db_app.command("download")
def db_download(
    checkm: bool = typer.Option(
        False, "--checkm",
        help="Download the CheckM database only.",
    ),
    bakta: bool = typer.Option(
        False, "--bakta",
        help="Download the Bakta database only.",
    ),
    force: bool = typer.Option(
        False, "--force-db-download",
        help=(
            "Re-download databases even if they are already present. "
            "The existing database directory will be deleted and replaced."
        ),
    ),
):
    """
    Download the databases required by BactoWise.

    \b
    By default, downloads both databases:
      ~/.bactowise/databases/checkm/   — CheckM marker gene database (~2 GB)
      ~/.bactowise/databases/bakta/    — Bakta annotation database, light (~2 GB)

    \b
    If a database is already present it is skipped unless --force-db-download
    is given. The presence check looks for key marker files inside each database
    directory, so an interrupted previous download is detected and re-run.

    \b
    Examples:
      bactowise db download
      bactowise db download --checkm
      bactowise db download --bakta
      bactowise db download --force-db-download
      bactowise db download --checkm --force-db-download
    """
    download_checkm_flag = checkm or (not checkm and not bakta)
    download_bakta_flag  = bakta  or (not checkm and not bakta)

    typer.echo(f"\nBactoWise — Database Download")
    typer.echo(f"  Storage root : {DEFAULT_DB_ROOT}")
    typer.echo(f"  Mode         : {'force re-download' if force else 'skip if already present'}\n")

    errors = []

    if download_checkm_flag:
        try:
            download_checkm(force=force)
        except RuntimeError as e:
            typer.echo(f"\n✗ CheckM download failed: {e}", err=True)
            errors.append("checkm")

    if download_bakta_flag:
        try:
            download_bakta(force=force)
        except RuntimeError as e:
            typer.echo(f"\n✗ Bakta download failed: {e}", err=True)
            errors.append("bakta")

    if errors:
        typer.echo(
            f"\n✗ {len(errors)} database(s) failed: {', '.join(errors)}\n",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo("\n✓ All requested databases are ready.")
    typer.echo("\nYou can now run the pipeline:")
    typer.echo("  bactowise run -f <genome.fasta> -c pipeline.yaml\n")


@db_app.command("status")
def db_status():
    """
    Show whether the required databases have been downloaded.

    \b
    Checks for marker files inside each database directory to confirm
    a complete (not just partial) download.

    \b
    Example:
      bactowise db status
    """
    typer.echo(f"\nBactoWise — Database Status")
    typer.echo(f"  Storage root: {DEFAULT_DB_ROOT}\n")

    checkm_ok = is_checkm_present()
    bakta_ok  = is_bakta_present()

    typer.echo(f"  {'✓' if checkm_ok else '✗'}  CheckM  → {DEFAULT_DB_ROOT / 'checkm'}")
    typer.echo(f"  {'✓' if bakta_ok  else '✗'}  Bakta   → {DEFAULT_DB_ROOT / 'bakta'}")

    if not checkm_ok or not bakta_ok:
        typer.echo(f"\n  Run 'bactowise db download' to fetch missing databases.\n")
    else:
        typer.echo(f"\n  All databases present.\n")


# ── run command ───────────────────────────────────────────────────────────────

@app.command()
def run(
    fasta: Path = typer.Option(
        ..., "-f", "--fasta",
        help=(
            "Path to input genome file in .fasta or .fna format. "
            "Example: -f /data/mgenitalium.fasta"
        ),
        exists=True,
        readable=True,
    ),
    config: Path = typer.Option(
        ..., "-c", "--config",
        help=(
            "Path to the pipeline config YAML file. "
            "Example: -c pipeline.yaml"
        ),
        exists=True,
        readable=True,
    ),
    skip: list[str] = typer.Option(
        [],
        "--skip",
        help=(
            "Skip a tool by name. Can be repeated to skip multiple tools. "
            "Skipped tools are excluded from preflight and execution. "
            "Downstream tools that depend on a skipped tool still run, "
            "but a warning is printed if a QC tool is skipped. "
            "Example: --skip checkm   or   --skip prokka --skip bakta"
        ),
    ),
):
    """
    Run the QC and annotation pipeline on a genome.

    \b
    Executes tools in dependency order as defined by depends_on in the
    config. Within each stage, tools run simultaneously. For example:

      Stage 1: checkm             (QC gate — runs alone first)
      Stage 2: prokka + bakta     (annotation — run in parallel after checkm)

    \b
    Use --skip to exclude one or more tools from this run without editing
    the config file. Downstream tools that depend on a skipped tool are
    automatically unblocked and still run. If a QC tool is skipped, a
    warning is printed before annotation begins.

    \b
    Examples:
      bactowise run -f mgenitalium.fasta -c pipeline.yaml
      bactowise run -f genome.fna -c pipeline.yaml --skip checkm
      bactowise run -f genome.fna -c pipeline.yaml --skip prokka --skip bakta
    """
    typer.echo(f"\nBactoWise — Bacterial Genome QC & Annotation Pipeline")
    typer.echo(f"  Genome : {fasta}")
    typer.echo(f"  Config : {config}")
    if skip:
        typer.echo(f"  Skip   : {', '.join(skip)}")
    typer.echo(f"  Tip    : Run 'bactowise validate -c {config}' first to check your config.\n")

    try:
        pipeline_config = load_config(config)
        pipeline = Pipeline(pipeline_config, skip=set(skip))
        pipeline.run(fasta)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"\n✗ Error: {e}", err=True)
        raise typer.Exit(code=1)
    except RuntimeError as e:
        typer.echo(f"\n✗ Pipeline failed: {e}", err=True)
        raise typer.Exit(code=1)


# ── validate command ──────────────────────────────────────────────────────────

@app.command()
def validate(
    config: Path = typer.Option(
        ..., "-c", "--config",
        help="Path to the pipeline config YAML file to validate.",
        exists=True,
    ),
):
    """
    Validate a config file without running anything.

    \b
    Checks that pipeline.yaml is correctly structured — required fields,
    valid runtimes, valid depends_on references, and well-formed tool configs.

    \b
    Does NOT check:
      - Whether Docker is running
      - Whether conda environments exist
      - Whether database paths exist on disk
    These are checked at runtime when you run 'bactowise run'.

    \b
    Example:
      bactowise validate -c pipeline.yaml
    """
    try:
        cfg = load_config(config)
        typer.echo(f"\n✓ Config is valid. Found {len(cfg.tools)} tool(s):\n")
        for tool in cfg.tools:
            role_tag = f" [{tool.role}]" if tool.role == "qc" else ""
            typer.echo(f"  {tool.name}{role_tag}")
            typer.echo(f"    version    : {tool.version}")
            typer.echo(f"    runtime    : {tool.runtime}")
            if tool.depends_on:
                typer.echo(f"    depends_on : {', '.join(tool.depends_on)}")
            if tool.runtime == "docker":
                typer.echo(f"    image      : {tool.image}")
            if tool.conda_env:
                typer.echo(f"    conda env  : {tool.conda_env.name}")
                if tool.conda_env.dependencies:
                    typer.echo(f"    deps       : {', '.join(tool.conda_env.dependencies)}")
            if tool.database:
                typer.echo(f"    database   : {tool.database.path}")
            if tool.qc_criteria:
                typer.echo(f"    qc pass    : completeness > {tool.qc_criteria.completeness}%, "
                           f"contamination < {tool.qc_criteria.contamination}%")
            typer.echo()
        typer.echo(f"  output_dir : {cfg.output_dir}")
        typer.echo(f"  threads    : {cfg.threads}")
        typer.echo(f"\nRun the pipeline with:")
        typer.echo(f"  bactowise run -f <genome.fasta> -c {config}\n")
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"\n✗ Config invalid: {e}", err=True)
        raise typer.Exit(code=1)


def main():
    app()
