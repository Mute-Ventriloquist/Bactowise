from __future__ import annotations

from pathlib import Path

import typer

from bactowise.pipeline import Pipeline
from bactowise.utils.config_loader import load_config
from bactowise.utils.config_manager import (
    active_config_path,
    bundled_config_path,
    ensure_config,
    install_config,
)
from bactowise.utils.db_manager import (
    DEFAULT_DB_ROOT,
    download_bakta,
    download_checkm,
    is_bakta_present,
    is_checkm_present,
)

app = typer.Typer(
    name="bactowise",
    help="Bacterial genome QC and annotation — one command.",
    add_completion=False,
)

# ── db sub-command group ──────────────────────────────────────────────────────

db_app = typer.Typer(
    name="db",
    help="Manage databases.",
    add_completion=False,
)
app.add_typer(db_app, name="db")


@db_app.command("download")
def db_download(
    checkm: bool = typer.Option(False, "--checkm", help="CheckM only."),
    bakta:  bool = typer.Option(False, "--bakta",  help="Bakta only."),
    force:  bool = typer.Option(
        False, "--force-db-download",
        help="Re-download even if already present.",
    ),
):
    """Download required databases (~4 GB, one-time).

    \b
    Stores databases under ~/.bactowise/databases/. By default downloads both:
      checkm/      — CheckM marker gene database (~2 GB)
      bakta/       — Bakta annotation database, light build (~2 GB)

    \b
    Skips any database that is already complete. Use --force-db-download
    to wipe and re-download. Interrupted downloads are detected automatically
    and resumed on the next run.

    \b
    Examples:
      bactowise db download
      bactowise db download --checkm --force-db-download
    """
    download_checkm_flag = checkm or (not checkm and not bakta)
    download_bakta_flag  = bakta  or (not checkm and not bakta)

    typer.echo(f"\nBactoWise — Database Download")
    typer.echo(f"  Storage : {DEFAULT_DB_ROOT}")
    typer.echo(f"  Mode    : {'force re-download' if force else 'skip if already present'}\n")

    errors = []

    if download_checkm_flag:
        try:
            download_checkm(force=force)
        except RuntimeError as e:
            typer.echo(f"\n✗ CheckM: {e}", err=True)
            errors.append("checkm")

    if download_bakta_flag:
        try:
            download_bakta(force=force)
        except RuntimeError as e:
            typer.echo(f"\n✗ Bakta: {e}", err=True)
            errors.append("bakta")

    if errors:
        typer.echo(f"\n✗ Failed: {', '.join(errors)}\n", err=True)
        raise typer.Exit(code=1)

    typer.echo("\n✓ Databases ready.\n")


@db_app.command("status")
def db_status():
    """Show database status at the default install location only.

    \b
    This command only checks ~/.bactowise/databases/. It does not read
    the pipeline config. If you have set custom database paths in the
    installed config, check those paths manually — the pipeline will
    report a missing database at runtime if a configured path is missing.
    """
    typer.echo(f"\nBactoWise — Database Status")
    typer.echo(f"  Note: showing status for default location only ({DEFAULT_DB_ROOT}).")
    typer.echo()

    checkm_ok = is_checkm_present()
    bakta_ok  = is_bakta_present()

    typer.echo(f"  {'✓' if checkm_ok else '✗'}  CheckM  → {DEFAULT_DB_ROOT / 'checkm'}")
    typer.echo(f"  {'✓' if bakta_ok  else '✗'}  Bakta   → {DEFAULT_DB_ROOT / 'bakta' / 'db-light'}")

    if not checkm_ok or not bakta_ok:
        typer.echo(f"\n  Run 'bactowise db download' to fetch missing databases.\n")
    else:
        typer.echo(f"\n  All databases present.\n")


# ── init command ──────────────────────────────────────────────────────────────

@app.command()
def init(
    reset: bool = typer.Option(
        False, "--reset",
        help=(
            "Overwrite the installed config with the version bundled in this "
            "release of BactoWise. Use this after upgrading to apply config "
            "changes from the new version."
        ),
    ),
):
    """Install the pipeline config to ~/.bactowise/config/pipeline.yaml.

    \b
    Run once after installing BactoWise. The config is copied from the
    bundled version shipped with this release and will not be changed by
    future upgrades unless you run 'bactowise init --reset'.

    \b
    Examples:
      bactowise init              # install config (fails if already present)
      bactowise init --reset      # overwrite with the bundled version
    """
    config_path = active_config_path()
    bundled     = bundled_config_path()

    try:
        install_config(reset=reset)
        if reset:
            typer.echo(f"\n✓ Config reset to bundled version.")
        else:
            typer.echo(f"\n✓ Config installed.")
        typer.echo(f"  Location : {config_path}")
        typer.echo(f"  Source   : {bundled}\n")
    except FileExistsError as e:
        typer.echo(f"\n✗ {e}", err=True)
        raise typer.Exit(code=1)
    except RuntimeError as e:
        typer.echo(f"\n✗ {e}", err=True)
        raise typer.Exit(code=1)


# ── run command ───────────────────────────────────────────────────────────────

@app.command()
def run(
    fasta: Path = typer.Option(
        ..., "-f", "--fasta",
        help="Input genome (.fasta / .fna).",
        exists=True,
        readable=True,
    ),
    skip: list[str] = typer.Option(
        [], "--skip",
        help=(
            "Skip a tool by name. Repeatable. "
            "Dependents still run; a warning is shown if a QC tool is skipped."
        ),
    ),
    gff: list[str] = typer.Option(
        [], "--gff",
        help=(
            "Provide a pre-computed GFF file for a tool, bypassing stage 2. "
            "Format: 'tool:path'  (e.g. --gff bakta:/results/bakta.gff3). "
            "Repeatable. Must supply for ALL annotation tools or NONE."
        ),
    ),
):
    """Run QC and annotation on a genome.

    \b
    Loads the pipeline config from ~/.bactowise/config/pipeline.yaml.
    Run 'bactowise init' first if you haven't already.

    \b
    Runs tools in dependency order. Within each stage, tools run in parallel:
      Stage 1: checkm           — quality gate
      Stage 2: prokka + bakta   — annotation (parallel)

    \b
    On first run, any missing conda environments and container images are
    created automatically. Databases are downloaded if not already present.

    \b
    GFF bypass — skip stage 2 by providing pre-computed annotation files.
    Must provide GFF for ALL annotation tools or NONE (no partial bypass):
      bactowise run -f genome.fasta \\
        --gff bakta:/path/to/bakta.gff3 \\
        --gff prokka:/path/to/prokka.gff

    \b
    Examples:
      bactowise run -f genome.fasta
      bactowise run -f genome.fasta --skip checkm
      bactowise run -f genome.fasta --gff bakta:/results/bakta.gff3 --gff prokka:/results/prokka.gff
    """
    # Ensure the config is installed; install it automatically on first run
    # so 'bactowise run' works without requiring an explicit 'bactowise init'
    try:
        config_path = ensure_config()
    except RuntimeError as e:
        typer.echo(f"\n✗ {e}", err=True)
        raise typer.Exit(code=1)

    # Parse --gff tool:path entries
    gff_files: dict[str, Path] = {}
    for entry in gff:
        if ":" not in entry:
            typer.echo(
                f"\n✗ Invalid --gff format: '{entry}'\n"
                f"  Expected: tool:path  (e.g. --gff bakta:/results/bakta.gff3)",
                err=True,
            )
            raise typer.Exit(code=1)
        tool_name, _, raw_path = entry.partition(":")
        gff_files[tool_name.strip()] = Path(raw_path.strip())

    typer.echo(f"\nBactoWise")
    typer.echo(f"  Genome : {fasta}")
    typer.echo(f"  Config : {config_path}")
    if skip:
        typer.echo(f"  Skip   : {', '.join(skip)}")
    if gff_files:
        typer.echo(f"  GFF    : {', '.join(f'{t}:{p}' for t, p in gff_files.items())}")
    typer.echo()

    try:
        pipeline_config = load_config(config_path)
        pipeline = Pipeline(pipeline_config, skip=set(skip), gff_files=gff_files or None)
        pipeline.run(fasta)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"\n✗ {e}", err=True)
        raise typer.Exit(code=1)
    except RuntimeError as e:
        typer.echo(f"\n✗ {e}", err=True)
        raise typer.Exit(code=1)


# ── validate command ──────────────────────────────────────────────────────────

@app.command()
def validate():
    """Validate the installed pipeline config without running anything.

    \b
    Loads ~/.bactowise/config/pipeline.yaml and checks that all required
    fields are present, runtimes are valid, and depends_on references exist.
    Does not check Docker/Singularity, conda environments, or database paths
    — those are verified at runtime.

    \b
    Run 'bactowise init' first if the config has not been installed yet.
    """
    config_path = active_config_path()

    if not config_path.exists():
        typer.echo(
            f"\n✗ No config found at: {config_path}\n"
            f"  Run 'bactowise init' to install it.\n",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        cfg = load_config(config_path)
        typer.echo(f"\n✓ Config valid — {len(cfg.tools)} tool(s):\n")
        for tool in cfg.tools:
            role_tag = f" [{tool.role}]" if tool.role == "qc" else ""
            typer.echo(f"  {tool.name}{role_tag}")
            typer.echo(f"    version    : {tool.version}")
            typer.echo(f"    runtime    : {tool.runtime}")
            if tool.depends_on:
                typer.echo(f"    depends_on : {', '.join(tool.depends_on)}")
            if tool.runtime in ("docker", "singularity"):
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
        typer.echo(f"  config     : {config_path}")
        typer.echo(f"  output_dir : {cfg.output_dir}")
        typer.echo(f"  threads    : {cfg.threads}\n")
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"\n✗ {e}", err=True)
        raise typer.Exit(code=1)


def main():
    app()
