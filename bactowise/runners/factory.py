from __future__ import annotations

from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.amrfinderplus_runner import AMRFinderPlusRunner
from bactowise.runners.base import BaseRunner
from bactowise.runners.checkm_runner import CheckMRunner
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.runners.consensus_runner import ConsensusRunner
from bactowise.runners.docker_runner import DockerToolRunner
from bactowise.runners.mefinder_runner import MobileElementFinderRunner
from bactowise.runners.pgap_runner import PGAPRunner
from bactowise.runners.phigaro_runner import PhigaroRunner
from bactowise.runners.platon_runner import PlatonRunner
from bactowise.runners.singularity_runner import SingularityToolRunner


class RunnerFactory:
    """
    Given a ToolConfig, returns the correct runner instance.
    Adding a new runtime type in future = add one elif here.
    """

    @staticmethod
    def create(tool_config: ToolConfig, output_dir: Path, organism: str = "", global_threads: int = 4) -> BaseRunner:
        # Named tools get their own specialised runner regardless of runtime
        if tool_config.name == "checkm":
            return CheckMRunner(tool_config, output_dir, organism, global_threads)
        if tool_config.name == "pgap":
            return PGAPRunner(tool_config, output_dir, organism, global_threads)
        if tool_config.name == "consensus":
            return ConsensusRunner(tool_config, output_dir, organism, global_threads)
        if tool_config.name == "amrfinderplus":
            return AMRFinderPlusRunner(tool_config, output_dir, organism, global_threads)
        if tool_config.name == "phigaro":
            return PhigaroRunner(tool_config, output_dir, organism, global_threads)
        if tool_config.name == "platon":
            return PlatonRunner(tool_config, output_dir, organism, global_threads)
        if tool_config.name == "mefinder":
            return MobileElementFinderRunner(tool_config, output_dir, organism, global_threads)

        if tool_config.runtime == "conda":
            return CondaToolRunner(tool_config, output_dir, organism, global_threads)
        elif tool_config.runtime == "docker":
            return DockerToolRunner(tool_config, output_dir, organism, global_threads)
        elif tool_config.runtime == "singularity":
            return SingularityToolRunner(tool_config, output_dir, organism, global_threads)
        else:
            raise ValueError(
                f"Unknown runtime '{tool_config.runtime}' for tool '{tool_config.name}'.\n"
                f"Supported runtimes: conda, docker, singularity, pgap"
            )
