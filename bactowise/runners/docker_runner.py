from __future__ import annotations

from pathlib import Path

from bactowise.models.config import ToolConfig
from bactowise.runners.base import BaseRunner


class DockerToolRunner(BaseRunner):
    """
    Runs tools inside Docker containers (e.g. Bakta, PGAP).
    Uses the Docker Python SDK to pull images, mount volumes, and stream logs.
    Swapping Bakta for PGAP is purely a config change — this class handles both.
    """

    def __init__(self, tool_config: ToolConfig, output_dir: Path):
        super().__init__(tool_config, output_dir)
        self.client = self._connect_to_docker()

    def _connect_to_docker(self):
        try:
            import docker
            client = docker.from_env()
            client.ping()
            return client
        except ImportError:
            raise RuntimeError(
                "The 'docker' Python package is not installed.\n"
                "Run: pip install docker"
            )
        except Exception:
            raise RuntimeError(
                "Cannot connect to Docker. Is Docker Desktop running?\n"
                "Start Docker Desktop and try again."
            )

    def preflight(self) -> None:
        print(f"\n[preflight] Checking docker tool: {self.config.name}")

        self._validate_required_fields()

        if self.config.database:
            db_path = self.config.database.path
            if not db_path.exists():
                raise RuntimeError(
                    f"  ✗  Database for {self.config.name} not found at: {db_path}\n"
                    f"     Run: bactowise db download --bakta"
                )
            print(f"  ✓  Database found at: {db_path}")

        image_ref = self.config.image
        print(f"  Checking Docker image: {image_ref}")
        self._ensure_image(image_ref)

    def _validate_required_fields(self) -> None:
        if self.config.name == "bakta":
            if not self.config.database:
                raise RuntimeError(
                    f"  ✗  Bakta requires a database path.\n"
                    f"     Add to pipeline.yaml:\n"
                    f"       database:\n"
                    f"         path: ~/.bactowise/databases/bakta\n"
                    f"         type: light\n"
                    f"     Then run: bactowise db download --bakta"
                )

    def _ensure_image(self, image_ref: str) -> None:
        import docker
        try:
            image = self.client.images.get(image_ref)
            labels = image.labels or {}
            installed_version = labels.get(
                "version",
                labels.get("org.opencontainers.image.version", "unknown")
            )
            if installed_version != "unknown":
                self._check_version(installed_version)
            else:
                print(f"  ✓  Image {image_ref} found locally.")
        except docker.errors.ImageNotFound:
            print(f"  Image {image_ref} not found locally. Pulling now (this may take a while)...")
            self._pull_image(image_ref)

    def _pull_image(self, image_ref: str) -> None:
        if ":" in image_ref:
            repo, tag = image_ref.rsplit(":", 1)
        else:
            repo, tag = image_ref, "latest"

        seen_layers = set()
        for line in self.client.api.pull(repo, tag=tag, stream=True, decode=True):
            layer_id = line.get("id", "")
            status   = line.get("status", "")
            if layer_id and layer_id not in seen_layers:
                seen_layers.add(layer_id)
                print(f"  [{layer_id}] {status}")
            elif not layer_id and status:
                print(f"  {status}")

        print(f"  ✓  Image {image_ref} pulled successfully.")

    def run(self, fasta: Path) -> Path:
        import docker

        print(f"\n[{self.config.name}] Starting annotation inside Docker...")

        volumes  = self._build_volumes(fasta)
        cmd      = self._build_command(fasta)
        log_file = self.log_dir / f"{self.config.name}.log"

        print(f"[{self.config.name}] Image:      {self.config.image}")
        print(f"[{self.config.name}] Command:    {cmd}")
        print(f"[{self.config.name}] Logging to: {log_file}")

        try:
            output: bytes = self.client.containers.run(
                self.config.image,
                command=cmd,
                volumes=volumes,
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
            )
            # containers.run(detach=False) returns combined stdout+stderr as bytes
            with open(log_file, "wb") as log:
                log.write(output if isinstance(output, bytes) else b"")

        except docker.errors.ContainerError as e:
            # The container ran but exited with a non-zero code.
            # ContainerError carries stderr; write it to the log so the user
            # can diagnose the failure, then re-raise with a clear message.
            stderr_bytes = e.stderr if isinstance(e.stderr, bytes) else b""
            with open(log_file, "wb") as log:
                log.write(stderr_bytes)
            raise RuntimeError(
                f"[{self.config.name}] Container exited with error (code {e.exit_status}).\n"
                f"Check logs at: {log_file}"
            ) from e

        except docker.errors.ImageNotFound as e:
            raise RuntimeError(
                f"[{self.config.name}] Docker image not found: {self.config.image}\n"
                f"Run preflight checks first: bactowise validate -c pipeline.yaml"
            ) from e

        except docker.errors.APIError as e:
            raise RuntimeError(
                f"[{self.config.name}] Docker API error: {e}\n"
                f"Check logs at: {log_file}"
            ) from e

        print(f"[{self.config.name}] ✓ Finished. Output at: {self.output_dir}")
        return self.output_dir

    def _build_volumes(self, fasta: Path) -> dict:
        volumes = {
            str(fasta.parent.resolve()): {"bind": "/input",  "mode": "ro"},
            str(self.output_dir.resolve()): {"bind": "/output", "mode": "rw"},
        }
        if self.config.database:
            volumes[str(self.config.database.path)] = {"bind": "/db", "mode": "ro"}
        return volumes

    def _build_command(self, fasta: Path) -> str:
        if self.config.name == "bakta":
            return self._bakta_command(fasta)
        if self.config.name == "pgap":
            return self._pgap_command(fasta)
        return f"--input /input/{fasta.name} --output /output"

    def _bakta_command(self, fasta: Path) -> str:
        cmd = f"/input/{fasta.name} --db /db --output /output --force"
        for key, val in self.config.params.items():
            cmd += f" --{key} {val}"
        return cmd

    def _pgap_command(self, fasta: Path) -> str:
        cmd = (
            f"--fasta /input/{fasta.name} "
            f"--output /output "
            f"--database /db"
        )
        for key, val in self.config.params.items():
            cmd += f" --{key} {val}"
        return cmd
