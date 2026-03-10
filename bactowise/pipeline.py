from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bactowise.models.config import PipelineConfig
from bactowise.runners.base import BaseRunner
from bactowise.runners.factory import RunnerFactory


class Pipeline:
    """
    Orchestrates all tools defined in the config with dependency-aware execution.

    Execution model:
      - Tools are grouped into stages based on their depends_on declarations.
      - Stage 0: tools with no dependencies (e.g. CheckM) — run first.
      - Stage 1+: tools whose dependencies have all completed — run next.
      - Within each stage, tools run simultaneously via a thread pool.
      - If a dependency tool has role=qc and its results failed QC criteria,
        downstream tools are warned before running.

    Skipping tools:
      - Pass a set of tool names to skip via the `skip` parameter.
      - Skipped tools are excluded from preflight AND execution.
      - Skipped tools are treated as "satisfied" in the dependency graph so
        their dependents still run (with a warning if a QC tool was skipped).
      - Example: skip={"checkm"} → prokka and bakta still run, but without
        the QC gate. A warning is printed before each affected stage.

    Example (no skips):
        checkm           → stage 0 (no deps, runs first)
        prokka, bakta    → stage 1 (depend on checkm, run after checkm completes)

    Example (skip checkm):
        prokka, bakta    → stage 0 (checkm treated as satisfied, run immediately)
    """

    def __init__(self, config: PipelineConfig, skip: set[str] | None = None):
        self.config = config
        self.skip: set[str] = set(skip or [])

        # Validate skip names against the tool list so typos surface immediately
        known_tools = {t.name for t in config.tools}
        unknown = self.skip - known_tools
        if unknown:
            raise ValueError(
                f"Unknown tool(s) in --skip: {', '.join(sorted(unknown))}.\n"
                f"Available tools: {', '.join(sorted(known_tools))}"
            )

        # Only create runners for tools that are not being skipped.
        # This means skipped tools never connect to Docker / conda, so preflight
        # for those tools is also cleanly bypassed.
        self.runners: dict[str, BaseRunner] = {
            tool.name: RunnerFactory.create(tool, config.output_dir)
            for tool in config.tools
            if tool.name not in self.skip
        }

    def preflight(self) -> None:
        print("\n" + "="*50)
        print("  BactoWise — Preflight Checks")
        print("="*50)

        if self.skip:
            print(f"\n  Skipping preflight for: {', '.join(sorted(self.skip))}")

        errors = []
        for runner in self.runners.values():
            try:
                runner.preflight()
            except RuntimeError as e:
                errors.append(str(e))

        if errors:
            print("\n✗ Preflight failed. Fix the following issues:\n")
            for err in errors:
                print(f"  {err}\n")
            raise SystemExit(1)

        print("\n✓ All preflight checks passed. Starting pipeline...\n")

    def run(self, fasta: Path) -> dict[str, Path]:
        fasta = fasta.resolve()
        if not fasta.exists():
            raise FileNotFoundError(f"Input fasta not found: {fasta}")

        self.preflight()

        stages = self._build_stages()
        total = sum(len(s) for s in stages)

        print("="*50)
        if self.skip:
            print(f"  Skipping tool(s): {', '.join(sorted(self.skip))}")
        print(f"  Running {total} tool(s) in {len(stages)} stage(s)")
        print(f"  Input:  {fasta}")
        print(f"  Output: {self.config.output_dir}")
        print("="*50 + "\n")

        results: dict[str, Path] = {}
        errors:  dict[str, str]  = {}

        for stage_num, stage_tools in enumerate(stages, 1):
            print(f"\n── Stage {stage_num}: {', '.join(stage_tools)} {'─'*20}\n")

            # Warn if any skipped dependency of tools in this stage was a QC tool
            self._warn_skipped_qc(stage_tools)

            # Warn if any non-skipped QC dependency failed its thresholds
            self._warn_qc(stage_tools, results)

            runners_in_stage = [self.runners[name] for name in stage_tools]

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
                        print(f"\n✗ [{tool_name}] Failed: {e}")

        # Summary
        print("\n" + "="*50)
        print("  Pipeline Summary")
        print("="*50)
        for tool_name in sorted(self.skip):
            print(f"  ⊘  {tool_name:15s} → skipped")
        for tool_name, output_path in results.items():
            print(f"  ✓  {tool_name:15s} → {output_path}")
        for tool_name, error in errors.items():
            print(f"  ✗  {tool_name:15s} → FAILED: {error}")
        print()

        if errors:
            raise RuntimeError(
                f"{len(errors)} tool(s) failed: {', '.join(errors.keys())}"
            )

        return results

    def _build_stages(self) -> list[list[str]]:
        """
        Topological sort of tools into execution stages, respecting skips.

        Skipped tools are treated as already-completed at the start so their
        dependents are unblocked and still run. Only non-skipped tools appear
        in the returned stages list.

        Stage 0 = non-skipped tools with no unsatisfied dependencies.
        Stage N = non-skipped tools whose all dependencies are in stages 0..N-1
                  or have been skipped.
        """
        tool_configs = {t.name: t for t in self.config.tools}

        # Skipped tools are pre-populated into completed so dependents are
        # unblocked without the skipped tool appearing in any stage.
        completed: set[str] = set(self.skip)
        remaining = [
            name for name in tool_configs
            if name not in self.skip
        ]
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
        Before running a stage, warn if any of its dependencies were skipped
        AND those dependencies had role=qc. The user is running annotation
        without a quality gate — they should know.
        """
        tool_configs = {t.name: t for t in self.config.tools}

        warned: set[str] = set()
        for tool_name in stage_tools:
            for dep_name in tool_configs[tool_name].depends_on:
                if dep_name not in self.skip or dep_name in warned:
                    continue
                dep_config = tool_configs.get(dep_name)
                if dep_config and dep_config.role == "qc":
                    print(
                        f"  ⚠  Warning: QC tool '{dep_name}' was skipped.\n"
                        f"     '{tool_name}' is running without a genome quality gate.\n"
                        f"     Results should be interpreted with caution.\n"
                    )
                    warned.add(dep_name)

    def _warn_qc(self, stage_tools: list[str], completed_results: dict) -> None:
        """
        Before running a stage, check if any of its dependencies were QC tools
        whose results didn't meet criteria. Warn the user if so.
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
                            print(
                                f"  ⚠  Note: '{tool_name}' is running on a genome that "
                                f"did not pass QC criteria set for '{dep_name}'.\n"
                                f"     Completeness: {qc['completeness']:.1f}% "
                                f"(threshold: {criteria.completeness:.1f}%)\n"
                                f"     Contamination: {qc['contamination']:.1f}% "
                                f"(threshold: {criteria.contamination:.1f}%)\n"
                            )
