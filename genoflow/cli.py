from __future__ import annotations

from pathlib import Path

import typer

from genoflow.pipeline import Pipeline
from genoflow.utils.config_loader import load_config

app = typer.Typer(
    name="genoflow",
    help="""
\b
Genoflow — Genome Annotation Pipeline

Annotate bacterial genomes using multiple tools (Prokka, Bakta, PGAP)
running simultaneously. Tools are configured via a YAML config file.

\b
QUICK START
-----------
Step 1 — Validate your config file:
    genoflow validate -c pipeline.yaml

Step 2 — Run the pipeline on a genome:
    genoflow run -f genome.fasta -c pipeline.yaml

\b
FIRST TIME SETUP
----------------
Before running, make sure you have:

  1. Docker running (for Docker-based tools like Bakta):
       Linux:   sudo systemctl start docker
       Mac/Win: Open Docker Desktop

  2. Bakta database downloaded (~2 GB, one-time):
       bakta_db download --output ~/bakta_db --type light

  3. A genome file in .fasta or .fna format.
     Download the M. genitalium test genome:
       efetch -db nucleotide -id NC_000908.2 -format fasta > mgenitalium.fasta

\b
CONDA TOOLS (e.g. Prokka)
-------------------------
Tools with a 'conda_env' block in pipeline.yaml will have their
conda environment created automatically on first run. No manual
setup needed.

\b
OUTPUT
------
Results are written to separate subfolders under output_dir:
    results/
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
            "to run, their versions, and parameters. "
            "Example: -c pipeline.yaml"
        ),
        exists=True,
        readable=True,
    ),
):
    """
    Run the annotation pipeline on a genome.

    \b
    Runs all tools defined in the config file simultaneously on the
    provided genome. Each tool writes output to its own subfolder
    under the output_dir specified in the config.

    \b
    On first run, genoflow will automatically:
      - Create any missing conda environments (e.g. prokka_env)
      - Pull any missing Docker images (e.g. oschwengers/bakta)

    \b
    Examples:
      genoflow run -f mgenitalium.fasta -c pipeline.yaml
      genoflow run -f /data/genome.fna -c /configs/my_pipeline.yaml
    """
    typer.echo(f"\nGenoflow — Genome Annotation Pipeline")
    typer.echo(f"  Genome : {fasta}")
    typer.echo(f"  Config : {config}")
    typer.echo(f"  Tip    : Run 'genoflow validate -c {config}' first to check your config.\n")

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
    fields are present, runtimes are valid, and tool configs are well-formed.

    \b
    Does NOT check:
      - Whether Docker is running
      - Whether conda environments exist
      - Whether database paths exist on disk
    These are checked at runtime when you run 'genoflow run'.

    \b
    Run this first whenever you edit pipeline.yaml to catch typos
    and config errors before starting a long annotation job.

    \b
    Examples:
      genoflow validate -c pipeline.yaml
    """
    try:
        cfg = load_config(config)
        typer.echo(f"\n✓ Config is valid. Found {len(cfg.tools)} tool(s):\n")
        for tool in cfg.tools:
            typer.echo(f"  {tool.name}")
            typer.echo(f"    version  : {tool.version}")
            typer.echo(f"    runtime  : {tool.runtime}")
            if tool.runtime == "docker":
                typer.echo(f"    image    : {tool.image}")
            if tool.conda_env:
                typer.echo(f"    conda env: {tool.conda_env.name}")
                if tool.conda_env.dependencies:
                    typer.echo(f"    deps     : {', '.join(tool.conda_env.dependencies)}")
            if tool.database:
                typer.echo(f"    database : {tool.database.path}")
            typer.echo()
        typer.echo(f"  output_dir : {cfg.output_dir}")
        typer.echo(f"  threads    : {cfg.threads}")
        typer.echo(f"\nRun the pipeline with:")
        typer.echo(f"  genoflow run -f <genome.fasta> -c {config}\n")
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"\n✗ Config invalid: {e}", err=True)
        raise typer.Exit(code=1)


def main():
    app()
