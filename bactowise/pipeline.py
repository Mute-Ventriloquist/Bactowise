from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import shutil

from bactowise.models.config import PipelineConfig
from bactowise.runners.base import BaseRunner
from bactowise.runners.factory import RunnerFactory
from bactowise.utils.console import console, stage_rule
from bactowise.utils.db_manager import (
    download_all,
    download_pgap,
    download_spifinder,
    is_checkm_present,
    is_bakta_present,
    is_pgap_present,
    is_spifinder_present,
)


class Pipeline:
    """
    Orchestrates all tools defined in the config with dependency-aware execution.

    Execution model:
      - Tools are grouped into stages based on their depends_on declarations.
      - Stage 1: tools with no dependencies (QC tools, e.g. CheckM) -- run first.
      - Stage 2+: tools whose dependencies have all completed -- run next.
      - Within each stage, tools run simultaneously via a thread pool.
      - If a dependency tool has role=qc and its results failed QC criteria,
        downstream tools are warned before running.

    Skipping stages:
      - Pass a set of stage numbers to skip via the `skip_stages` parameter.
      - Only stage 1 (QC) may be skipped. Stage 2 and beyond contain the core
        annotation tools and cannot be skipped.
      - Skipped stages are excluded from preflight AND execution.
      - Skipped stages are treated as satisfied in the dependency graph so
        annotation tools still run (with a warning that the QC gate was skipped).
      - Example: skip_stages={1} means prokka, bakta, pgap run without a QC gate.

    GFF bypass:
      - Pass pre-computed GFF files via gff_files for any subset of annotation
        tools. The provided files are copied to the standard output directory;
        tools without a GFF file run normally.
      - No runner, preflight check, or database download is performed for a
        bypassed tool.
      - Any number of annotation tools may be bypassed (1, 2, or all of them).
      - QC tools cannot be bypassed via --gff.

    Stage numbering (user-facing):
        Stage 1: checkm                    -- QC gate (skippable)
        Stage 2: prokka + bakta + pgap     -- annotation (cannot be skipped)
    """

    # Stages the user is permitted to skip.
    # Stages 2 (annotation) and 3 (consensus) are core and never skippable.
    # Stage 1 (QC) and stage 4+ (supplementary) are optional and skippable.
    SKIPPABLE_STAGES: frozenset = frozenset({1, 4})

    def __init__(
        self,
        config: PipelineConfig,
        skip_stages: set[int] | None = None,
        gff_files: dict[str, Path] | None = None,
        organism: str = "",
    ):
        self.config = config
        self.organism = organism.strip()

        skip_stages = set(skip_stages or [])
        invalid_stages = skip_stages - self.SKIPPABLE_STAGES
        if invalid_stages:
            unskippable_tools = {
                t.name for t in config.tools
                if t.depends_on and t.name not in
                {u.name for u in config.tools if not u.depends_on}
            }
            raise ValueError(
                f"Stage(s) {sorted(invalid_stages)} cannot be skipped.\n"
                f"Skippable stages: 1 (QC) and 4 (supplementary).\n"
                f"Stages 2 (annotation) and 3 (consensus) are core and cannot be skipped."
            )
        self.skip_stages: frozenset = frozenset(skip_stages)
        self.skip: set[str] = self._resolve_skip_stages(skip_stages)

        self.gff_files: dict[str, Path] = {}
        if gff_files:
            self._validate_gff_files(gff_files)
            self.gff_files = {k: v.resolve() for k, v in gff_files.items()}

        bypassed = set(self.gff_files.keys())
        self.runners: dict[str, BaseRunner] = {
            tool.name: RunnerFactory.create(tool, config.output_dir, self.organism, config.threads)
            for tool in config.tools
            if tool.name not in self.skip and tool.name not in bypassed
        }

    def _resolve_skip_stages(self, skip_stages: set[int]) -> set[str]:
        """
        Convert a set of stage numbers into the set of tool names to skip.

        Stage 1 = all tools with no depends_on (QC tools).
        Stage 4 = all tools that depend only on stage 3 tools (supplementary).
        This is deterministic from the config alone.
        """
        if not skip_stages:
            return set()

        # Build the full stage map to resolve which tools belong to which stage
        tool_configs = {t.name: t for t in self.config.tools}
        completed: set[str] = set()
        remaining = list(tool_configs.keys())
        stage_assignment: dict[str, int] = {}
        stage_num = 1

        while remaining:
            ready = [
                name for name in remaining
                if all(dep in completed for dep in tool_configs[name].depends_on)
            ]
            if not ready:
                break
            for name in ready:
                stage_assignment[name] = stage_num
            completed.update(ready)
            remaining = [n for n in remaining if n not in ready]
            stage_num += 1

        return {
            name for name, stage in stage_assignment.items()
            if stage in skip_stages
        }

    def preflight(self) -> None:
        console.print()
        console.rule("[bold white]  BactoWise — Preflight Checks  [/bold white]", style="bright_blue")
        console.print()

        if self.skip:
            console.print(f"  [skip]⊘  Skipping stage 1 (QC): {', '.join(sorted(self.skip))}[/skip]")

        if self.gff_files:
            console.print(f"  [bypass]↩  GFF bypass active for: {', '.join(sorted(self.gff_files))}[/bypass]")

        if self.skip or self.gff_files:
            console.print()

        self._ensure_databases()

        errors = []
        for runner in self.runners.values():
            try:
                runner.preflight()
            except RuntimeError as e:
                errors.append(str(e))

        if errors:
            console.print()
            console.print("[error]✗ Preflight failed. Fix the following issues:[/error]")
            console.print()
            for err in errors:
                console.print(f"  [error]{err}[/error]")
                console.print()
            raise SystemExit(1)

        console.print()
        console.print("[success]✓ All preflight checks passed. Starting pipeline...[/success]")
        console.print()

    def _print_resource_warning(self) -> None:
        """
        Print a storage and compute requirements warning before anything runs,
        and pause for 5 seconds so the user can cancel if needed (Ctrl+C).

        Only shown when databases have not all been downloaded yet — experienced
        users with everything in place see a brief confirmation instead.
        """
        import time
        from bactowise.utils.db_manager import (
            is_checkm_present, is_bakta_present, is_pgap_present,
            is_phigaro_present, is_platon_present, is_eggnog_present,
        )

        tool_names = {t.name for t in self.config.tools} - self.skip
        needs_checkm = "checkm"       in tool_names
        needs_bakta  = "bakta"        in tool_names
        needs_pgap   = "pgap"         in tool_names
        needs_phigaro = "phigaro"     in tool_names
        needs_platon  = "platon"      in tool_names
        needs_eggnog  = "eggnogmapper" in tool_names

        missing = []
        if needs_checkm  and not is_checkm_present():  missing.append("CheckM (~1.4 GB)")
        if needs_bakta   and not is_bakta_present():   missing.append("Bakta (~4 GB)")
        if needs_pgap    and not is_pgap_present():    missing.append("PGAP (~38 GB)")
        if needs_phigaro and not is_phigaro_present(): missing.append("Phigaro pVOG profiles (~1.6 GB)")
        if needs_platon  and not is_platon_present():  missing.append("Platon (~2.8 GB)")
        if needs_eggnog  and not is_eggnog_present():  missing.append("EggNOG (~48 GB)")

        console.rule("[bold white]  BactoWise — Resource Requirements  [/bold white]", style="yellow")
        console.print()

        if missing:
            console.print(
                "  [warning]⚠  One-time database downloads required[/warning]\n"
                f"     The following databases will be downloaded on this run:"
            )
            for db in missing:
                console.print(f"       • {db}")
            console.print()

        console.print(
            "  [label]Disk space:[/label]  ~160 GB total required\n"
            "    [muted]• ~96 GB for all databases (CheckM 1.4 GB · Bakta 4 GB · PGAP 38 GB ·[/muted]\n"
            "    [muted]  Phigaro 1.6 GB · Platon 2.8 GB · EggNOG 48 GB)[/muted]\n"
            "    [muted]• ~60 GB additional working space during a PGAP run[/muted]\n"
            "    [muted]  (NCBI quotes ~100 GB total for PGAP data + working space combined)[/muted]\n"
            "    [muted]• Ensure your filesystem has sufficient free space before continuing.[/muted]"
        )
        console.print()
        console.print(
            "  [label]Compute:[/label]    Multi-core CPU recommended\n"
            "    [muted]• Stage 2 tools (Prokka, Bakta, PGAP) run in parallel — expect 30–90 min[/muted]\n"
            "    [muted]  on a 4-core machine for a typical bacterial genome.[/muted]\n"
            "    [muted]• PGAP is the most resource-intensive step and may take 1–3 hours[/muted]\n"
            "    [muted]  depending on genome size and available CPUs.[/muted]\n"
            "    [muted]• Stage 4 tools run in parallel — EggNOG-mapper may take 10–30 min[/muted]\n"
            "    [muted]  depending on genome size and the number of consensus genes.[/muted]"
        )
        console.print()
        console.print(
            "  [muted]Press Ctrl+C within 5 seconds to cancel.[/muted]"
        )
        console.print()

        try:
            for remaining in range(5, 0, -1):
                console.print(
                    f"\r  [muted]Starting in {remaining}s...[/muted]",
                    end="", soft_wrap=True,
                )
                time.sleep(1)
            console.print()
            console.print()
        except KeyboardInterrupt:
            console.print()
            console.print("\n  [warning]Run cancelled by user.[/warning]\n")
            raise SystemExit(0)

    def run(self, fasta: Path) -> dict[str, Path]:
        fasta = fasta.resolve()
        if not fasta.exists():
            raise FileNotFoundError(f"Input fasta not found: {fasta}")

        self._print_resource_warning()
        self.preflight()

        stages = self._build_stages()
        total = sum(len(s) for s in stages)

        console.rule("[bold white]  Pipeline  [/bold white]", style="bright_blue")
        console.print()

        if self.skip_stages:
            stage_labels = ", ".join(f"stage_{s}" for s in sorted(self.skip_stages))
            console.print(f"  [skip]⊘  Skipping: {stage_labels} ({', '.join(sorted(self.skip))})[/skip]")

        if self.gff_files:
            console.print(f"  [bypass]↩  GFF bypass for: {', '.join(sorted(self.gff_files))}[/bypass]")

        console.print(f"  Running [bold]{total}[/bold] tool(s) in [bold]{len(stages)}[/bold] stage(s)")
        console.print(f"  Input:  [muted]{fasta}[/muted]")
        console.print(f"  Output: [muted]{self.config.output_dir}[/muted]")
        console.print()

        results: dict[str, Path] = {}
        errors:  dict[str, str]  = {}

        # Build the true stage numbers by taking the full sequence (1..N+skipped)
        # and removing the skipped ones. This works correctly regardless of which
        # stages are skipped or how many there are.
        total_stages = len(stages) + len(self.skip_stages)
        running_stage_nums = [n for n in range(1, total_stages + 1) if n not in self.skip_stages]

        for stage_num, stage_tools in zip(running_stage_nums, stages):
            stage_rule(stage_num, stage_tools)

            bypass_tools = [name for name in stage_tools if name in self.gff_files]
            run_tools    = [name for name in stage_tools if name not in self.gff_files]

            if bypass_tools:
                self._apply_gff_bypass(bypass_tools, results)

            if not run_tools:
                continue

            self._warn_skipped_qc(run_tools)
            self._warn_qc(run_tools, results)

            runners_in_stage = [self.runners[name] for name in run_tools]

            with ThreadPoolExecutor(max_workers=len(runners_in_stage)) as executor:
                future_to_name = {
                    executor.submit(runner.run, fasta): runner.config.name
                    for runner in runners_in_stage
                }
                for future in as_completed(future_to_name):
                    tool_name = future_to_name[future]
                    try:
                        results[tool_name] = future.result()
                    except Exception as e:
                        errors[tool_name] = str(e)
                        console.print(f"\n[error]✗ [{tool_name}] Failed: {e}[/error]")

        # Build a map of tool_name → stage_number for the summary label.
        # We need the full stage ordering including skipped tools, so we
        # re-run the topological sort without the skip filter.
        tool_configs  = {t.name: t for t in self.config.tools}
        all_tools     = list(tool_configs.keys())
        completed_all: set[str] = set()
        remaining_all = list(all_tools)
        stage_num_map: dict[str, int] = {}
        stage_counter = 1
        while remaining_all:
            ready = [n for n in remaining_all
                     if all(d in completed_all for d in tool_configs[n].depends_on)]
            for n in ready:
                stage_num_map[n] = stage_counter
            completed_all.update(ready)
            remaining_all = [n for n in remaining_all if n not in ready]
            if ready:
                stage_counter += 1

        # Summary
        console.print()
        console.rule("[bold white]  Pipeline Summary  [/bold white]", style="bright_blue")
        console.print()

        for tool_name in sorted(self.skip):
            stage_label = stage_num_map.get(tool_name, "?")
            console.print(f"  [skip]⊘  {tool_name:15s} → skipped (stage {stage_label})[/skip]")

        for tool_name in sorted(self.gff_files):
            console.print(f"  [bypass]↩  {tool_name:15s} → GFF provided[/bypass]")

        for tool_name, output_path in results.items():
            if tool_name not in self.gff_files:
                console.print(f"  [success]✓  {tool_name:15s}[/success] → [muted]{output_path}[/muted]")

        for tool_name, error in errors.items():
            console.print(f"  [error]✗  {tool_name:15s} → FAILED: {error}[/error]")

        console.print()

        if errors:
            raise RuntimeError(
                f"{len(errors)} tool(s) failed: {', '.join(errors.keys())}"
            )

        return results

    def _annotation_tools(self) -> set[str]:
        """
        Return the names of all annotation tools -- i.e. tools that have at
        least one dependency and are not being skipped.
        """
        return {
            t.name for t in self.config.tools
            if t.depends_on and t.name not in self.skip
        }

    def _validate_gff_files(self, gff_files: dict[str, Path]) -> None:
        """
        Validate --gff entries:

        1. No tool may appear in both --gff and --skip (contradictory).
        2. Every tool name in --gff must be a valid annotation tool in the
           active config (catches typos before anything runs).
        3. Every provided GFF path must exist on disk.
        """
        annotation_tools = self._annotation_tools()
        provided         = set(gff_files.keys())

        conflict = provided & self.skip
        if conflict:
            raise ValueError(
                f"Tool(s) appear in both --gff and --skip: "
                f"{', '.join(sorted(conflict))}.\n"
                f"Use --skip stage_1 to skip QC entirely, or --gff to provide "
                f"pre-computed annotation output -- not both."
            )

        unknown = provided - annotation_tools
        if unknown:
            raise ValueError(
                f"--gff provided for unknown or non-annotation tool(s): "
                f"{', '.join(sorted(unknown))}.\n"
                f"Annotation tools in this config: "
                f"{', '.join(sorted(annotation_tools))}"
            )

        for tool_name, path in gff_files.items():
            if not path.exists():
                raise FileNotFoundError(
                    f"GFF file for '{tool_name}' not found: {path}"
                )

    def _apply_gff_bypass(
        self, stage_tools: list[str], results: dict[str, Path]
    ) -> None:
        """
        Copy each provided GFF file into the tool's standard output directory
        so downstream steps always find outputs in the same place.
        """
        for tool_name in stage_tools:
            src             = self.gff_files[tool_name]
            tool_output_dir = self.config.output_dir / tool_name
            tool_output_dir.mkdir(parents=True, exist_ok=True)

            dst = tool_output_dir / f"provided_{src.name}"
            shutil.copy2(src, dst)

            results[tool_name] = tool_output_dir
            console.print(f"  [bypass]↩  [{tool_name}] Using provided GFF: {src}[/bypass]")
            console.print(f"              Copied to: [muted]{dst}[/muted]")

    def _ensure_databases(self) -> None:
        """
        Check whether required databases are present and download any that are missing.
        Only downloads databases needed by the active (non-skipped) tools in this run.
        SPIFinder is only needed when the organism is Salmonella.
        """
        tool_names = {t.name for t in self.config.tools} - self.skip - set(self.gff_files)

        needs_checkm    = "checkm"    in tool_names
        needs_bakta     = "bakta"     in tool_names
        needs_pgap      = "pgap"      in tool_names
        # SPIFinder git install is only needed for Salmonella runs
        needs_spifinder = (
            "spifinder" in tool_names
            and self.organism.strip().lower().split()[0] == "salmonella"
            if self.organism else False
        )

        missing_checkm    = needs_checkm    and not is_checkm_present()
        missing_bakta     = needs_bakta     and not is_bakta_present()
        missing_pgap      = needs_pgap      and not is_pgap_present()
        missing_spifinder = needs_spifinder and not is_spifinder_present()

        if not any([missing_checkm, missing_bakta, missing_pgap, missing_spifinder]):
            return

        console.print()
        console.print("  [warning]Some required databases are missing — downloading now.[/warning]")
        console.print("  You can also run: [bold]bactowise db download[/bold] to manage databases manually.")
        console.print()

        try:
            download_all(
                force=False,
                checkm=missing_checkm,
                bakta=missing_bakta,
                pgap=missing_pgap,
            )
            if missing_spifinder:
                download_spifinder(force=False)
        except RuntimeError as e:
            raise RuntimeError(
                f"Database download failed: {e}\n"
                f"You can retry manually with: bactowise db download"
            ) from e

    def _build_stages(self) -> list[list[str]]:
        """
        Topological sort of tools into execution stages, respecting skips.
        """
        tool_configs = {t.name: t for t in self.config.tools}

        completed: set[str] = set(self.skip)
        remaining = [name for name in tool_configs if name not in self.skip]
        stages = []

        while remaining:
            ready = [
                name for name in remaining
                if all(dep in completed for dep in tool_configs[name].depends_on)
            ]

            if not ready:
                raise RuntimeError(
                    f"Circular dependency detected among: {remaining}"
                )

            stages.append(ready)
            completed.update(ready)
            remaining = [n for n in remaining if n not in ready]

        return stages

    def _warn_skipped_qc(self, stage_tools: list[str]) -> None:
        """
        Warn if any dependency of the current stage was a QC tool that was
        skipped via --skip stage_1.
        """
        tool_configs = {t.name: t for t in self.config.tools}

        warned: set[str] = set()
        for tool_name in stage_tools:
            for dep_name in tool_configs[tool_name].depends_on:
                if dep_name not in self.skip or dep_name in warned:
                    continue
                dep_config = tool_configs.get(dep_name)
                if dep_config and dep_config.role == "qc":
                    console.print(
                        f"\n  [warning]⚠  Warning:[/warning] QC tool [bold]'{dep_name}'[/bold] "
                        f"was skipped (--skip stage_1).\n"
                        f"     [bold]{tool_name}[/bold] is running without a genome quality gate.\n"
                        f"     Results should be interpreted with caution."
                    )
                    console.print()
                    warned.add(dep_name)

    def _warn_qc(self, stage_tools: list[str], completed_results: dict) -> None:
        """
        Warn if any QC dependency failed its thresholds.
        """
        tool_configs = {t.name: t for t in self.config.tools}

        for tool_name in stage_tools:
            for dep_name in tool_configs[tool_name].depends_on:
                dep_runner = self.runners.get(dep_name)
                dep_config = tool_configs.get(dep_name)

                if not dep_config or dep_config.role != "qc":
                    continue

                if hasattr(dep_runner, "qc_result") and dep_runner.qc_result:
                    qc       = dep_runner.qc_result
                    criteria = dep_config.qc_criteria
                    if criteria:
                        failed = (
                            qc["completeness"] < criteria.completeness or
                            qc["contamination"] > criteria.contamination
                        )
                        if failed:
                            console.print(
                                f"\n  [warning]⚠  Note:[/warning] [bold]{tool_name}[/bold] is running "
                                f"on a genome that did not pass QC criteria for "
                                f"[bold]{dep_name}[/bold].\n"
                                f"     Completeness:  [bold]{qc['completeness']:.1f}%[/bold] "
                                f"(threshold: {criteria.completeness:.1f}%)\n"
                                f"     Contamination: [bold]{qc['contamination']:.1f}%[/bold] "
                                f"(threshold: {criteria.contamination:.1f}%)"
                            )
                            console.print()
