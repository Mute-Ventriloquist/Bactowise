from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from genoflow.models.config import PipelineConfig
from genoflow.runners.factory import RunnerFactory


class Pipeline:
    """
    Orchestrates all tools defined in the config.
    Runs all tools simultaneously (parallel) using a thread pool.
    Each tool writes to its own subfolder under output_dir.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.runners = [
            RunnerFactory.create(tool, config.output_dir)
            for tool in config.tools
        ]

    def preflight(self) -> None:
        """Run all pre-execution checks before any tool starts."""
        print("\n" + "="*50)
        print("  Genoflow — Preflight Checks")
        print("="*50)
        errors = []
        for runner in self.runners:
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
        """
        Run all tools simultaneously on the provided fasta file.
        Returns a dict of {tool_name: output_path}.
        """
        fasta = fasta.resolve()
        if not fasta.exists():
            raise FileNotFoundError(f"Input fasta not found: {fasta}")

        self.preflight()

        print("="*50)
        print(f"  Running {len(self.runners)} tool(s) in parallel")
        print(f"  Input:  {fasta}")
        print(f"  Output: {self.config.output_dir}")
        print("="*50 + "\n")

        results = {}
        errors = {}

        # ThreadPoolExecutor runs all tools simultaneously
        with ThreadPoolExecutor(max_workers=len(self.runners)) as executor:
            future_to_runner = {
                executor.submit(runner.run, fasta): runner
                for runner in self.runners
            }

            for future in as_completed(future_to_runner):
                runner = future_to_runner[future]
                tool_name = runner.config.name
                try:
                    output_path = future.result()
                    results[tool_name] = output_path
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
