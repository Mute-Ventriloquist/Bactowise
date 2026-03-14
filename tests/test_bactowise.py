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
from bactowise.pipeline import Pipeline
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
            ToolConfig(name="prokka", version="1.14.6", runtime="kubernetes")


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
        with pytest.raises(Exception, match="(?i)at least one"):
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

    def test_singularity_runtime_returns_singularity_runner(self, tmp_path):
        from bactowise.runners.singularity_runner import SingularityToolRunner
        tool = ToolConfig(
            name="bakta", version="1.9.3", runtime="singularity",
            image="oschwengers/bakta:1.9.3"
        )
        # SingularityToolRunner has no external connection in __init__ — no mock needed
        runner = RunnerFactory.create(tool, tmp_path)
        assert isinstance(runner, SingularityToolRunner)

    def test_pgap_name_returns_pgap_runner(self, tmp_path):
        from bactowise.runners.pgap_runner import PGAPRunner
        tool = ToolConfig(
            name="pgap", version="2024-07-18.build7555", runtime="pgap",
            params={"organism": "Mycoplasmoides genitalium"}
        )
        # PGAPRunner has no external connection in __init__ — no mock needed
        runner = RunnerFactory.create(tool, tmp_path)
        assert isinstance(runner, PGAPRunner)

    def test_pgap_command_structure(self, tmp_path):
        from bactowise.runners.pgap_runner import PGAPRunner
        tool = ToolConfig(
            name="pgap", version="2024-07-18.build7555", runtime="pgap",
            params={"organism": "Mycoplasmoides genitalium", "threads": 4}
        )
        runner = PGAPRunner(tool, tmp_path)
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._build_command(
            pgap_bin="/usr/local/bin/pgap.py",
            runtime_bin="/usr/bin/singularity",
            fasta=fasta,
            organism="Mycoplasmoides genitalium",
            threads=4,
            report_usage=False,
        )
        assert "/usr/local/bin/pgap.py" in cmd
        assert "-g" in cmd
        assert "-s" in cmd
        assert "Mycoplasmoides genitalium" in cmd
        assert "-D" in cmd
        assert "/usr/bin/singularity" in cmd
        assert "-n" in cmd          # report_usage=False → -n flag
        assert "--no-internet" in cmd

    def test_unknown_runtime_raises(self, tmp_path):
        tool = ToolConfig.__new__(ToolConfig)
        object.__setattr__(tool, "name", "sometool")
        object.__setattr__(tool, "version", "1.0")
        object.__setattr__(tool, "runtime", "kubernetes")   # not supported
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


# ─── Pipeline skip tests ──────────────────────────────────────────────────────

class TestPipelineSkip:
    """
    Tests for the --skip / Pipeline(skip=...) feature.
    All tests mock runners so no real tools are needed.
    """

    def _make_config(self, tmp_path) -> "PipelineConfig":
        """Three-tool config: checkm → prokka + bakta (mirrors the real pipeline)."""
        return PipelineConfig(**{
            "tools": [
                {
                    "name": "checkm",
                    "version": "1.2.3",
                    "runtime": "conda",
                    "role": "qc",
                },
                {
                    "name": "prokka",
                    "version": "1.14.6",
                    "runtime": "conda",
                    "depends_on": ["checkm"],
                },
                {
                    "name": "bakta",
                    "version": "1.9.3",
                    "runtime": "docker",
                    "image": "oschwengers/bakta:1.9.3",
                    "depends_on": ["checkm"],
                },
            ],
            "output_dir": str(tmp_path),
        })

    def test_skip_unknown_tool_raises(self, tmp_path):
        config = self._make_config(tmp_path)
        with pytest.raises(ValueError, match="Unknown tool"):
            Pipeline(config, skip={"nonexistent_tool"})

    def test_skip_removes_tool_from_runners(self, tmp_path):
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip={"checkm"})
        assert "checkm" not in pipeline.runners
        assert "prokka" in pipeline.runners
        assert "bakta" in pipeline.runners

    def test_skip_all_annotation_tools(self, tmp_path):
        config = self._make_config(tmp_path)
        pipeline = Pipeline(config, skip={"prokka", "bakta"})
        assert "prokka" not in pipeline.runners
        assert "bakta"  not in pipeline.runners
        assert "checkm" in pipeline.runners

    def test_skip_unblocks_dependents(self, tmp_path):
        """
        Skipping checkm should place prokka and bakta in stage 0
        (treated as if their dependency is already satisfied).
        """
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip={"checkm"})

        stages = pipeline._build_stages()
        # All remaining tools should land in one stage with no ordering issue
        all_staged = [tool for stage in stages for tool in stage]
        assert "prokka" in all_staged
        assert "bakta"  in all_staged
        assert "checkm" not in all_staged

    def test_no_skip_preserves_normal_stages(self, tmp_path):
        """Without skips the stage order should be checkm first, then prokka+bakta."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip=set())

        stages = pipeline._build_stages()
        assert stages[0] == ["checkm"]
        assert set(stages[1]) == {"prokka", "bakta"}

    def test_skip_empty_set_is_a_noop(self, tmp_path):
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip=set())
        assert set(pipeline.runners.keys()) == {"checkm", "prokka", "bakta"}
