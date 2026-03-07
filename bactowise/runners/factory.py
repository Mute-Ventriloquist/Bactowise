from __future__ import annotations

from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.base import BaseRunner
from bactowise.runners.checkm_runner import CheckMRunner
from bactowise.runners.conda_runner import CondaToolRunner
from bactowise.runners.docker_runner import DockerToolRunner


class RunnerFactory:
    """
    Given a ToolConfig, returns the correct runner instance.
    Adding a new runtime type in future = add one elif here.
    """

    @staticmethod
    def create(tool_config: ToolConfig, output_dir: Path) -> BaseRunner:
        # QC tools get their own specialised runner regardless of runtime
        if tool_config.name == "checkm":
            return CheckMRunner(tool_config, output_dir)

        if tool_config.runtime == "conda":
            return CondaToolRunner(tool_config, output_dir)
        elif tool_config.runtime == "docker":
            return DockerToolRunner(tool_config, output_dir)
        else:
            raise ValueError(
                f"Unknown runtime '{tool_config.runtime}' for tool '{tool_config.name}'.\n"
                f"Supported runtimes: conda, docker"
            )
