"""
Tests for bactowise.
These tests validate orchestration logic — config parsing, validation,
runner creation, and pipeline wiring — without needing real tools installed.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from bactowise.models.config import DatabaseConfig, PipelineConfig, ToolConfig
from bactowise.runners.factory import RunnerFactory
from bactowise.utils.config_loader import load_config


# ─── Config model tests ───────────────────────────────────────────────────────

class TestToolConfig:
    def test_conda_tool_parses_correctly(self):
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        assert tool.name == "prokka"
        assert tool.runtime == "conda"
        assert tool.image is None           # no image for conda tools

    def test_docker_tool_autofills_image(self):
        tool = ToolConfig(name="bakta", version="1.9.3", runtime="docker")
        assert tool.image == "bakta:1.9.3"  # auto-filled from name:version

    def test_docker_tool_respects_explicit_image(self):
        tool = ToolConfig(
            name="bakta", version="1.9.3",
            runtime="docker", image="oschwengers/bakta:1.9.3"
        )
        assert tool.image == "oschwengers/bakta:1.9.3"

    def test_params_default_to_empty_dict(self):
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        assert tool.params == {}

    def test_invalid_runtime_raises(self):
        with pytest.raises(Exception):
            ToolConfig(name="prokka", version="1.14.6", runtime="singularity")


class TestPipelineConfig:
    def test_full_config_parses(self, tmp_path):
        raw = {
            "tools": [
                {"name": "prokka", "version": "1.14.6", "runtime": "conda"},
                {
                    "name": "bakta", "version": "1.9.3", "runtime": "docker",
                    "image": "oschwengers/bakta:1.9.3",
                    "database": {"path": str(tmp_path), "type": "light"},
                },
            ],
            "output_dir": str(tmp_path),
            "threads": 4,
        }
        config = PipelineConfig(**raw)
        assert len(config.tools) == 2
        assert config.threads == 4

    def test_empty_tools_raises(self, tmp_path):
        with pytest.raises(Exception, match="at least one"):
            PipelineConfig(tools=[], output_dir=str(tmp_path))

    def test_output_dir_defaults(self):
        config = PipelineConfig(
            tools=[{"name": "prokka", "version": "1.14.6", "runtime": "conda"}]
        )
        assert config.output_dir is not None


class TestDatabaseConfig:
    def test_valid_path_passes(self, tmp_path):
        db = DatabaseConfig(path=str(tmp_path), type="light")
        assert db.path == tmp_path

    def test_path_expanded(self):
        # ~ should be expanded without raising
        db = DatabaseConfig(path="~/some_db", type="light")
        assert "~" not in str(db.path)


# ─── Config loader tests ──────────────────────────────────────────────────────

class TestConfigLoader:
    def test_loads_valid_yaml(self, tmp_path):
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text(textwrap.dedent(f"""
            tools:
              - name: prokka
                version: "1.14.6"
                runtime: conda
            output_dir: {tmp_path}
        """))
        config = load_config(config_file)
        assert config.tools[0].name == "prokka"

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_raises_on_invalid_yaml(self, tmp_path):
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("tools: not_a_list")
        with pytest.raises(ValueError):
            load_config(config_file)


# ─── Runner factory tests ─────────────────────────────────────────────────────

class TestRunnerFactory:
    def test_conda_runtime_returns_conda_runner(self, tmp_path):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        runner = RunnerFactory.create(tool, tmp_path)
        assert isinstance(runner, CondaToolRunner)

    def test_docker_runtime_returns_docker_runner(self, tmp_path):
        from bactowise.runners.docker_runner import DockerToolRunner
        tool = ToolConfig(
            name="bakta", version="1.9.3", runtime="docker",
            image="oschwengers/bakta:1.9.3"
        )
        # mock Docker so test doesn't need Docker running
        with patch("docker.from_env") as mock_docker:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_docker.return_value = mock_client
            runner = RunnerFactory.create(tool, tmp_path)
            assert isinstance(runner, DockerToolRunner)

    def test_unknown_runtime_raises(self, tmp_path):
        tool = ToolConfig.__new__(ToolConfig)
        object.__setattr__(tool, "name", "sometool")
        object.__setattr__(tool, "version", "1.0")
        object.__setattr__(tool, "runtime", "singularity")   # not supported
        object.__setattr__(tool, "image", None)
        object.__setattr__(tool, "database", None)
        object.__setattr__(tool, "params", {})
        with pytest.raises(ValueError, match="Unknown runtime"):
            RunnerFactory.create(tool, tmp_path)


# ─── Version warning test ─────────────────────────────────────────────────────

class TestVersionWarning:
    def test_version_mismatch_warns_not_raises(self, tmp_path, capsys):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        runner = CondaToolRunner(tool, tmp_path)
        runner._check_version("1.14.5")         # different version
        captured = capsys.readouterr()
        assert "⚠" in captured.out             # warning printed
        # no exception raised — test passes if we reach this line


# ─── conda_env field tests ────────────────────────────────────────────────────

class TestCondaEnvField:
    def test_conda_env_with_dependencies(self):
        tool = ToolConfig(
            name="prokka", version="1.14.6", runtime="conda",
            conda_env={
                "name": "prokka_env",
                "channels": ["bioconda", "conda-forge"],
                "dependencies": ["python=3.8"]
            }
        )
        assert tool.conda_env.name == "prokka_env"
        assert tool.conda_env.dependencies == ["python=3.8"]
        assert tool.conda_env.channels == ["bioconda", "conda-forge"]

    def test_conda_env_no_dependencies(self):
        # tools like samtools need no extra deps — dependencies should be empty
        tool = ToolConfig(
            name="samtools", version="1.19", runtime="conda",
            conda_env={"name": "samtools_env"}
        )
        assert tool.conda_env.dependencies == []
        assert "bioconda" in tool.conda_env.channels

    def test_conda_env_multiple_dependencies(self):
        # GATK-style: needs a specific JDK
        tool = ToolConfig(
            name="gatk", version="4.5.0", runtime="conda",
            conda_env={
                "name": "gatk_env",
                "channels": ["bioconda", "conda-forge"],
                "dependencies": ["openjdk=11"]
            }
        )
        assert "openjdk=11" in tool.conda_env.dependencies

    def test_conda_env_rejected_for_docker_runtime(self):
        with pytest.raises(Exception, match="conda_env"):
            ToolConfig(
                name="bakta", version="1.9.3", runtime="docker",
                conda_env={"name": "some_env"}
            )

    def test_conda_env_none_by_default(self):
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        assert tool.conda_env is None

    def test_conda_env_invocation_uses_conda_run(self):
        # Tools with conda_env should be invoked via 'conda run -n <env>'
        # not via direct binary path — this is verified at the runner level
        tool = ToolConfig(
            name="prokka", version="1.14.6", runtime="conda",
            conda_env={"name": "prokka_env", "dependencies": ["python=3.8"]}
        )
        assert tool.conda_env.name == "prokka_env"
        assert tool.runtime == "conda"

    def test_no_conda_env_tool_uses_path(self):
        # Tools without conda_env rely on the binary being on PATH
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        assert tool.conda_env is None
