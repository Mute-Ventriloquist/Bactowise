from __future__ import annotations

from pathlib import Path

import typer

from bactowise.pipeline import Pipeline
from bactowise.utils.config_loader import load_config

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
Step 1 — Validate your config file:
    bactowise validate -c pipeline.yaml

Step 2 — Run the pipeline on a genome:
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

  1. Docker running (for Docker-based tools like Bakta):
       Linux:   sudo systemctl start docker
       Mac/Win: Open Docker Desktop

  2. Bakta database downloaded (~2 GB, one-time):
       bakta_db download --output ~/bakta_db --type light

  3. CheckM database downloaded (~2 GB, one-time):
       mkdir -p ~/checkm_db && cd ~/checkm_db
       wget https://data.ace.uq.edu.au/public/CheckM_databases/checkm_data_2015_01_16.tar.gz
       tar -xzf checkm_data_2015_01_16.tar.gz
     Then set database.path in pipeline.yaml — BactoWise configures
     CheckM automatically via checkm data setRoot on every preflight.

  4. A genome file in .fasta or .fna format.
     Download the M. genitalium test genome:
       efetch -db nucleotide -id NC_000908.2 -format fasta > mgenitalium.fasta

\b
CONDA TOOLS (CheckM, Prokka)
-----------------------------
Tools with a 'conda_env' block in pipeline.yaml will have their
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
            "Path to the pipeline config YAML file that defines which tools "
            "to run, their versions, parameters, and dependencies. "
            "Example: -c pipeline.yaml"
        ),
        exists=True,
        readable=True,
    ),
):
    """
    Run the QC and annotation pipeline on a genome.

    \b
    Executes tools in dependency order as defined by 'depends_on' in the
    config. Within each stage, tools run simultaneously. For example:

      Stage 1: checkm             (QC gate — runs alone first)
      Stage 2: prokka + bakta     (annotation — run in parallel after checkm)

    \b
    On first run, bactowise will automatically:
      - Create any missing conda environments (e.g. checkm_env, prokka_env)
      - Pull any missing Docker images (e.g. oschwengers/bakta)

    \b
    Examples:
      bactowise run -f mgenitalium.fasta -c pipeline.yaml
      bactowise run -f /data/genome.fna -c /configs/my_pipeline.yaml
    """
    typer.echo(f"\nBactoWise — Bacterial Genome QC & Annotation Pipeline")
    typer.echo(f"  Genome : {fasta}")
    typer.echo(f"  Config : {config}")
    typer.echo(f"  Tip    : Run 'bactowise validate -c {config}' first to check your config.\n")

    try:
        pipeline_config = load_config(config)
        pipeline = Pipeline(pipeline_config)
        pipeline.run(fasta)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"\n✗ Error: {e}", err=True)
        raise typer.Exit(code=1)
    except RuntimeError as e:
        typer.echo(f"\n✗ Pipeline failed: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def validate(
    config: Path = typer.Option(
        ..., "-c", "--config",
        help=(
            "Path to the pipeline config YAML file to validate. "
            "Example: -c pipeline.yaml"
        ),
        exists=True,
    ),
):
    """
    Validate a config file without running anything.

    \b
    Checks that your pipeline.yaml is correctly structured — all required
    fields are present, runtimes are valid, depends_on references are valid,
    and tool configs are well-formed.

    \b
    Does NOT check:
      - Whether Docker is running
      - Whether conda environments exist
      - Whether database paths exist on disk
    These are checked at runtime when you run 'bactowise run'.

    \b
    Run this first whenever you edit pipeline.yaml to catch typos
    and config errors before starting a long annotation job.

    \b
    Examples:
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
