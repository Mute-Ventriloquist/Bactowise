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
from bactowise.utils.console import console
from bactowise.utils.db_manager import (
    DEFAULT_DB_ROOT,
    _DEFAULT_PGAP_DATA_DIR,
    download_bakta,
    download_checkm,
    download_pgap,
    is_bakta_present,
    is_checkm_present,
    is_pgap_present,
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
    pgap:   bool = typer.Option(False, "--pgap",   help="PGAP only (~30 GB)."),
    force:  bool = typer.Option(
        False, "--force-db-download",
        help="Re-download even if already present.",
    ),
):
    """Download all required databases, one-time (~32 GB total).

    \b
    Stores all databases under ~/.bactowise/databases/:
      checkm/      — CheckM marker gene database (~2 GB)
      bakta/       — Bakta annotation database, light build (~2 GB)
      pgap/        — PGAP supplemental data (~30 GB)

    \b
    Use individual flags to download only specific databases:
      bactowise db download --checkm
      bactowise db download --bakta
      bactowise db download --pgap

    \b
    Examples:
      bactowise db download
      bactowise db download --pgap --force-db-download
      bactowise db download --checkm --force-db-download
    """
    any_specified = checkm or bakta or pgap
    download_checkm_flag = checkm or not any_specified
    download_bakta_flag  = bakta  or not any_specified
    download_pgap_flag   = pgap   or not any_specified

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

    if download_pgap_flag:
        try:
            download_pgap(force=force)
        except RuntimeError as e:
            typer.echo(f"\n✗ PGAP: {e}", err=True)
            errors.append("pgap")

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
    pgap_ok   = is_pgap_present()

    typer.echo(f"  {'✓' if checkm_ok else '✗'}  CheckM  → {DEFAULT_DB_ROOT / 'checkm'}")
    typer.echo(f"  {'✓' if bakta_ok  else '✗'}  Bakta   → {DEFAULT_DB_ROOT / 'bakta' / 'db-light'}")
    typer.echo(f"  {'✓' if pgap_ok   else '✗'}  PGAP    → {_DEFAULT_PGAP_DATA_DIR}")

    if not checkm_ok or not bakta_ok or not pgap_ok:
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
    organism: str = typer.Option(
        ..., "-n", "--organism",
        help=(
            "Organism name as a valid NCBI Taxonomy string "
            "(e.g. 'Mycoplasmoides genitalium', 'Escherichia coli'). "
            "Required by PGAP. Also improves labelling in Prokka and Bakta."
        ),
    ),
    output_dir: Path = typer.Option(
        None, "-o", "--output",
        help=(
            "Output directory for all results. "
            "Defaults to ./results in the current working directory. "
            "Created automatically if it does not exist."
        ),
    ),
    skip: list[str] = typer.Option(
        [], "--skip",
        help=(
            "Skip a pipeline stage. Repeatable. "
            "Skippable stages: stage_1 (QC), stage_4 (supplementary). "
            "Stages 2 and 3 cannot be skipped."
        ),
    ),
    gff: list[str] = typer.Option(
        [], "--gff",
        help=(
            "Provide a pre-computed GFF file for an annotation tool. "
            "Format: 'tool:path'  (e.g. --gff bakta:/results/bakta.gff3). "
            "Repeatable. Any subset of annotation tools may be bypassed."
        ),
    ),
):
    """Run QC and annotation on a genome.

    \b
    Loads the pipeline config from ~/.bactowise/config/pipeline.yaml.
    Run 'bactowise init' first if you haven't already.

    \b
    Runs tools in dependency order. Within each stage, tools run in parallel:
      Stage 1: checkm                    -- quality gate (skippable)
      Stage 2: prokka + bakta + pgap     -- annotation (cannot be skipped)
      Stage 3: consensus                 -- consensus engine (cannot be skipped)
      Stage 4: amrfinderplus + ...       -- supplementary annotations (skippable)

    \b
    The organism name (-n) must be a valid NCBI Taxonomy name. It is passed
    to PGAP (required), Prokka (--genus/--species), and Bakta (--genus/--species).
    Check validity at: https://www.ncbi.nlm.nih.gov/taxonomy

    \b
    On first run, any missing conda environments and container images are
    created automatically. Databases are downloaded if not already present.

    \b
    Skip stages with --skip. Skippable: stage_1 (QC), stage_4 (supplementary).
      bactowise run -f genome.fasta -n "Escherichia coli" --skip stage_1
      bactowise run -f genome.fasta -n "Escherichia coli" --skip stage_4
      bactowise run -f genome.fasta -n "Escherichia coli" --skip stage_1 --skip stage_4

    \b
    GFF bypass -- provide pre-computed annotation for any subset of tools.
    Tools without a GFF still run and compute their annotation normally:
      bactowise run -f genome.fasta -n "Escherichia coli" \\
        --gff bakta:/path/to/bakta.gff3 \\
        --gff prokka:/path/to/prokka.gff

    \b
    Examples:
      bactowise run -f genome.fasta -n "Mycoplasmoides genitalium"
      bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" -o /scratch/my_run
      bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_1
      bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_1 --gff pgap:/path/to/pgap.gff
    """
    # Ensure the config is installed; install it automatically on first run
    # so 'bactowise run' works without requiring an explicit 'bactowise init'
    try:
        config_path = ensure_config()
    except RuntimeError as e:
        console.print(f"\n[user_error]✗ {e}[/user_error]")
        raise typer.Exit(code=1)

    # Parse and validate --skip stage_N entries
    skip_stages: set[int] = set()
    for entry in skip:
        if not entry.startswith("stage_"):
            console.print(
                f"\n[user_error]✗ Invalid --skip value: '{entry}'[/user_error]\n"
                f"  Expected a stage identifier, e.g. [bold]--skip stage_1[/bold]"
            )
            raise typer.Exit(code=1)
        try:
            stage_num = int(entry.split("_", 1)[1])
        except (IndexError, ValueError):
            console.print(
                f"\n[user_error]✗ Invalid --skip value: '{entry}'[/user_error]\n"
                f"  Expected format: [bold]stage_<number>[/bold]  (e.g. stage_1)"
            )
            raise typer.Exit(code=1)
        skip_stages.add(stage_num)

    # Parse --gff tool:path entries
    gff_files: dict[str, Path] = {}
    for entry in gff:
        if ":" not in entry:
            console.print(
                f"\n[user_error]✗ Invalid --gff format: '{entry}'[/user_error]\n"
                f"  Expected: [bold]tool:path[/bold]  (e.g. --gff bakta:/results/bakta.gff3)"
            )
            raise typer.Exit(code=1)
        tool_name, _, raw_path = entry.partition(":")
        gff_files[tool_name.strip()] = Path(raw_path.strip())

    console.print()
    console.print("[bold]BactoWise[/bold]")
    console.print(f"  [label]Genome[/label]   : [muted]{fasta}[/muted]")
    console.print(f"  [label]Organism[/label] : [bold]{organism}[/bold]")
    console.print(f"  [label]Config[/label]   : [muted]{config_path}[/muted]")
    if output_dir:
        console.print(f"  [label]Output[/label]   : [muted]{output_dir.resolve()}[/muted]")
    if skip_stages:
        console.print(f"  [label]Skip[/label]     : [warning]{', '.join(f'stage_{s}' for s in sorted(skip_stages))}[/warning]")
    if gff_files:
        console.print(f"  [label]GFF[/label]      : [bypass]{', '.join(f'{t}:{p}' for t, p in gff_files.items())}[/bypass]")
    console.print()

    try:
        pipeline_config = load_config(config_path)

        # Override output_dir if the user supplied -o / --output.
        # model_copy(update=...) returns a new validated instance — the original
        # config object and the pipeline.yaml file are never modified.
        if output_dir is not None:
            pipeline_config = pipeline_config.model_copy(
                update={"output_dir": output_dir.resolve()}
            )

        pipeline = Pipeline(
            pipeline_config,
            skip_stages=skip_stages,
            gff_files=gff_files or None,
            organism=organism,
        )
        pipeline.run(fasta)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"\n[user_error]✗ {e}[/user_error]")
        raise typer.Exit(code=1)
    except RuntimeError as e:
        console.print(f"\n[user_error]✗ {e}[/user_error]")
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
        console.print(
            f"\n[user_error]✗ No config found at: {config_path}[/user_error]\n"
            f"  Run [bold]bactowise init[/bold] to install it."
        )
        raise typer.Exit(code=1)

    try:
        cfg = load_config(config_path)
        console.print(f"\n[success]✓ Config valid — {len(cfg.tools)} tool(s):[/success]\n")
        for tool in cfg.tools:
            role_tag = f" [{tool.role}]" if tool.role == "qc" else ""
            console.print(f"  [bold]{tool.name}[/bold]{role_tag}")
            console.print(f"    [label]version[/label]    : [muted]{tool.version}[/muted]")
            console.print(f"    [label]runtime[/label]    : [muted]{tool.runtime}[/muted]")
            if tool.depends_on:
                console.print(f"    [label]depends_on[/label] : [muted]{', '.join(tool.depends_on)}[/muted]")
            if tool.runtime in ("docker", "singularity"):
                console.print(f"    [label]image[/label]      : [muted]{tool.image}[/muted]")
            if tool.conda_env:
                console.print(f"    [label]conda env[/label]  : [muted]{tool.conda_env.name}[/muted]")
                if tool.conda_env.dependencies:
                    console.print(f"    [label]deps[/label]       : [muted]{', '.join(tool.conda_env.dependencies)}[/muted]")
            if tool.database:
                console.print(f"    [label]database[/label]   : [muted]{tool.database.path}[/muted]")
            if tool.qc_criteria:
                console.print(
                    f"    [label]qc pass[/label]    : completeness > [bold]{tool.qc_criteria.completeness}%[/bold], "
                    f"contamination < [bold]{tool.qc_criteria.contamination}%[/bold]"
                )
            console.print()
        console.print(f"  [label]config[/label]     : [muted]{config_path}[/muted]")
        console.print(f"  [label]output_dir[/label] : [muted]{cfg.output_dir}[/muted]")
        console.print(f"  [label]threads[/label]    : [bold]{cfg.threads}[/bold]\n")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"\n[user_error]✗ {e}[/user_error]")
        raise typer.Exit(code=1)


def main():
    app()
