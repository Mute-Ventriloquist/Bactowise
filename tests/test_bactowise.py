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
            runner = RunnerFactory.create(tool, tmp_path, organism="Escherichia coli")
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
            params={"report_usage": False}
        )
        runner = PGAPRunner(tool, tmp_path, organism="Mycoplasmoides genitalium")
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._build_command(
            pgap_bin="/usr/local/bin/pgap.py",
            runtime_bin="/usr/bin/singularity",
            fasta=fasta,
            organism="Mycoplasmoides genitalium",
            threads=1,
            report_usage=False,
        )
        assert "/usr/local/bin/pgap.py" in cmd
        assert "-g" in cmd
        assert "-s" in cmd
        assert "Mycoplasmoides genitalium" in cmd
        assert "-D" in cmd
        assert "/usr/bin/singularity" in cmd
        assert "-n" in cmd          # report_usage=False → -n flag

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


# ─── Organism propagation tests ──────────────────────────────────────────────

class TestOrganismPropagation:
    def test_organism_parts_full(self, tmp_path):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        runner = CondaToolRunner(tool, tmp_path, organism="Mycoplasmoides genitalium")
        assert runner._organism_parts() == ("Mycoplasmoides", "genitalium")

    def test_organism_parts_genus_only(self, tmp_path):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        runner = CondaToolRunner(tool, tmp_path, organism="Mycoplasma")
        assert runner._organism_parts() == ("Mycoplasma", "")

    def test_organism_parts_empty(self, tmp_path):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        runner = CondaToolRunner(tool, tmp_path, organism="")
        assert runner._organism_parts() == ("", "")

    def test_prokka_command_includes_genus_species(self, tmp_path):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        runner = CondaToolRunner(tool, tmp_path, organism="Escherichia coli")
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._prokka_command(fasta)
        assert "--genus" in cmd
        assert "Escherichia" in cmd
        assert "--species" in cmd
        assert "coli" in cmd

    def test_prokka_command_no_organism(self, tmp_path):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        runner = CondaToolRunner(tool, tmp_path, organism="")
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._prokka_command(fasta)
        assert "--genus" not in cmd
        assert "--species" not in cmd

    def test_pipeline_passes_organism_to_runners(self, tmp_path):
        from bactowise.pipeline import Pipeline
        from bactowise.models.config import PipelineConfig
        config = PipelineConfig(
            tools=[{"name": "prokka", "version": "1.14.6", "runtime": "conda"}],
            output_dir=str(tmp_path),
        )
        pipeline = Pipeline(config, organism="Staphylococcus aureus")
        assert pipeline.organism == "Staphylococcus aureus"
        assert pipeline.runners["prokka"].organism == "Staphylococcus aureus"

    def test_pipeline_passes_global_threads_to_runners(self, tmp_path):
        from bactowise.pipeline import Pipeline
        from bactowise.models.config import PipelineConfig
        config = PipelineConfig(
            tools=[{"name": "prokka", "version": "1.14.6", "runtime": "conda"}],
            output_dir=str(tmp_path),
            threads=8,
        )
        pipeline = Pipeline(config)
        assert pipeline.runners["prokka"].global_threads == 8

    def test_output_dir_override_via_model_copy(self, tmp_path):
        """model_copy(update=...) correctly overrides output_dir without mutating original."""
        from bactowise.models.config import PipelineConfig
        config = PipelineConfig(
            tools=[{"name": "prokka", "version": "1.14.6", "runtime": "conda"}],
            output_dir=str(tmp_path / "default"),
        )
        custom = tmp_path / "custom_output"
        overridden = config.model_copy(update={"output_dir": custom.resolve()})
        assert overridden.output_dir == custom.resolve()
        assert config.output_dir == (tmp_path / "default").resolve()  # original unchanged


# ─── Global threads fallback tests ───────────────────────────────────────────

class TestGlobalThreadsFallback:
    """
    Verify that global_threads flows through to command builders as a fallback
    when threads/cpus are not set in params.
    """

    def test_prokka_uses_global_threads_when_cpus_not_in_params(self, tmp_path):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(name="prokka", version="1.14.6", runtime="conda")
        runner = CondaToolRunner(tool, tmp_path, global_threads=8)
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._prokka_command(fasta)
        assert "--cpus" in cmd
        assert cmd[cmd.index("--cpus") + 1] == "8"

    def test_prokka_respects_explicit_cpus_over_global_threads(self, tmp_path):
        from bactowise.runners.conda_runner import CondaToolRunner
        tool = ToolConfig(
            name="prokka", version="1.14.6", runtime="conda",
            params={"cpus": 2}
        )
        runner = CondaToolRunner(tool, tmp_path, global_threads=8)
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._prokka_command(fasta)
        # "2" (from params) should appear, global threads (8) should not
        cpus_val = cmd[cmd.index("--cpus") + 1]
        assert cpus_val == "2"

    def test_checkm_uses_global_threads_when_threads_not_in_params(self, tmp_path):
        from bactowise.runners.checkm_runner import CheckMRunner
        tool = ToolConfig(
            name="checkm", version="1.2.3", runtime="conda", role="qc",
        )
        runner = CheckMRunner(tool, tmp_path, global_threads=6)
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._build_checkm_command(fasta, "taxonomy_wf")
        assert "-t" in cmd
        assert cmd[cmd.index("-t") + 1] == "6"

    def test_checkm_respects_explicit_threads_over_global(self, tmp_path):
        from bactowise.runners.checkm_runner import CheckMRunner
        tool = ToolConfig(
            name="checkm", version="1.2.3", runtime="conda", role="qc",
            params={"threads": 2}
        )
        runner = CheckMRunner(tool, tmp_path, global_threads=8)
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._build_checkm_command(fasta, "taxonomy_wf")
        assert cmd[cmd.index("-t") + 1] == "2"

    def test_bakta_singularity_uses_global_threads_when_not_in_params(self, tmp_path):
        from bactowise.runners.singularity_runner import SingularityToolRunner
        tool = ToolConfig(
            name="bakta", version="1.12.0", runtime="singularity",
            image="oschwengers/bakta:v1.12.0",
        )
        runner = SingularityToolRunner(tool, tmp_path, global_threads=10)
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._bakta_command(fasta)
        assert "--threads" in cmd
        assert cmd[cmd.index("--threads") + 1] == "10"

    def test_bakta_singularity_respects_explicit_threads_over_global(self, tmp_path):
        from bactowise.runners.singularity_runner import SingularityToolRunner
        tool = ToolConfig(
            name="bakta", version="1.12.0", runtime="singularity",
            image="oschwengers/bakta:v1.12.0",
            params={"threads": 3}
        )
        runner = SingularityToolRunner(tool, tmp_path, global_threads=10)
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        cmd = runner._bakta_command(fasta)
        assert cmd[cmd.index("--threads") + 1] == "3"


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
    Tests for the --skip stage_N / Pipeline(skip_stages=...) feature.
    All tests mock runners so no real tools are needed.
    """

    def _make_config(self, tmp_path) -> "PipelineConfig":
        """Three-tool config: checkm (stage 1) -> prokka + bakta (stage 2)."""
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

    def test_skip_invalid_stage_format_raises(self, tmp_path):
        """Passing a tool name instead of a stage number should raise."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            with pytest.raises((ValueError, TypeError)):
                Pipeline(config, skip_stages={"checkm"})  # type: ignore

    def test_skip_stage_2_raises(self, tmp_path):
        """Attempting to skip stage 2 (annotation) must raise immediately."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            with pytest.raises(ValueError, match="cannot be skipped"):
                Pipeline(config, skip_stages={2})

    def test_skip_stage_1_removes_qc_from_runners(self, tmp_path):
        """skip_stages={1} must exclude checkm from runners."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages={1})
        assert "checkm" not in pipeline.runners
        assert "prokka" in pipeline.runners
        assert "bakta" in pipeline.runners

    def test_skip_stage_1_resolves_to_correct_tool_names(self, tmp_path):
        """skip_stages={1} should resolve self.skip to the QC tool names."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages={1})
        assert "checkm" in pipeline.skip
        assert "prokka" not in pipeline.skip
        assert "bakta" not in pipeline.skip

    def test_skip_stage_1_unblocks_dependents(self, tmp_path):
        """
        skip_stages={1} should place prokka and bakta in stage 1 of the
        build output (treated as if their dependency is already satisfied).
        """
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages={1})

        stages = pipeline._build_stages()
        all_staged = [tool for stage in stages for tool in stage]
        assert "prokka" in all_staged
        assert "bakta"  in all_staged
        assert "checkm" not in all_staged

    def test_no_skip_preserves_normal_stages(self, tmp_path):
        """Without skips the stage order should be checkm first, then prokka+bakta."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages=set())

        stages = pipeline._build_stages()
        assert stages[0] == ["checkm"]
        assert set(stages[1]) == {"prokka", "bakta"}

    def test_skip_empty_set_is_a_noop(self, tmp_path):
        """skip_stages=set() should leave all runners intact."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages=set())
        assert set(pipeline.runners.keys()) == {"checkm", "prokka", "bakta"}


# ─── GFF bypass tests ─────────────────────────────────────────────────────────

class TestGFFBypass:
    """
    Tests for the --gff / Pipeline(gff_files=...) feature.
    Uses the same three-tool config as TestPipelineSkip.
    No real tools are invoked — runners are mocked where needed.
    """

    def _make_config(self, tmp_path) -> "PipelineConfig":
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

    def _make_gff_files(self, tmp_path) -> dict:
        """Create real (empty) GFF files so existence checks pass."""
        bakta_gff  = tmp_path / "bakta.gff3"
        prokka_gff = tmp_path / "prokka.gff"
        bakta_gff.touch()
        prokka_gff.touch()
        return {"bakta": bakta_gff, "prokka": prokka_gff}

    def test_annotation_tools_returns_correct_set(self, tmp_path):
        """_annotation_tools() should return exactly the stage-2 tools."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config)
        assert pipeline._annotation_tools() == {"prokka", "bakta"}

    def test_all_gffs_provided_passes_validation(self, tmp_path):
        """Providing GFF for all annotation tools should not raise."""
        config = self._make_config(tmp_path)
        gff_files = self._make_gff_files(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, gff_files=gff_files)
        assert set(pipeline.gff_files.keys()) == {"bakta", "prokka"}

    def test_partial_gff_one_tool_passes(self, tmp_path):
        """Providing GFF for only one annotation tool should now be valid."""
        config = self._make_config(tmp_path)
        bakta_gff = tmp_path / "bakta.gff3"
        bakta_gff.touch()
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, gff_files={"bakta": bakta_gff})
        assert "bakta" in pipeline.gff_files
        # prokka should still have a runner since no GFF was provided for it
        assert "prokka" in pipeline.runners
        assert "bakta" not in pipeline.runners

    def test_partial_gff_two_tools_passes(self, tmp_path):
        """Providing GFF for two of three annotation tools should be valid."""
        config = self._make_config(tmp_path)
        gff_files = self._make_gff_files(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, gff_files=gff_files)
        assert set(pipeline.gff_files.keys()) == {"bakta", "prokka"}
        # checkm still has a runner (it's a QC tool, not an annotation tool)
        assert "checkm" in pipeline.runners

    def test_no_gff_passes_validation(self, tmp_path):
        """Providing no GFF files is always valid."""
        config = self._make_config(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, gff_files=None)
        assert pipeline.gff_files == {}

    def test_gff_for_unknown_tool_raises(self, tmp_path):
        """GFF for a tool not in the config's annotation tools should raise."""
        config = self._make_config(tmp_path)
        fake = tmp_path / "fake.gff"
        fake.touch()
        with pytest.raises(ValueError, match="unknown or non-annotation tool"):
            with patch("docker.from_env") as mock_docker:
                mock_docker.return_value.ping.return_value = True
                Pipeline(config, gff_files={"nonexistent": fake})

    def test_gff_for_qc_tool_raises(self, tmp_path):
        """GFF for a QC tool (checkm) is not valid — it has no depends_on."""
        config = self._make_config(tmp_path)
        fake = tmp_path / "checkm.gff"
        fake.touch()
        with pytest.raises(ValueError, match="unknown or non-annotation tool"):
            Pipeline(config, gff_files={"checkm": fake})

    def test_gff_and_skip_same_tool_raises(self, tmp_path):
        """A GFF tool name that is also in the skipped set is contradictory."""
        config = self._make_config(tmp_path)
        gff_files = self._make_gff_files(tmp_path)
        # skip_stages={1} skips checkm; gff_files covers bakta+prokka (annotation
        # tools) -- no overlap, so this should NOT raise.
        # To trigger the conflict we need to contrive a situation where the
        # resolved self.skip overlaps with gff_files keys, which cannot happen
        # via the public API (stage 1 = QC tools, gff = annotation tools only).
        # The internal guard still exists; test it directly via _validate_gff_files.
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages={1}, gff_files=gff_files)
        # Manually inject a fake overlap and confirm the guard fires
        pipeline.skip.add("bakta")
        with pytest.raises(ValueError, match="both --gff and --skip"):
            pipeline._validate_gff_files(gff_files)

    def test_gff_missing_file_raises(self, tmp_path):
        """GFF path that does not exist on disk must raise FileNotFoundError."""
        config = self._make_config(tmp_path)
        with pytest.raises(FileNotFoundError, match="not found"):
            with patch("docker.from_env") as mock_docker:
                mock_docker.return_value.ping.return_value = True
                Pipeline(config, gff_files={
                    "bakta":  tmp_path / "does_not_exist.gff3",
                })

    def test_gff_bypass_creates_no_runners_for_bypassed_tools(self, tmp_path):
        """Bypassed tools must not have runners created — no Docker contact."""
        config = self._make_config(tmp_path)
        gff_files = self._make_gff_files(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, gff_files=gff_files)
        assert "checkm" in pipeline.runners
        assert "bakta"  not in pipeline.runners
        assert "prokka" not in pipeline.runners

    def test_partial_bypass_creates_runner_only_for_non_bypassed(self, tmp_path):
        """With one GFF provided, only the non-bypassed tool gets a runner."""
        config = self._make_config(tmp_path)
        bakta_gff = tmp_path / "bakta.gff3"
        bakta_gff.touch()
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, gff_files={"bakta": bakta_gff})
        assert "checkm" in pipeline.runners
        assert "prokka" in pipeline.runners
        assert "bakta"  not in pipeline.runners

    def test_apply_gff_bypass_copies_files(self, tmp_path):
        """_apply_gff_bypass() must copy GFF files to the tool output directories."""
        config = self._make_config(tmp_path)
        gff_files = self._make_gff_files(tmp_path)
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, gff_files=gff_files)

        results = {}
        pipeline._apply_gff_bypass(["bakta", "prokka"], results)

        assert "bakta"  in results
        assert "prokka" in results
        assert (results["bakta"]  / "provided_bakta.gff3").exists()
        assert (results["prokka"] / "provided_prokka.gff").exists()


# ─── ConsensusRunner tests ────────────────────────────────────────────────────

class TestConsensusRunner:
    """
    Tests for ConsensusRunner — GFF discovery, staging, and command building.
    No real tools or conda envs are needed.
    """

    def _make_tool_config(self) -> ToolConfig:
        return ToolConfig(
            name="consensus",
            version="1.0.0",
            runtime="conda",
            depends_on=["bakta", "prokka", "pgap"],
            conda_env={"name": "consensus_env", "dependencies": ["pandas", "openpyxl"]},
        )

    def test_factory_returns_consensus_runner(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = RunnerFactory.create(tool, tmp_path)
        assert isinstance(runner, ConsensusRunner)

    def test_find_bakta_gff_normal_run(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        # Simulate normal Bakta output
        bakta_dir = tmp_path / "bakta"
        bakta_dir.mkdir()
        gff = bakta_dir / "mgenitalium.gff3"
        gff.touch()

        result = runner._find_bakta_gff(bakta_dir)
        assert result == gff

    def test_find_bakta_gff_bypass(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        bakta_dir = tmp_path / "bakta"
        bakta_dir.mkdir()
        gff = bakta_dir / "provided_bakta.gff3"
        gff.touch()

        result = runner._find_bakta_gff(bakta_dir)
        assert result == gff

    def test_find_bakta_gff_not_found_raises(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        bakta_dir = tmp_path / "bakta"
        bakta_dir.mkdir()

        with pytest.raises(RuntimeError, match="No Bakta GFF"):
            runner._find_bakta_gff(bakta_dir)

    def test_find_prokka_gff_normal_run(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        prokka_dir = tmp_path / "prokka"
        prokka_dir.mkdir()
        gff = prokka_dir / "prokka_output.gff"
        gff.touch()

        result = runner._find_prokka_gff(prokka_dir)
        assert result == gff

    def test_find_prokka_gff_bypass(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        prokka_dir = tmp_path / "prokka"
        prokka_dir.mkdir()
        gff = prokka_dir / "provided_prokka_output.gff"
        gff.touch()

        result = runner._find_prokka_gff(prokka_dir)
        assert result == gff

    def test_find_pgap_gff_normal_run_picks_most_recent(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        pgap_dir = tmp_path / "pgap"
        pgap_dir.mkdir()

        # Create two run dirs — most recent should be picked
        older = pgap_dir / "run_1000000000"
        newer = pgap_dir / "run_2000000000"
        for d in (older, newer):
            d.mkdir()
            (d / "annot.gff").touch()

        result = runner._find_pgap_gff(pgap_dir)
        assert result == newer / "annot.gff"

    def test_find_pgap_gff_bypass(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        pgap_dir = tmp_path / "pgap"
        pgap_dir.mkdir()
        gff = pgap_dir / "provided_annot.gff"
        gff.touch()

        result = runner._find_pgap_gff(pgap_dir)
        assert result == gff

    def test_find_pgap_gff_not_found_raises(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        pgap_dir = tmp_path / "pgap"
        pgap_dir.mkdir()

        with pytest.raises(RuntimeError, match="No PGAP GFF"):
            runner._find_pgap_gff(pgap_dir)

    def test_build_engine_command_includes_key_args(self, tmp_path):
        from bactowise.runners.consensus_runner import ConsensusRunner, _ENGINE_PATH
        tool = self._make_tool_config()
        runner = ConsensusRunner(tool, tmp_path)

        staging = tmp_path / "staging"
        output  = tmp_path / "consensus"

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_engine_command(staging, output)

        assert "/usr/bin/conda" in cmd
        assert "consensus_env" in cmd
        assert "python" in cmd
        assert str(_ENGINE_PATH) in cmd
        assert "--input" in cmd
        assert str(staging) in cmd
        assert "--output" in cmd
        assert str(output) in cmd

    def test_consensus_in_pipeline_stages_as_stage_3(self, tmp_path):
        """consensus must appear in stage 3 (after bakta, prokka, pgap)."""
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",    "version": "1.2.3",            "runtime": "conda", "role": "qc"},
                {"name": "prokka",    "version": "1.14.6",            "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",     "version": "1.9.3",             "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                  "depends_on": ["checkm"]},
                {"name": "pgap",      "version": "2024-07-18.build7555", "runtime": "pgap", "depends_on": ["checkm"]},
                {"name": "consensus", "version": "1.0.0",             "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas", "openpyxl"]}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config)

        stages = pipeline._build_stages()
        # stage 1: checkm, stage 2: prokka+bakta+pgap, stage 3: consensus
        assert stages[0] == ["checkm"]
        assert set(stages[1]) == {"prokka", "bakta", "pgap"}
        assert stages[2] == ["consensus"]

    def test_consensus_not_skippable(self, tmp_path):
        """Stage 3 contains consensus — attempting --skip stage_3 must raise."""
        config = PipelineConfig(**{
            "tools": [
                {"name": "prokka",    "version": "1.14.6", "runtime": "conda"},
                {"name": "consensus", "version": "1.0.0",  "runtime": "conda",
                 "depends_on": ["prokka"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
            ],
            "output_dir": str(tmp_path),
        })
        with pytest.raises(ValueError, match="cannot be skipped"):
            Pipeline(config, skip_stages={3})


# ─── AMRFinderPlusRunner tests ────────────────────────────────────────────────

class TestAMRFinderPlusRunner:
    """
    Tests for AMRFinderPlusRunner — factory dispatch, command building,
    FAA discovery, stage 4 skippability.
    """

    def _make_tool_config(self, **extra_params) -> ToolConfig:
        params = {"plus": True}
        params.update(extra_params)
        return ToolConfig(
            name="amrfinderplus",
            version="latest",
            runtime="conda",
            depends_on=["consensus"],
            conda_env={"name": "amrfinderplus_env", "dependencies": []},
            params=params,
        )

    def test_factory_returns_amrfinderplus_runner(self, tmp_path):
        from bactowise.runners.amrfinderplus_runner import AMRFinderPlusRunner
        tool = self._make_tool_config()
        runner = RunnerFactory.create(tool, tmp_path)
        assert isinstance(runner, AMRFinderPlusRunner)

    def test_build_command_basic(self, tmp_path):
        from bactowise.runners.amrfinderplus_runner import AMRFinderPlusRunner
        tool   = self._make_tool_config()
        runner = AMRFinderPlusRunner(tool, tmp_path, global_threads=4)

        fasta      = tmp_path / "genome.fasta"
        output_tsv = tmp_path / "amrfinderplus_results.tsv"
        fasta.touch()

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta, output_tsv)

        assert "-n" in cmd
        assert str(fasta.resolve()) in cmd
        assert "-p" not in cmd
        assert "-o" in cmd
        assert str(output_tsv) in cmd
        assert "--plus" in cmd
        assert "-t" in cmd

    def test_build_command_with_organism(self, tmp_path):
        from bactowise.runners.amrfinderplus_runner import AMRFinderPlusRunner
        tool   = self._make_tool_config(organism="Escherichia")
        runner = AMRFinderPlusRunner(tool, tmp_path, global_threads=4)

        fasta      = tmp_path / "genome.fasta"
        output_tsv = tmp_path / "out.tsv"

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta, output_tsv)

        assert "--organism" in cmd
        assert "Escherichia" in cmd

    def test_build_command_no_organism_no_flag(self, tmp_path):
        from bactowise.runners.amrfinderplus_runner import AMRFinderPlusRunner
        tool   = self._make_tool_config()
        runner = AMRFinderPlusRunner(tool, tmp_path, global_threads=4)

        fasta      = tmp_path / "genome.fasta"
        output_tsv = tmp_path / "out.tsv"

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta, output_tsv)

        assert "--organism" not in cmd


    def test_conda_run_cmd_uses_amrfinder_binary(self, tmp_path):
        """Binary in conda run must be 'amrfinder', not 'amrfinderplus'."""
        from bactowise.runners.amrfinderplus_runner import AMRFinderPlusRunner
        tool   = self._make_tool_config()
        runner = AMRFinderPlusRunner(tool, tmp_path)

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._conda_run_cmd(["--version"])

        assert "amrfinder" in cmd
        assert "amrfinderplus" not in cmd

    def test_stage_4_is_skippable(self, tmp_path):
        """--skip stage_4 must be accepted and resolve to amrfinderplus."""
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",        "version": "1.2.3",               "runtime": "conda", "role": "qc"},
                {"name": "prokka",        "version": "1.14.6",              "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",         "version": "1.9.3",               "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                         "depends_on": ["checkm"]},
                {"name": "pgap",          "version": "2024-07-18.build7555", "runtime": "pgap",  "depends_on": ["checkm"]},
                {"name": "consensus",     "version": "1.0.0",               "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
                {"name": "amrfinderplus", "version": "latest",              "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "amrfinderplus_env", "dependencies": []}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages={4})
        assert "amrfinderplus" in pipeline.skip
        assert "consensus" not in pipeline.skip

    def test_stage_4_appears_in_stage_4_of_full_pipeline(self, tmp_path):
        """amrfinderplus must land in stage 4 of the full pipeline stage map."""
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",        "version": "1.2.3",              "runtime": "conda", "role": "qc"},
                {"name": "prokka",        "version": "1.14.6",             "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",         "version": "1.9.3",              "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                        "depends_on": ["checkm"]},
                {"name": "pgap",          "version": "2024-07-18.build7555","runtime": "pgap", "depends_on": ["checkm"]},
                {"name": "consensus",     "version": "1.0.0",              "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
                {"name": "amrfinderplus", "version": "latest",             "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "amrfinderplus_env", "dependencies": []}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config)

        stages = pipeline._build_stages()
        assert stages[0] == ["checkm"]
        assert set(stages[1]) == {"prokka", "bakta", "pgap"}
        assert stages[2] == ["consensus"]
        assert stages[3] == ["amrfinderplus"]

    def test_stage_2_still_not_skippable(self, tmp_path):
        """Ensure stage 2 remains unskippable after adding stage 4."""
        config = PipelineConfig(**{
            "tools": [
                {"name": "prokka", "version": "1.14.6", "runtime": "conda"},
            ],
            "output_dir": str(tmp_path),
        })
        with pytest.raises(ValueError, match="cannot be skipped"):
            Pipeline(config, skip_stages={2})


# ─── PhigaroRunner tests ──────────────────────────────────────────────────────

class TestPhigaroRunner:
    """
    Tests for PhigaroRunner — factory dispatch, command building,
    setup detection, and stage 4 placement.
    """

    def _make_tool_config(self) -> ToolConfig:
        return ToolConfig(
            name="phigaro",
            version="latest",
            runtime="conda",
            depends_on=["consensus"],
            conda_env={"name": "phigaro_env", "dependencies": []},
        )

    def test_factory_returns_phigaro_runner(self, tmp_path):
        from bactowise.runners.phigaro_runner import PhigaroRunner
        tool   = self._make_tool_config()
        runner = RunnerFactory.create(tool, tmp_path)
        assert isinstance(runner, PhigaroRunner)

    def test_build_command_basic(self, tmp_path):
        from bactowise.runners.phigaro_runner import PhigaroRunner
        tool   = self._make_tool_config()
        runner = PhigaroRunner(tool, tmp_path, global_threads=4)

        fasta         = tmp_path / "genome.fasta"
        output_prefix = tmp_path / "phigaro_output"
        fasta.touch()

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta, output_prefix)

        assert "-f" in cmd
        assert str(fasta.resolve()) in cmd
        assert "-o" in cmd
        assert str(output_prefix) in cmd
        assert "-e" in cmd
        assert "tsv" in cmd
        assert "gff" in cmd
        assert "--not-open" in cmd
        assert "-t" in cmd

    def test_build_command_threads_fallback(self, tmp_path):
        from bactowise.runners.phigaro_runner import PhigaroRunner
        tool   = self._make_tool_config()
        runner = PhigaroRunner(tool, tmp_path, global_threads=6)

        fasta         = tmp_path / "genome.fasta"
        output_prefix = tmp_path / "phigaro_output"

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta, output_prefix)

        assert "-t" in cmd
        assert cmd[cmd.index("-t") + 1] == "6"

    def test_build_command_explicit_threads(self, tmp_path):
        from bactowise.runners.phigaro_runner import PhigaroRunner
        tool = ToolConfig(
            name="phigaro", version="latest", runtime="conda",
            depends_on=["consensus"],
            conda_env={"name": "phigaro_env", "dependencies": []},
            params={"threads": 2},
        )
        runner = PhigaroRunner(tool, tmp_path, global_threads=8)

        fasta         = tmp_path / "genome.fasta"
        output_prefix = tmp_path / "phigaro_output"

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta, output_prefix)

        assert cmd[cmd.index("-t") + 1] == "2"

    def test_conda_run_cmd_for_setup_uses_phigaro_setup_binary(self, tmp_path):
        from bactowise.runners.phigaro_runner import PhigaroRunner
        tool   = self._make_tool_config()
        runner = PhigaroRunner(tool, tmp_path)

        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._conda_run_cmd_for("phigaro-setup", ["--auto"])

        assert "phigaro-setup" in cmd
        assert "--auto" in cmd
        assert "phigaro_env" in cmd

    def test_phigaro_in_stage_4_of_full_pipeline(self, tmp_path):
        """phigaro must land in stage 4 alongside amrfinderplus."""
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",        "version": "1.2.3",               "runtime": "conda", "role": "qc"},
                {"name": "prokka",        "version": "1.14.6",              "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",         "version": "1.9.3",               "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                         "depends_on": ["checkm"]},
                {"name": "pgap",          "version": "2024-07-18.build7555", "runtime": "pgap",  "depends_on": ["checkm"]},
                {"name": "consensus",     "version": "1.0.0",               "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
                {"name": "amrfinderplus", "version": "latest",              "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "amrfinderplus_env", "dependencies": []}},
                {"name": "phigaro",       "version": "latest",              "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "phigaro_env", "dependencies": []}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config)

        stages = pipeline._build_stages()
        assert stages[0] == ["checkm"]
        assert set(stages[1]) == {"prokka", "bakta", "pgap"}
        assert stages[2] == ["consensus"]
        assert set(stages[3]) == {"amrfinderplus", "phigaro"}

    def test_phigaro_skipped_with_stage_4(self, tmp_path):
        """--skip stage_4 must also skip phigaro."""
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",        "version": "1.2.3",               "runtime": "conda", "role": "qc"},
                {"name": "prokka",        "version": "1.14.6",              "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",         "version": "1.9.3",               "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                         "depends_on": ["checkm"]},
                {"name": "pgap",          "version": "2024-07-18.build7555", "runtime": "pgap",  "depends_on": ["checkm"]},
                {"name": "consensus",     "version": "1.0.0",               "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
                {"name": "amrfinderplus", "version": "latest",              "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "amrfinderplus_env", "dependencies": []}},
                {"name": "phigaro",       "version": "latest",              "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "phigaro_env", "dependencies": []}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages={4})

        assert "phigaro"       in pipeline.skip
        assert "amrfinderplus" in pipeline.skip
        assert "consensus"     not in pipeline.skip


# ─── PlatonRunner tests ───────────────────────────────────────────────────────

class TestPlatonRunner:

    def _make_tool_config(self, **params) -> ToolConfig:
        p = {"mode": "accuracy"}
        p.update(params)
        return ToolConfig(
            name="platon", version="latest", runtime="conda",
            depends_on=["consensus"],
            conda_env={"name": "platon_env", "dependencies": []},
            params=p,
        )

    def test_factory_returns_platon_runner(self, tmp_path):
        from bactowise.runners.platon_runner import PlatonRunner
        runner = RunnerFactory.create(self._make_tool_config(), tmp_path)
        assert isinstance(runner, PlatonRunner)

    def test_build_command_basic(self, tmp_path):
        from bactowise.runners.platon_runner import PlatonRunner
        from bactowise.utils.db_manager import _PLATON_DB_DIR
        runner = PlatonRunner(self._make_tool_config(), tmp_path, global_threads=4)
        fasta = tmp_path / "genome.fasta"
        fasta.touch()
        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta)
        assert str(fasta.resolve()) in cmd
        assert "--db" in cmd
        assert str(_PLATON_DB_DIR) in cmd
        assert "--output" in cmd
        assert "--prefix" in cmd
        assert "platon_output" in cmd
        assert "--mode" in cmd
        assert "accuracy" in cmd
        assert "--threads" in cmd

    def test_build_command_custom_mode(self, tmp_path):
        from bactowise.runners.platon_runner import PlatonRunner
        runner = PlatonRunner(
            self._make_tool_config(mode="sensitivity"), tmp_path, global_threads=4
        )
        fasta = tmp_path / "genome.fasta"
        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta)
        assert "sensitivity" in cmd

    def test_platon_in_stage_4(self, tmp_path):
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",    "version": "1.2.3",               "runtime": "conda", "role": "qc"},
                {"name": "prokka",    "version": "1.14.6",              "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",     "version": "1.9.3",               "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                     "depends_on": ["checkm"]},
                {"name": "pgap",      "version": "2024-07-18.build7555", "runtime": "pgap",  "depends_on": ["checkm"]},
                {"name": "consensus", "version": "1.0.0",               "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
                {"name": "platon",    "version": "latest",              "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "platon_env", "dependencies": []}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config)
        stages = pipeline._build_stages()
        assert stages[3] == ["platon"]


# ─── MobileElementFinderRunner tests ─────────────────────────────────────────

class TestMobileElementFinderRunner:

    def _make_tool_config(self) -> ToolConfig:
        return ToolConfig(
            name="mefinder", version="latest", runtime="conda",
            depends_on=["consensus"],
            conda_env={"name": "mefinder_env", "dependencies": []},
        )

    def test_factory_returns_mefinder_runner(self, tmp_path):
        from bactowise.runners.mefinder_runner import MobileElementFinderRunner
        runner = RunnerFactory.create(self._make_tool_config(), tmp_path)
        assert isinstance(runner, MobileElementFinderRunner)

    def test_build_command_basic(self, tmp_path):
        from bactowise.runners.mefinder_runner import MobileElementFinderRunner
        runner = MobileElementFinderRunner(
            self._make_tool_config(), tmp_path, global_threads=4
        )
        fasta         = tmp_path / "genome.fasta"
        output_prefix = tmp_path / "mefinder_output"
        fasta.touch()
        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(fasta, output_prefix)
        assert "find" in cmd
        assert "-c" in cmd
        assert str(fasta.resolve()) in cmd
        assert "-t" in cmd
        assert "-g" in cmd
        assert str(output_prefix) in cmd

    def test_conda_run_cmd_uses_mefinder_binary(self, tmp_path):
        from bactowise.runners.mefinder_runner import MobileElementFinderRunner
        runner = MobileElementFinderRunner(self._make_tool_config(), tmp_path)
        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._conda_run_cmd(["find", "--version"])
        assert "mefinder" in cmd
        assert "mefinder_env" in cmd

    def test_mefinder_in_stage_4(self, tmp_path):
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",    "version": "1.2.3",               "runtime": "conda", "role": "qc"},
                {"name": "prokka",    "version": "1.14.6",              "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",     "version": "1.9.3",               "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                     "depends_on": ["checkm"]},
                {"name": "pgap",      "version": "2024-07-18.build7555", "runtime": "pgap",  "depends_on": ["checkm"]},
                {"name": "consensus", "version": "1.0.0",               "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
                {"name": "mefinder",  "version": "latest",              "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "mefinder_env", "dependencies": []}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config)
        stages = pipeline._build_stages()
        assert stages[3] == ["mefinder"]


# ─── EggNOGMapperRunner tests ─────────────────────────────────────────────────

class TestEggNOGMapperRunner:

    def _make_tool_config(self, **params) -> ToolConfig:
        p = {"tax_scope": "Bacteria", "go_evidence": "all"}
        p.update(params)
        return ToolConfig(
            name="eggnogmapper", version="latest", runtime="conda",
            depends_on=["consensus"],
            conda_env={"name": "eggnogmapper_env", "dependencies": []},
            params=p,
        )

    def test_factory_returns_eggnogmapper_runner(self, tmp_path):
        from bactowise.runners.eggnogmapper_runner import EggNOGMapperRunner
        runner = RunnerFactory.create(self._make_tool_config(), tmp_path)
        assert isinstance(runner, EggNOGMapperRunner)

    def test_build_command_uses_consensus_faa(self, tmp_path):
        from bactowise.runners.eggnogmapper_runner import EggNOGMapperRunner
        from bactowise.utils.db_manager import _EGGNOG_DB_DIR
        # eggnogmapper output_dir is tmp_path/eggnogmapper
        runner = EggNOGMapperRunner(self._make_tool_config(), tmp_path, global_threads=4)
        # Create a fake consensus FAA so the command can be built
        faa = tmp_path / "eggnogmapper" / ".." / "consensus" / "GENE.faa"
        faa = faa.resolve()
        faa.parent.mkdir(parents=True, exist_ok=True)
        faa.touch()
        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._build_command(faa)
        assert "-i" in cmd
        assert str(faa) in cmd
        assert "--itype" in cmd
        assert "proteins" in cmd
        assert "-m" in cmd
        assert "diamond" in cmd
        assert "--data_dir" in cmd
        assert str(_EGGNOG_DB_DIR) in cmd
        assert "--tax_scope" in cmd
        assert "Bacteria" in cmd
        assert "--go_evidence" in cmd
        assert "--override" in cmd

    def test_consensus_faa_path_resolves_correctly(self, tmp_path):
        from bactowise.runners.eggnogmapper_runner import EggNOGMapperRunner
        runner = EggNOGMapperRunner(self._make_tool_config(), tmp_path, global_threads=4)
        faa = runner._consensus_faa_path()
        # Should point to <tmp_path>/consensus/GENE.faa
        assert faa.name == "GENE.faa"
        assert faa.parent.name == "consensus"

    def test_conda_run_cmd_uses_emapper_binary(self, tmp_path):
        from bactowise.runners.eggnogmapper_runner import EggNOGMapperRunner
        runner = EggNOGMapperRunner(self._make_tool_config(), tmp_path)
        with patch.object(runner, "_find_conda_binary", return_value="/usr/bin/conda"):
            cmd = runner._conda_run_cmd(["--version"])
        assert "emapper.py" in cmd
        assert "eggnogmapper_env" in cmd

    def test_eggnogmapper_in_stage_4(self, tmp_path):
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",       "version": "1.2.3",               "runtime": "conda", "role": "qc"},
                {"name": "prokka",       "version": "1.14.6",              "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",        "version": "1.9.3",               "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                        "depends_on": ["checkm"]},
                {"name": "pgap",         "version": "2024-07-18.build7555", "runtime": "pgap", "depends_on": ["checkm"]},
                {"name": "consensus",    "version": "1.0.0",               "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
                {"name": "eggnogmapper","version": "latest",               "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "eggnogmapper_env", "dependencies": []}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config)
        stages = pipeline._build_stages()
        assert stages[3] == ["eggnogmapper"]

    def test_eggnogmapper_skipped_with_stage_4(self, tmp_path):
        config = PipelineConfig(**{
            "tools": [
                {"name": "checkm",       "version": "1.2.3",               "runtime": "conda", "role": "qc"},
                {"name": "prokka",       "version": "1.14.6",              "runtime": "conda", "depends_on": ["checkm"]},
                {"name": "bakta",        "version": "1.9.3",               "runtime": "docker",
                 "image": "oschwengers/bakta:1.9.3",                        "depends_on": ["checkm"]},
                {"name": "pgap",         "version": "2024-07-18.build7555", "runtime": "pgap", "depends_on": ["checkm"]},
                {"name": "consensus",    "version": "1.0.0",               "runtime": "conda",
                 "depends_on": ["bakta", "prokka", "pgap"],
                 "conda_env": {"name": "consensus_env", "dependencies": ["pandas"]}},
                {"name": "eggnogmapper","version": "latest",               "runtime": "conda",
                 "depends_on": ["consensus"],
                 "conda_env": {"name": "eggnogmapper_env", "dependencies": []}},
            ],
            "output_dir": str(tmp_path),
        })
        with patch("docker.from_env") as mock_docker:
            mock_docker.return_value.ping.return_value = True
            pipeline = Pipeline(config, skip_stages={4})
        assert "eggnogmapper" in pipeline.skip
