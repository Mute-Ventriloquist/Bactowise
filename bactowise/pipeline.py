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

    Example:
        checkm           → stage 0 (no deps, runs first)
        prokka, bakta    → stage 1 (depend on checkm, run after checkm completes)
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.runners: dict[str, BaseRunner] = {
            tool.name: RunnerFactory.create(tool, config.output_dir)
            for tool in config.tools
        }

    def preflight(self) -> None:
        print("\n" + "="*50)
        print("  BactoWise — Preflight Checks")
        print("="*50)
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
        print(f"  Running {total} tool(s) in {len(stages)} stage(s)")
        print(f"  Input:  {fasta}")
        print(f"  Output: {self.config.output_dir}")
        print("="*50 + "\n")

        results: dict[str, Path] = {}
        errors: dict[str, str] = {}

        for stage_num, stage_tools in enumerate(stages, 1):
            print(f"\n── Stage {stage_num}: {', '.join(stage_tools)} {'─'*20}\n")

            # Warn if any dependency of tools in this stage failed QC
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
        Topological sort of tools into execution stages.

        Stage 0 = tools with no dependencies.
        Stage N = tools whose all dependencies are in stages 0..N-1.
        Tools within a stage run in parallel.
        """
        tool_configs = {t.name: t for t in self.config.tools}
        completed: set[str] = set()
        remaining = list(tool_configs.keys())
        stages = []

        while remaining:
            # Find all tools whose dependencies are all satisfied
            ready = [
                name for name in remaining
                if all(dep in completed for dep in tool_configs[name].depends_on)
            ]

            if not ready:
                # Circular dependency — should be caught by config validation
                raise RuntimeError(
                    f"Circular dependency detected among: {remaining}"
                )

            stages.append(ready)
            completed.update(ready)
            remaining = [n for n in remaining if n not in ready]

        return stages

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

                # Check if the QC runner stored a result with a failed evaluation
                if hasattr(dep_runner, "qc_result") and dep_runner.qc_result:
                    qc = dep_runner.qc_result
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
